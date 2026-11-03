"""Мутабельное состояние навигации UI (план D2 §3.2).

Пишется только из main loop (drain ui_queue) → render-проход читает
без замка. Поток MIDI-колбэка сюда не лезет.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.app.ui.screen_id import ScreenId

DEFAULT_FLASH_SECONDS = 3.0
PAGE_SIZE = 8  # дорожек на странице экрана TRACKS
DEMO_VALUE_COUNT = 6  # энкодеры E3–E8 демо-экрана (0..127)
DEMO_VALUE_DEFAULT = 64  # старт посередине — бары видны сразу


@dataclass
class UiState:
    """Состояние навигации: экран, страница, курсор, flash, макро-CC.

    Атрибуты:
        screen: Текущий экран (таб).
        page: Банк дорожек на TRACKS (0 = дорожки 1–8).
        selected: Курсор в рамках страницы (TRACKS) или списка (PORTS).
        flash_text: Transient-сообщение (ошибка/подтверждение) или None.
        flash_deadline: ``time.monotonic()`` дедлайн flash-сообщения.
        macro_cc: Performance-CC слой: ``(track_name, axis) → 0..127``.
            Живёт в рантайме: переживает смену экранов, не переживает
            restart — осознанно.
        shift: Удержание Shift (модификатор Shift+Delete и т.п.).
        ports_route_track: Имя дорожки для назначения порта (экран PORTS).
        wizard_kind: Шаг wizard'а создания дорожки: ``"kind"`` (выбор
            Melodic/Drum), ``"profile"`` (профиль melodic) или ``"route"``
            (порт: «—» или порт снапшота).
        wizard_index: Курсор внутри шага wizard'а.
        wizard_profile: Выбранный на шаге profile профиль; None — drum
            (или шаг ещё не пройдён). Нужен, чтобы шаг route знал, что создавать.
    """

    screen: ScreenId = ScreenId.TRACKS
    selected: int = 0
    flash_text: str | None = None
    flash_deadline: float = 0.0
    macro_cc: dict[tuple[str, str], int] = field(default_factory=dict)
    shift: bool = False
    ports_route_track: str | None = None
    wizard_kind: str = "kind"
    wizard_index: int = 0
    wizard_profile: str | None = None
    setup_tab: int = 0  # активная суб-вкладка SETUP (индекс в SETUP_TABS)
    delete_armed: bool = False  # Delete вооружён: следующий LOWER ROW удалит
    demo_top: int = 0  # DEMO: активная верхняя вкладка (E1)
    demo_bottom: int = 0  # DEMO: активная нижняя вкладка (E2)
    demo_values: tuple[int, ...] = (DEMO_VALUE_DEFAULT,) * DEMO_VALUE_COUNT

    @property
    def page(self) -> int:
        """Страница банка дорожек: производная от ``selected`` (только дорожные экраны)."""
        return self.selected // PAGE_SIZE

    def flash(self, text: str, now: float, ttl: float = DEFAULT_FLASH_SECONDS) -> None:
        """Показать transient-сообщение до ``now + ttl`` (не блокирует UI)."""
        self.flash_text = text
        self.flash_deadline = now + ttl

    def flash_expired(self, now: float) -> bool:
        """True, когда flash-сообщение протухло (или его нет)."""
        return self.flash_text is None or now >= self.flash_deadline

    def clear_flash(self) -> None:
        """Снять flash-сообщение досрочно."""
        self.flash_text = None
        self.flash_deadline = 0.0

    def visible_flash(self, now: float) -> str | None:
        """Текст flash, если он ещё жив; иначе None."""
        return None if self.flash_expired(now) else self.flash_text

    def macro_value(self, track_name: str, axis: str) -> int:
        """Сохранённое значение оси (0..127) для дорожки; default 0."""
        return self.macro_cc.get((track_name, axis), 0)

    def set_macro_value(self, track_name: str, axis: str, value: int) -> int:
        """Кламп 0..127 + сохранить; возвращает фактическое значение."""
        clamped = max(0, min(127, int(value)))
        self.macro_cc[(track_name, axis)] = clamped
        return clamped
