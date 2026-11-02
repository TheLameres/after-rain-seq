#!/usr/bin/env python3
"""
Spike: pycairo/cairocffi для отрисовки UI Push 2 (960×160).

Вопрос: может ли cairo заменить numpy-примитивы из plan_d1_renderer.md?

Что меряем:
  1. Полный кадр типичного экрана (фон, 8 track-баров, 3 global, статус-текст)
  2. Dirty-перерисовка одного виджета через clip
  3. Конвертация cairo ARGB32 → BGR565 (wire format Push 2)
  4. Конвертация → полный wire payload (filler + XOR + byteswap)

Запуск:
  python -m pip install --target /tmp/cairo_spike cairocffi
  PYTHONPATH=/tmp/cairo_spike python spikes/spike_cairo_bench.py
"""

import time
from statistics import mean, median

import numpy as np

try:
    import ctypes
    import ctypes.util

    _lib = ctypes.util.find_library("cairo")
    if _lib is None:  # macOS: homebrew не в dyld-путях — грузим абсолютным путём
        import glob

        _candidates = glob.glob("/opt/homebrew/lib/libcairo.2.dylib") + glob.glob(
            "/usr/local/lib/libcairo.2.dylib"
        )
        if _candidates:
            ctypes.CDLL(_candidates[0], mode=ctypes.RTLD_GLOBAL)
    import cairocffi as cairo  # чистое wheel; требует libcairo в рантайме
except OSError as exc:  # libcairo не найден
    raise SystemExit(f"libcairo не загрузился: {exc}\n")

W, H = 960, 160
N_ITERS = 300

# ── буфер кадра: cairo ARGB32 = uint8 (H, W, 4), little-endian порядок B,G,R,A ──
buf = np.zeros((H, W, 4), dtype=np.uint8)
surface = cairo.ImageSurface.create_for_data(
    buf, cairo.FORMAT_ARGB32, W, H, stride=W * 4
)
ctx = cairo.Context(surface)

