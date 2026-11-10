#!/usr/bin/env python3
"""
carla_plugins.py — получение списка плагинов, доступных Carla.

Два независимых источника данных:

  1. КАТАЛОГ (по умолчанию) — всё, что Carla может загрузить.
     Работает через утилиту `carla-discovery`, которую Carla использует
     сама при сканировании. Для типов с кэшем (INTERNAL, LV2, AU, SFZ,
     JSFX) достаточно `carla-discovery <TYPE> :all`. Для форматов, которые
     нельзя перечислить из кэша (LADSPA, DSSI, VST2, VST3, CLAP),
     скрипт сам обходит каталоги и опрашивает каждый бинарник отдельно —
     ровно так же, как это делает GUI Carla.

  2. ЗАГРУЖЕННЫЕ (--osc) — только плагины, уже открытые в работающем
     экземпляре Carla. OSC-интерфейс Carla не умеет перечислять каталог,
     он умеет отдавать /info по каждому загруженному плагину.

Примеры:

    ./carla_plugins.py                      # весь каталог, таблицей
    ./carla_plugins.py -f lv2 vst3          # только LV2 и VST3
    ./carla_plugins.py --json > plugins.json
    ./carla_plugins.py --search reverb
    ./carla_plugins.py --osc                # что сейчас загружено

Зависимости: только стандартная библиотека.
Для --osc нужен pyliblo3 (или liblo): pip install pyliblo3
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# Типы плагинов (значения PluginType из CarlaBackend.h)
# --------------------------------------------------------------------------

PLUGIN_TYPES = {
    "internal": 1,
    "ladspa": 2,
    "dssi": 3,
    "lv2": 4,
    "vst2": 5,
    "vst3": 6,
    "au": 7,
    "sf2": 10,
    "sfz": 11,
    "jsfx": 13,
    "clap": 14,
}

# Типы, которые Carla умеет отдавать из кэша целиком ("carla-discovery TYPE :all")
CACHED_TYPES = {"internal", "lv2", "au", "sfz", "jsfx"}

# Что искать в файловой системе для остальных типов
WALKABLE = {
    "ladspa": (r"\.so$|\.dylib$|\.dll$", False),
    "dssi": (r"\.so$|\.dylib$|\.dll$", False),
    "vst2": (r"\.so$|\.dylib$|\.dll$|\.vst$", False),
    "vst3": (r"\.vst3$", True),      # бандл-каталог
    "clap": (r"\.clap$", True),
}

PTYPE_NAMES = {
    1: "Internal", 2: "LADSPA", 3: "DSSI", 4: "LV2", 5: "VST2",
    6: "VST3", 7: "AU", 8: "DLS", 9: "GIG", 10: "SF2", 11: "SFZ",
    12: "JACK", 13: "JSFX", 14: "CLAP",
}

CATEGORY_NAMES = {
    0: "none", 1: "synth", 2: "delay", 3: "eq", 4: "filter",
    5: "distortion", 6: "dynamics", 7: "modulator", 8: "reverb",
    9: "utility", 10: "other",
}


# --------------------------------------------------------------------------
# Поиск исполняемого файла carla-discovery
# --------------------------------------------------------------------------

def find_discovery_tool(explicit: str | None = None) -> str:
    """Ищет carla-discovery рядом с Carla или в PATH."""
    candidates = []
    if explicit:
        candidates.append(explicit)

    candidates += [
        "carla-discovery",
        "carla-discovery-64",
        "carla-discovery-32",
        "carla-discovery-win64",
        "carla-discovery-win32",
    ]

    # Стандартные места установки: рядом с самим carla
    for carla_bin in ("carla", "/usr/bin/carla", "/usr/local/bin/carla"):
        path = shutil.which(carla_bin)
        if path:
            # /usr/bin/carla -> /usr/lib/carla/carla-discovery-*, etc.
            d = Path(path).parent
            for sub in ("", "..", "../lib/carla", "../lib64/carla"):
                p = (d / sub).resolve()
                for name in ("carla-discovery-64", "carla-discovery"):
                    if (p / name).is_file():
                        candidates.insert(0, str(p / name))

    for name in candidates:
        found = shutil.which(name) if os.sep not in name else (
            name if Path(name).is_file() else None)
        if found:
            return found

    raise SystemExit(
        "Не найден carla-discovery.\n"
        "Укажите путь вручную:  ./carla_plugins.py --discovery /usr/lib/carla/carla-discovery-64\n"
        "Или установите Carla пакетом, где утилита кладётся рядом с бинарником."
    )


# --------------------------------------------------------------------------
# Разбор вывода carla-discovery
#
# Формат (по одному ключу на строку):
#   carla-discovery::init::------------
#   carla-discovery::name::Calf Reverb
#   carla-discovery::label::.../calf_reverb.so
#   carla-discovery::end::------------
# --------------------------------------------------------------------------

PREFIX = "carla-discovery::"


def parse_discovery_output(text: str, ptype: str) -> list[PluginInfo]:
    plugins: list[PluginInfo] = []
    current: dict[str, str] | None = None
    errors: list[str] = []

    for raw in text.splitlines():
        if not raw.startswith(PREFIX):
            continue

        _, key, value = raw.split("::", 2)

        if key == "init":
            current = {}
        elif key == "end":
            if current is not None:
                plugins.append(_to_plugin(current, ptype, errors))
            current = None
        elif key == "error":
            errors.append(value)
            # ошибка внутри блока — плагин невалиден
        elif current is not None:
            current[key] = value
        elif key in ("name", "label"):
            # некоторые форматы не печатают init/end
            current = {key: value}

    if current is not None:
        plugins.append(_to_plugin(current, ptype, errors))

    return [p for p in plugins if p.name or p.label]


def _to_plugin(d: dict[str, str], ptype: str, errors: list[str]) -> PluginInfo:
    def as_int(key: str, default: int = 0) -> int:
        try:
            return int(d.get(key, "") or default)
        except ValueError:
            return default

    return PluginInfo(
        ptype=ptype,
        ptype_id=PLUGIN_TYPES.get(ptype, 0),
        name=d.get("name", ""),
        label=d.get("label", ""),
        maker=d.get("maker", ""),
        category_name=d.get("category", ""),
        binary=d.get("build", ""),
        unique_id=as_int("uniqueId", -1),
        hints=as_int("hints"),
        audio_ins=as_int("audio.ins"),
        audio_outs=as_int("audio.outs"),
        midi_ins=as_int("midi.ins"),
        midi_outs=as_int("midi.outs"),
        cv_ins=as_int("cv.ins"),
        cv_outs=as_int("cv.outs"),
        parameter_ins=as_int("parameters.ins"),
        parameter_outs=as_int("parameters.outs"),
    )


# --------------------------------------------------------------------------
# Модель
# --------------------------------------------------------------------------

@dataclass
class PluginInfo:
    ptype: str
    ptype_id: int
    name: str
    label: str
    maker: str = ""
    category_name: str = ""
    binary: str = ""
    unique_id: int = -1
    hints: int = 0
    audio_ins: int = 0
    audio_outs: int = 0
    midi_ins: int = 0
    midi_outs: int = 0
    cv_ins: int = 0
    cv_outs: int = 0
    parameter_ins: int = 0
    parameter_outs: int = 0

    @property
    def is_synth(self) -> bool:
        # PLUGIN_IS_SYNTH = 0x004 в CarlaBackend.h
        return self.category_name == "synth" or (self.hints & 0x004) != 0

    @property
    def io_summary(self) -> str:
        parts = []
        if self.audio_ins or self.audio_outs:
            parts.append(f"a{self.audio_ins}→{self.audio_outs}")
        if self.midi_ins or self.midi_outs:
            parts.append(f"m{self.midi_ins}→{self.midi_outs}")
        if self.cv_ins or self.cv_outs:
            parts.append(f"cv{self.cv_ins}→{self.cv_outs}")
        return " ".join(parts)


# --------------------------------------------------------------------------
# Пути поиска
# --------------------------------------------------------------------------

HOME = Path.home()

DEFAULT_PATHS = {
    "ladspa": [
        HOME / ".ladspa",
        Path("/usr/local/lib/ladspa"),
        Path("/usr/lib/ladspa"),
        ],
    "dssi": [
        HOME / ".dssi",
        Path("/usr/local/lib/dssi"),
        Path("/usr/lib/dssi"),
        ],
    "lv2": [
        HOME / ".lv2",
        Path("/usr/local/lib/lv2"),
        Path("/usr/lib/lv2"),
        ],
    "vst2": [
        HOME / ".vst",
        HOME / ".lxvst",
        Path("/usr/local/lib/vst"),
        Path("/usr/local/lib/lxvst"),
        Path("/usr/lib/vst"),
        Path("/usr/lib/lxvst"),
        ],
    "vst3": [
        HOME / ".vst3",
        Path("/usr/local/lib/vst3"),
        Path("/usr/lib/vst3"),
        ],
    "clap": [
        HOME / ".clap",
        Path("/usr/local/lib/clap"),
        Path("/usr/lib/clap"),
        ],
}

ENV_OVERRIDES = {
    "ladspa": "LADSPA_PATH",
    "dssi": "DSSI_PATH",
    "lv2": "LV2_PATH",
    "vst2": "VST_PATH",
    "vst3": "VST3_PATH",
    "clap": "CLAP_PATH",
}


def search_paths(ptype: str, extra: str | None = None) -> list[Path]:
    env = ENV_OVERRIDES.get(ptype)
    if env and os.environ.get(env):
        raw = os.environ[env]
    elif extra:
        raw = extra
    else:
        return [p for p in DEFAULT_PATHS.get(ptype, []) if p.is_dir()]

    sep = ";" if os.name == "nt" else ":"
    return [Path(p).expanduser() for p in raw.split(sep) if p]


# --------------------------------------------------------------------------
# Сканирование
# --------------------------------------------------------------------------

def run_discovery(tool: str, ptype: str, target: str, timeout: int = 60) -> list[PluginInfo]:
    cmd = [tool, ptype.upper(), target]
    env = dict(os.environ)
    # Отключает тяжёлые проверки обработки — Carla выставляет это сама
    env.setdefault("CARLA_DISCOVERY_NO_PROCESSING_CHECKS", "1")

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"  ! таймаут: {target}", file=sys.stderr)
        return []
    except OSError as exc:
        print(f"  ! не удалось запустить {tool}: {exc}", file=sys.stderr)
        return []

    return parse_discovery_output(proc.stdout, ptype)


def find_bundles(ptype: str, roots: list[Path]) -> list[Path]:
    """Обходит каталоги и возвращает бинарники/бандлы нужного типа."""
    import re

    pattern, is_bundle = WALKABLE[ptype]
    rx = re.compile(pattern, re.IGNORECASE)
    found: list[Path] = []
    seen: set[Path] = set()

    for root in roots:
        if not root.is_dir():
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)

            # .vst3-бандл: берём целиком, внутрь не спускаемся
            if is_bundle and rx.search(here.name):
                if here not in seen:
                    seen.add(here)
                    found.append(here)
                dirnames[:] = []
                continue

            for fn in filenames:
                if not rx.search(fn):
                    continue
                full = here / fn
                if full not in seen:
                    seen.add(full)
                    found.append(full)

    return found


def scan_type(tool: str, ptype: str, extra_path: str | None,
              verbose: bool) -> list[PluginInfo]:
    results: list[PluginInfo] = []

    if ptype in CACHED_TYPES:
        # Один вызов на весь формат
        if verbose:
            print(f"  {ptype}: через кэш (carla-discovery {ptype.upper()} :all)",
                  file=sys.stderr)
        results = run_discovery(tool, ptype, ":all", timeout=120)
        return results

    if ptype not in WALKABLE:
        if verbose:
            print(f"  {ptype}: формат не поддерживает перечисление", file=sys.stderr)
        return results

    roots = search_paths(ptype, extra_path)
    if verbose:
        print(f"  {ptype}: каталоги {[str(r) for r in roots]}", file=sys.stderr)

    for bundle in find_bundles(ptype, roots):
        if verbose:
            print(f"    · {bundle}", file=sys.stderr)
        results.extend(run_discovery(tool, ptype, str(bundle)))

    return results


# --------------------------------------------------------------------------
# Режим OSC — список загруженных в работающем экземпляре
# --------------------------------------------------------------------------

def _import_liblo():
    """Возвращает модуль liblo и имена констант протокола для него."""
    try:
        import pyliblo3 as lo  # type: ignore
    except ModuleNotFoundError:
        try:
            import liblo as lo  # type: ignore
        except ModuleNotFoundError:
            raise SystemExit(
                "Для --osc нужен liblo:\n"
                "    pip install pyliblo3\n"
                "(или системный пакет python3-liblo / python3-pyliblo3)"
            )

    # pyliblo3 объявляет LO_TCP/LO_UDP, старый pyliblo — TCP/UDP
    tcp = getattr(lo, "LO_TCP", getattr(lo, "TCP", None))
    udp = getattr(lo, "LO_UDP", getattr(lo, "UDP", None))
    if tcp is None or udp is None:
        raise SystemExit("Установленная версия liblo не предоставляет константы протоколов")

    return lo, tcp, udp


def list_loaded_via_osc(address: str, timeout: float = 3.0,
                        via_udp: bool = False) -> list[dict]:
    """
    Список плагинов, загруженных в работающем экземпляре Carla.

    Carla отдаёт /info только зарегистрированному клиенту, причём стартовую
    пачку (ENGINE_STARTED + PLUGIN_ADDED + /info на каждый плагин) присылает
    ТОЛЬКО по TCP-регистрации. Поэтому по умолчанию регистрируемся по TCP.
    """
    lo, LO_TCP, LO_UDP = _import_liblo()
    import time

    proto = LO_UDP if via_udp else LO_TCP

    target = lo.Address(address)

    # Порт None -> liblo выбирает свободный. Порт "0" даёт URL с :0,
    # по которому реально не привяжешься, поэтому именно None.
    server = lo.Server(None, proto)
    our_url = server.get_url()

    # get_url() подставляет имя хоста машины. Если Carla на localhost,
    # анонсируем 127.0.0.1: на macOS/минимальных контейнерах hostname
    # может не резолвиться, и Carla не сможет прислать ответ.
    try:
        tgt_host = target.get_hostname()
    except Exception:
        tgt_host = ""
    if tgt_host in ("127.0.0.1", "localhost", "::1"):
        scheme, rest = our_url.split("://", 1)
        _hostport, _, tail = rest.partition("/")
        port = _hostport.rsplit(":", 1)[-1]
        our_url = f"{scheme}://127.0.0.1:{port}/{tail}"
    own_path = our_url.rsplit("/", 1)[-1]  # имя, которое мы дали в /register (пусто)

    collected: list[dict] = []
    errors: list[str] = []
    finished = {"done": False}
    registered = {"ok": False}

    def on_message(path, args, types, src):
        p = str(path)
        tail = p.rsplit("/", 1)[-1]

        # любой ответ по нашему пути означает, что регистрация прошла
        registered["ok"] = True

        if tail == "info":
            args = list(args)
            if len(args) < 14:
                return
            (pid, ptype, category, hints, unique_id, opts_avail, opts_enabled,
             name, filename, icon, realname, label, maker, copyright) = args[:14]
            collected.append({
                "pluginId": pid,
                "ptype": PTYPE_NAMES.get(ptype, str(ptype)),
                "category": CATEGORY_NAMES.get(category, str(category)),
                "name": str(name),
                "label": str(label),
                "maker": str(maker),
                "filename": str(filename),
                "realName": str(realname),
                "uniqueId": unique_id,
                "audioIns": 0, "audioOuts": 0,
                "midiIns": 0, "midiOuts": 0,
                "parameters": 0,
            })
            return

        if tail == "ports":
            # id, audioIn, audioOut, midiIn, midiOut, paramIns, paramOuts, paramTotal
            args = list(args)
            if len(args) < 8:
                return
            pid, a_in, a_out, m_in, m_out, _pi, _po, ptotal = args[:8]
            for entry in collected:
                if entry["pluginId"] == pid:
                    entry.update(audioIns=a_in, audioOuts=a_out,
                                 midiIns=m_in, midiOuts=m_out, parameters=ptotal)
                    break
            return

        if tail == "exit-error":
            errors.append(str(args[0]) if args else "неизвестная ошибка")
            finished["done"] = True
            return

    # wildcard: путь заранее неизвестен — Carla шлёт на <наш path>/info
    server.add_method(None, None, on_message)

    try:
        lo.send(target, "/register", our_url)
    except OSError as exc:
        server.free()
        raise SystemExit(
            f"Не удалось отправить /register на {address}: {exc}\n"
            "Проверьте, что Carla запущена, OSC включён (Настройки → Engine → OSC)\n"
            "и что порт совпадает с тем, что показан в Help → About → вкладка OSC."
        )

    deadline = time.time() + timeout
    idle_since = None
    seen = 0

    while time.time() < deadline:
        if finished["done"]:
            break
        server.recv(100)

        if len(collected) != seen:
            seen = len(collected)
            idle_since = time.time()
        elif idle_since is not None and time.time() - idle_since > 0.5:
            # тишина полсекунды после последнего /info — считаем, что отдали всё
            break

    try:
        lo.send(target, "/unregister", our_url)
    except Exception:
        pass

    server.free()

    if errors:
        raise SystemExit(
            "Carla отказала в регистрации: " + "; ".join(errors) + "\n"
                                                                   "Скорее всего, к этому экземпляру уже подключён другой OSC-клиент "
                                                                   "(например, carla-control). OSC допускает только одного."
        )

    unique: dict[int, dict] = {}
    for entry in collected:
        unique.setdefault(entry["pluginId"], entry)

    result = sorted(unique.values(), key=lambda e: e["pluginId"])

    # пустой ответ при неудавшейся регистрации — это не «нет плагинов»
    if not result and not registered["ok"] and not errors:
        raise SystemExit(
            f"Carla не ответила на /register за {timeout:g} с.\n"
            "Возможные причины:\n"
            "  · OSC выключен (Настройки → Engine → OSC)\n"
            "  · неверный порт — сверьтесь с Help → About → вкладка OSC\n"
            "  · Carla слушает другой интерфейс, а не 127.0.0.1\n"
            "  · занятый клиент: OSC разрешает только одно подключение"
        )

    return result


# --------------------------------------------------------------------------
# Вывод
# --------------------------------------------------------------------------

def print_table(plugins: list[PluginInfo]) -> None:
    if not plugins:
        print("Ничего не найдено.")
        return

    rows = []
    for p in plugins:
        rows.append([
            p.ptype,
            p.name[:44],
            p.maker[:24],
            p.category_name[:12],
            p.io_summary,
        ])

    widths = [max(len(r[i]) for r in rows + [["Type", "Name", "Maker", "Category", "IO"]])
              for i in range(5)]

    header = ["Type", "Name", "Maker", "Category", "IO"]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(header))
    print(line)
    print("-" * len(line))

    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))

    print()
    print(f"Всего: {len(plugins)}")

    by_type: dict[str, int] = {}
    for p in plugins:
        by_type[p.ptype] = by_type.get(p.ptype, 0) + 1
    print("По форматам: " + ", ".join(
        f"{k}={v}" for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Список плагинов, доступных Carla.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Примеры:")[1] if "Примеры:" in __doc__ else None,
    )
    ap.add_argument("-f", "--format", nargs="+", default=None,
                    choices=sorted(PLUGIN_TYPES),
                    help="форматы (по умолчанию: все поддерживаемые)")
    ap.add_argument("--path", default=None,
                    help="дополнительный каталог поиска (через ':' )")
    ap.add_argument("--discovery", default=None,
                    help="путь к carla-discovery")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    ap.add_argument("--search", default=None,
                    help="фильтр по подстроке в имени/производителе")
    ap.add_argument("--synth", action="store_true", help="только синтезаторы")
    ap.add_argument("--osc", nargs="?", const="osc.tcp://127.0.0.1:22752/Carla",
                    default=None, metavar="ADDR",
                    help="список ЗАГРУЖЕННЫХ плагинов через OSC")
    ap.add_argument("--osc-udp", action="store_true",
                    help="регистрироваться по UDP вместо TCP (стартовую пачку "
                         "плагинов Carla отдаёт только по TCP)")
    ap.add_argument("--timeout", type=float, default=3.0,
                    help="сколько ждать ответов OSC, сек (по умолчанию 3)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    # --- режим OSC ---
    if args.osc:
        if args.verbose:
            print(f"OSC: {args.osc}  (udp={args.osc_udp})", file=sys.stderr)
        loaded = list_loaded_via_osc(args.osc, timeout=args.timeout,
                                     via_udp=args.osc_udp)
        if args.json:
            print(json.dumps(loaded, ensure_ascii=False, indent=2))
        else:
            print(f"Загружено плагинов: {len(loaded)}\n")
            for p in loaded:
                print(f"  [{p['pluginId']:>3}] {p['name']}")
                io = f"a{p['audioIns']}→{p['audioOuts']}"
                if p["midiIns"] or p["midiOuts"]:
                    io += f" m{p['midiIns']}→{p['midiOuts']}"
                print(f"        {p['ptype']} / {p['category']}"
                      f" / {p['maker'] or '—'} / {io}")
                if p.get("label"):
                    print(f"        label: {p['label']}")
            if not loaded:
                print("Пусто. Либо в Carla ничего не загружено,\n"
                      "либо не сработала регистрация — проверьте адрес и порт.")
        return 0

    # --- режим каталога ---
    tool = find_discovery_tool(args.discovery)
    if args.verbose:
        print(f"carla-discovery: {tool}\n", file=sys.stderr)

    formats = args.format or sorted(CACHED_TYPES | set(WALKABLE))

    all_plugins: list[PluginInfo] = []
    for ptype in formats:
        if args.verbose:
            print(f"[{ptype}]", file=sys.stderr)
        all_plugins.extend(scan_type(tool, ptype, args.path, args.verbose))

    # дедупликация: один и тот же плагин может найтись через разные каталоги
    unique: dict[tuple, PluginInfo] = {}
    for p in all_plugins:
        key = (p.ptype, p.label or p.name, p.unique_id)
        unique.setdefault(key, p)
    all_plugins = list(unique.values())

    if args.search:
        needle = args.search.lower()
        all_plugins = [p for p in all_plugins
                       if needle in p.name.lower() or needle in p.maker.lower()
                       or needle in p.label.lower()]

    if args.synth:
        all_plugins = [p for p in all_plugins if p.is_synth]

    all_plugins.sort(key=lambda p: (p.ptype, p.name.lower()))

    if args.json:
        print(json.dumps([asdict(p) for p in all_plugins],
                         ensure_ascii=False, indent=2))
    else:
        print_table(all_plugins)

    return 0


if __name__ == "__main__":
    sys.exit(main())
