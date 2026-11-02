#!/usr/bin/env python3
"""
Spike: Stress Test
10 минут нагрузки: CPU + мониторинг температуры и throttling.
"""

import time
import subprocess
import threading
import statistics

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠ psutil не установлен, CPU% не будет измеряться")


def get_temperature() -> float:
    """Читает температуру CPU."""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            temp_str = result.stdout.strip().split("=")[1].replace("'C", "")
            return float(temp_str)
    except (FileNotFoundError, subprocess.TimeoutExpired, IndexError, ValueError):
        pass
    
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read().strip()) / 1000.0
    except (FileNotFoundError, PermissionError):
        pass
    
    return -1.0


def get_throttled() -> str:
    """Проверяет throttling через vcgencmd."""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return "N/A"


def get_cpu_percent() -> float:
    """Возвращает текущий CPU%."""
    if HAS_PSUTIL:
        return psutil.cpu_percent(interval=0.1)
    return -1.0


def cpu_stress_worker(stop_event: threading.Event, duration: int):
    """Создаёт CPU-нагрузку."""
    end_time = time.time() + duration
    while not stop_event.is_set() and time.time() < end_time:
        _ = sum(i * i for i in range(10000))


def run_stress_test(duration: int = 600):
    """Запускает стресс-тест."""
    print("=== Stress Test Spike ===")
    print(f"Длительность: {duration} сек ({duration // 60} мин)")
    print()
    
    print(f"psutil: {'✓' if HAS_PSUTIL else '✗'}")
    print()
    
    stop_event = threading.Event()
    stress_thread = threading.Thread(
        target=cpu_stress_worker,
        args=(stop_event, duration),
        daemon=True
    )
    stress_thread.start()
    print("CPU-нагрузка запущена")
    print()
    
    temps = []
    cpu_percents = []
    throttled_flags = []
    
    start_time = time.time()
    last_report = start_time
    
    print("Мониторинг...")
    print("-" * 70)
    print(f"{'Время':>8} | {'Темп':>8} | {'CPU%':>8} | {'Throttled':>20}")
    print("-" * 70)
    
    try:
        while time.time() - start_time < duration:
            temp = get_temperature()
            cpu = get_cpu_percent()
            throttled = get_throttled()
            
            temps.append(temp)
            cpu_percents.append(cpu)
            throttled_flags.append(throttled)
            
            now = time.time()
            if now - last_report >= 30:
                elapsed = int(now - start_time)
                temp_str = f"{temp:.1f}°C" if temp > 0 else "N/A"
                cpu_str = f"{cpu:.1f}%" if cpu >= 0 else "N/A"
                print(f"{elapsed:>6}s | {temp_str:>8} | {cpu_str:>8} | {throttled:>20}")
                last_report = now
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print()
        print("Прервано пользователем")
    
    finally:
        stop_event.set()
    
    print()
    print("--- Результаты ---")
    
    if temps:
        valid_temps = [t for t in temps if t > 0]
        if valid_temps:
            print(f"Температура:")
            print(f"  Средняя: {statistics.mean(valid_temps):.1f}°C")
            print(f"  Максимум: {max(valid_temps):.1f}°C")
            print(f"  Минимум: {min(valid_temps):.1f}°C")
    
    if cpu_percents:
        valid_cpu = [c for c in cpu_percents if c >= 0]
        if valid_cpu:
            print(f"CPU%:")
            print(f"  Средний: {statistics.mean(valid_cpu):.1f}%")
            print(f"  Максимум: {max(valid_cpu):.1f}%")
    
    unique_throttled = set(throttled_flags)
    print(f"Throttling статусы: {unique_throttled}")
    
    has_throttling = any(t != "throttled=0x0" and t != "N/A" for t in unique_throttled)
    
    print()
    print("=== ИТОГ ===")
    
    max_temp = max([t for t in temps if t > 0], default=0)
    avg_cpu = statistics.mean([c for c in cpu_percents if c >= 0]) if cpu_percents else 0
    
    print(f"Макс. температура: {max_temp:.1f}°C")
    print(f"Средний CPU: {avg_cpu:.1f}%")
    print(f"Throttling: {'ДА' if has_throttling else 'НЕТ'}")
    
    passed = True
    if max_temp > 80:
        print("✗ Температура > 80°C")
        passed = False
    if avg_cpu > 70:
        print("✗ CPU > 70%")
        passed = False
    if has_throttling:
        print("✗ Обнаружен throttling")
        passed = False
    
    if passed:
        print("✓ ТЕСТ ПРОЙДЕН")
    else:
        print("✗ ТЕСТ НЕ ПРОЙДЕН")
    
    print()
    print("Готово.")


if __name__ == "__main__":
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    run_stress_test(duration)