# предвыделенный wire-буфер: (1024, 160) uint16 → 160 строк × (960 px + 64 filler)
FRAME_WIDTH = 960 + 64
wire = np.zeros((FRAME_WIDTH, H), dtype=np.uint16)
XOR_PATTERN = np.array([0xE7F3, 0xE7FF] * (FRAME_WIDTH * H // 2), dtype=np.uint16)

# wire-представление повёрнуто: (160, 1024) view для построчной записи
wire_t = wire.transpose()


def to_bgr565():
    """cairo ARGB32 (H, W, 4) → BGR565 uint16 (W, H) — как у Push2UsbDisplay."""
    b = buf[:, :, 0].astype(np.uint16)  # (H, W), порядок каналов B,G,R,A
    g = buf[:, :, 1].astype(np.uint16)
    r = buf[:, :, 2].astype(np.uint16)
    out = ((b >> 3) << 11) | ((g >> 2) << 5) | (r >> 3)
    return out.transpose()  # (W, H)


def encode_wire():
    """BGR565 (W,H) → полный wire payload: filler + transpose + byteswap + XOR."""
    frame = to_bgr565()
    wire[:960, :] = frame
    prepared = wire.transpose().flatten()
    prepared.byteswap(inplace=True)
    np.bitwise_xor(prepared, XOR_PATTERN, out=prepared)
    prepared.byteswap(inplace=True)
    return prepared.tobytes()


def draw_full_frame(vals: list[int]):
    """Типичный кадр: фон + 8 track-баров с подписями + 3 global + статус."""
    # фон
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    # 8 трековых колонок: подпись + фон бара + заливка
    for i in range(8):
        x = i * 120 + 6
        v = vals[i]
        ctx.set_source_rgb(0.62, 0.62, 0.67)
        ctx.set_font_size(10)
        ctx.move_to(x, 36)
        ctx.show_text(f"T{i + 1}:{v:3d}")
        ctx.set_source_rgb(0.11, 0.11, 0.16)
        ctx.rectangle(x, 40, 108, 10)
        ctx.fill()
        ctx.set_source_rgb(0.22, 0.57, 0.88)
        ctx.rectangle(x, 40, max(1, 108 * v // 127), 10)
        ctx.fill()
    # 3 global-бара
    for i, key in enumerate(("TMP", "SWG", "MST")):
        x = i * 320 + 6
        v = vals[8 + i]
        ctx.set_source_rgb(0.62, 0.62, 0.67)
        ctx.set_font_size(14)
        ctx.move_to(x, 68)
        ctx.show_text(f"{key}:{v:3d}")
        ctx.set_source_rgb(0.11, 0.11, 0.16)
        ctx.rectangle(x, 72, 308, 10)
        ctx.fill()
        ctx.set_source_rgb(0.22, 0.57, 0.88)
        ctx.rectangle(x, 72, max(1, 308 * v // 127), 10)
        ctx.fill()
    # статус-бар
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_font_size(12)
    ctx.move_to(4, 152)
    ctx.show_text(f"BPM: {120 + vals[0] * 0.1:.1f}   A dorian   LINK: 2")


def draw_status_only(bpm: float):
    """Dirty-перерисовка: только статус-бар через clip (y 138–160)."""
    ctx.save()
    ctx.reset_clip()
    ctx.rectangle(0, 138, W, 22)
    ctx.clip()
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_font_size(12)
    ctx.move_to(4, 152)
    ctx.show_text(f"BPM: {bpm:.1f}   A dorian   LINK: 2")
    ctx.restore()


def bench(fn, name, *args):
    times = []
    for k in range(N_ITERS):
        t0 = time.perf_counter()
        fn(*args)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"  {name:38s} mean {mean(times):6.3f} ms  median {median(times):6.3f} ms")
    return mean(times)


if __name__ == "__main__":
    print("=== Cairo → Push 2 spike (cairocffi, libcairo "
          f"{cairo.cairo_version_string()}) ===")
    print(f"Поверхность: {W}×{H} ARGB32, {W * H * 4} байт")

    # разогрев (JIT/caches, загрузка шрифта)
    draw_full_frame([64] * 11)
    encode_wire()

    print("\n--- 1. Полный кадр ---")
    full_ms = bench(lambda: draw_full_frame([64, 90, 32, 110, 64, 75, 20, 100,
                                             100, 55, 80]), "draw_full_frame")

    print("\n--- 2. Dirty-перерисовка (статус-бар через clip) ---")
    k = [0]
    def dirty_tick():
        k[0] += 1
        draw_status_only(120 + k[0] * 0.1)
    dirty_ms = bench(dirty_tick, "draw_status_only (clip)")

    print("\n--- 3. Конвертация в wire format ---")
    conv_ms = bench(to_bgr565, "ARGB32 → BGR565 (W,H)")
    enc_ms = bench(encode_wire, "encode_wire (полный payload)")

    print("\n--- Итог: типичный тик (dirty draw + encode) ---")
    tick = dirty_ms + enc_ms
    print(f"  dirty-тик: {tick:.3f} ms (бюджет 40 ms @25 fps, цель плана ≤ 4 мс)")
    print(f"  полный кадр + encode: {full_ms + enc_ms:.3f} ms")
    print(f"  частота полного кадра: {1000 / (full_ms + enc_ms):.0f} fps")

    print("\n--- Проверка цвета ---")
    # мануал Ableton: bits 15..0 = b4..b0 g5..g0 r4..r0 → красный = 0x001F,
    # синий = 0xF800. Совпадает с legacy `_rgb_to_bgr565(255,0,0) == 0x001F`.
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    encode_wire()
    assert to_bgr565()[0, 0] == 0, "чёрный не 0x0000"
    ctx.set_source_rgb(1, 0, 0)
    ctx.rectangle(0, 0, 4, 4)
    ctx.fill()
    encode_wire()
    px = to_bgr565()[0, 0]
    print(f"  красный (1,0,0) → 0x{px:04X} (по мануалу Ableton ожидается 0x001F)")
    assert px == 0x001F, "BGR-перепутан"
    print("  ✓ порядок каналов B,G,R,A корректен и совпадает с legacy-кодом")
