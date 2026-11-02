"""Тесты UiState: flash TTL, макро-CC, дефолты навигации."""

from __future__ import annotations

from src.app.ui.screen_id import ScreenId
from src.app.ui.ui_state import DEFAULT_FLASH_SECONDS, UiState


class TestDefaults:
    def test_initial_state(self) -> None:
        st = UiState()
        assert st.screen is ScreenId.TRACKS
        assert st.page == 0
        assert st.selected == 0
        assert st.flash_text is None
        assert st.shift is False
        assert st.macro_cc == {}


class TestFlash:
    def test_flash_sets_deadline(self) -> None:
        st = UiState()
        st.flash("limit reached", now=100.0)
        assert st.flash_text == "limit reached"
        assert st.flash_deadline == 100.0 + DEFAULT_FLASH_SECONDS

    def test_flash_expiry(self) -> None:
        st = UiState()
        st.flash("oops", now=10.0, ttl=3.0)
        assert not st.flash_expired(now=12.9)
        assert st.flash_expired(now=13.0)
        # visible_flash отдаёт живой текст и None после дедлайна
        assert st.visible_flash(12.9) == "oops"
        assert st.visible_flash(13.0) is None

    def test_no_flash_is_expired(self) -> None:
        st = UiState()
        assert st.flash_expired(now=0.0)
        assert st.visible_flash(now=0.0) is None

    def test_flash_survives_screen_switch(self) -> None:
        st = UiState()
        st.flash("error: cycle", now=5.0)
        st.screen = ScreenId.SETUP
        assert st.visible_flash(now=6.0) == "error: cycle"

    def test_clear_flash(self) -> None:
        st = UiState()
        st.flash("x", now=0.0)
        st.clear_flash()
        assert st.flash_text is None
        assert st.flash_expired(now=0.0)

    def test_custom_ttl(self) -> None:
        st = UiState()
        st.flash("quick", now=0.0, ttl=0.5)
        assert st.flash_deadline == 0.5


class TestMacroCc:
    def test_macro_defaults_to_zero(self) -> None:
        st = UiState()
        assert st.macro_value("Pad 1", "TONE") == 0

    def test_macro_set_clamps(self) -> None:
        st = UiState()
        assert st.set_macro_value("Pad 1", "TONE", 200) == 127
        assert st.set_macro_value("Pad 1", "TONE", -5) == 0
        assert st.set_macro_value("Pad 1", "TONE", 64) == 64
        assert st.macro_value("Pad 1", "TONE") == 64

    def test_macro_per_track_and_axis(self) -> None:
        st = UiState()
        st.set_macro_value("Pad 1", "TONE", 30)
        st.set_macro_value("Bass 1", "TONE", 90)
        st.set_macro_value("Pad 1", "SPACE", 60)
        assert st.macro_value("Pad 1", "TONE") == 30
        assert st.macro_value("Bass 1", "TONE") == 90
        assert st.macro_value("Pad 1", "SPACE") == 60


class TestScreenId:
    def test_values_stable(self) -> None:
        assert ScreenId.TRACKS.value == "tracks"
        assert ScreenId.TRACK_GEN.value == "gen"
        assert ScreenId.TRACK_MACRO.value == "macro"
        assert ScreenId.SCALE.value == "scale"
        assert ScreenId.SETUP.value == "setup"
        assert ScreenId.PORTS.value == "ports"
        assert ScreenId.WIZARD.value == "wizard"

    def test_tab_order_three_screens(self) -> None:
        """Табы дорожки: GEN → MACRO → PORTS (кольцо Right/Left)."""
        order = ScreenId.tab_order()
        assert len(order) == 3
        assert order[0] is ScreenId.TRACK_GEN
        assert order[1] is ScreenId.TRACK_MACRO
        assert order[2] is ScreenId.PORTS
        # Глобальные экраны и модалки — вне табов.
        assert ScreenId.TRACKS not in order
        assert ScreenId.SCALE not in order
        assert ScreenId.SETUP not in order
        assert ScreenId.WIZARD not in order
