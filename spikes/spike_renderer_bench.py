#!/usr/bin/env python3
"""
Spike: D1 renderer benchmark — стоимость кадра нового пайплайна (plan_d1_renderer.md §3.8).

Меряет:
  1. Полный compose (все 4 виджета) — цель ≤ 5 мс
  2. Типичный dirty-тик (BPM + один энкодер) — цель ≤ 2 мс
  3. Encode (FrameEncoder, без аллокаций) — цель ≤ 2 мс
  4. Сквозной fps при непрерывных dirty-тиках — цель ≥ 25 fps, p99 кадра < 40 мс

Запуск: python spikes/spike_renderer_bench.py [секунды]
"""

import sys
import time
from statistics import mean, median

from src.devices.push2.display import PushDisplay
from src.devices.push2.push2_display import FrameEncoder


def _state(bpm: float, track_val: int) -> dict:
    return {
        "push2_connected": True,
        "sync_bpm": bpm,
        "sync_link_peers": 0,
        "sync_link_active": False,
        "sync_clock_source": "internal",
    }


class _FakeUsb:
    """Заглушка USB-слоя: принимает кадр, не шлёт никуда."""

    def send_frame(self, _frame) -> None:
        pass


def bench(name: str, fn, iters: int) -> float:
    times = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    m = mean(times)
    print(f"  {name:44s} mean {m:6.3f} ms   median {median(times):6.3f} ms")
    return m


if __name__ == "__main__":
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    disp = PushDisplay(fps=25)
    usb = _FakeUsb()
    enc = FrameEncoder()

    # разогрев: шрифты, кеш глифов
    disp.update_state(**_state(120.0, 64))
    disp.render_usb(usb)

    print("=== D1 renderer bench (960×160, BGR565, numpy) ===\n")

    print("--- 1. Полный кадр (все регионы) ---")
    disp2 = PushDisplay(fps=25)  # свежий — все регионы грязные
    disp2.update_state(**_state(120.0, 64))

    def full_compose() -> None:
        disp2._dirty_regions.update({"header", "status"})  # noqa: SLF001
        disp2._compose()  # noqa: SLF001
        disp2._fb.dirty.take()  # noqa: SLF001

    full_ms = bench("compose: все регионы", full_compose, 300)

    print("\n--- 2. Типичный dirty-тик (BPM) ---")
    k = [0]

    def dirty_tick() -> None:
        k[0] += 1
        disp.update_state(**_state(120.0 + k[0] * 0.1, 64 + k[0] % 60))
        disp._compose()  # noqa: SLF001
        disp._fb.dirty.take()  # noqa: SLF001

    dirty_ms = bench("compose: dirty-тик (status)", dirty_tick, 1000)

    print("\n--- 3. Encode (wire payload, без аллокаций) ---")
    frame = disp._fb.pixels  # noqa: SLF001
    enc_ms = bench("FrameEncoder.encode", lambda: enc.encode(frame), 1000)

    print("\n--- 4. Сквозной прогон dirty-тиков + encode ---")
    tick_times = []
    start = time.perf_counter()
    while time.perf_counter() - start < duration:
        t0 = time.perf_counter()
        dirty_tick()
        enc.encode(disp._fb.pixels)  # noqa: SLF001
        tick_times.append((time.perf_counter() - t0) * 1000)
    tick_times.sort()
    p99 = tick_times[int(len(tick_times) * 0.99)]
    total_s = time.perf_counter() - start
    print(f"  тиков: {len(tick_times)} за {total_s:.1f} с")
    print(f"  средний тик: {mean(tick_times):.3f} ms   p99: {p99:.3f} ms")
    print(f"  максимальный поток: {len(tick_times) / total_s:.0f} тиков/с")

    print("\n--- Итог против критериев плана ---")
    checks = [
        ("compose полный кадр ≤ 5 мс", full_ms <= 5.0),
        ("compose dirty-тик ≤ 2 мс", dirty_ms <= 2.0),
        ("encode ≤ 2 мс", enc_ms <= 2.0),
        ("p99 тика < 40 мс (25 fps)", p99 < 40.0),
    ]
    for label, ok in checks:
        print(f"  {'✓' if ok else '✗'} {label}")
