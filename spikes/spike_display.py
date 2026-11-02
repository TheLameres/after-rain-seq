#!/usr/bin/env python3
"""
Spike: Push 2 Display Test
Измеряет fps и стоимость кадра при рисовании на дисплее Push 2.
"""

import time
import usb.core
import usb.util
import numpy as np
from statistics import mean, median

# Push 2 USB IDs
VENDOR_ID = 0x2982
PRODUCT_ID = 0x1967

# Дисплей Push 2: 960x160 RGB16 (5-6-5)
WIDTH = 960
HEIGHT = 160
FRAME_SIZE = WIDTH * HEIGHT * 2

# USB endpoint для дисплея
DISPLAY_ENDPOINT = 0x01


def find_push2():
    """Находит Push 2 по USB."""
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise RuntimeError("Push 2 не найден. Проверь подключение.")
    
    for cfg in dev:
        for intf in cfg:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                dev.detach_kernel_driver(intf.bInterfaceNumber)
    
    dev.set_configuration()
    return dev


def create_test_frame(pattern: int = 0) -> bytes:
    """Создаёт тестовый кадр с паттерном."""
    frame = np.zeros((HEIGHT, WIDTH, 2), dtype=np.uint8)
    
    if pattern == 0:
        for x in range(WIDTH):
            r = int(255 * x / WIDTH)
            g = int(255 * (1 - x / WIDTH))
            b = 128
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            frame[:, x, 0] = rgb565 & 0xFF
            frame[:, x, 1] = (rgb565 >> 8) & 0xFF
    elif pattern == 1:
        for y in range(HEIGHT):
            color = 0xF800 if (y // 10) % 2 == 0 else 0x07E0
            frame[y, :, 0] = color & 0xFF
            frame[y, :, 1] = (color >> 8) & 0xFF
    else:
        noise = np.random.randint(0, 65536, (HEIGHT, WIDTH), dtype=np.uint16)
        frame[:, :, 0] = noise & 0xFF
        frame[:, :, 1] = (noise >> 8) & 0xFF
    
    return frame.tobytes()


def send_frame(dev, frame_data: bytes):
    """Отправляет кадр на дисплей Push 2."""
    CHUNK_SIZE = 16384
    for i in range(0, len(frame_data), CHUNK_SIZE):
        chunk = frame_data[i:i + CHUNK_SIZE]
        dev.write(DISPLAY_ENDPOINT, chunk)


def run_display_test(duration: int = 30):
    """Запускает тест дисплея."""
    print("=== Push 2 Display Spike ===")
    print(f"Разрешение: {WIDTH}x{HEIGHT}, RGB565")
    print(f"Размер кадра: {FRAME_SIZE / 1024:.1f} KB")
    print()
    
    print("Подключение к Push 2...")
    dev = find_push2()
    print("✓ Push 2 подключен")
    print()
    
    print("Подготовка тестовых кадров...")
    frames = [create_test_frame(i) for i in range(3)]
    print(f"✓ {len(frames)} кадров готово")
    print()
    
    print("--- Тест 1: Стоимость кадра ---")
    frame_times = []
    for i, frame in enumerate(frames * 10):
        t0 = time.perf_counter()
        send_frame(dev, frame)
        t1 = time.perf_counter()
        frame_times.append((t1 - t0) * 1000)
    
    print(f"Среднее: {mean(frame_times):.2f} ms")
    print(f"Медиана: {median(frame_times):.2f} ms")
    print(f"Мин: {min(frame_times):.2f} ms")
    print(f"Макс: {max(frame_times):.2f} ms")
    print()
    
    print(f"--- Тест 2: FPS ({duration} сек) ---")
    print("Рисуем...")
    
    frame_count = 0
    start_time = time.perf_counter()
    fps_history = []
    last_report = start_time
    
    while time.perf_counter() - start_time < duration:
        frame = frames[frame_count % len(frames)]
        send_frame(dev, frame)
        frame_count += 1
        
        now = time.perf_counter()
        if now - last_report >= 1.0:
            fps = frame_count / (now - last_report)
            fps_history.append(fps)
            print(f"  {now - start_time:5.1f}s: {fps:5.1f} fps")
            frame_count = 0
            last_report = now
    
    print()
    print("--- Результаты ---")
    print(f"Средний FPS: {mean(fps_history):.1f}")
    print(f"Минимальный FPS: {min(fps_history):.1f}")
    print(f"Максимальный FPS: {max(fps_history):.1f}")
    print()
    
    avg_frame_ms = mean(frame_times)
    theoretical_fps = 1000 / avg_frame_ms if avg_frame_ms > 0 else 0
    print("=== ИТОГ ===")
    print(f"Стоимость кадра: {avg_frame_ms:.2f} ms")
    print(f"Теоретический потолок FPS: {theoretical_fps:.0f}")
    print(f"Реальный средний FPS: {mean(fps_history):.1f}")
    
    if mean(fps_history) >= 25:
        print("✓ ТЕСТ ПРОЙДЕН: ≥25 fps")
    else:
        print("✗ ТЕСТ НЕ ПРОЙДЕН: <25 fps")
    
    usb.util.dispose_resources(dev)
    print()
    print("Готово.")


if __name__ == "__main__":
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_display_test(duration)
