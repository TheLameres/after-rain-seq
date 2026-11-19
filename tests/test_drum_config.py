"""Tests for DrumConfig — конфигурация drum-машины."""

import pytest
from pydantic import ValidationError

from src.config import DEFAULT_CONFIG_YAML, AppConfig, load_config
from src.session.drum.drum_config import DrumConfig

# ---------------------------------------------------------------------------
# Дефолты
# ---------------------------------------------------------------------------


def test_default_values():
    """Дефолтные значения DrumConfig."""
    cfg = DrumConfig()
    assert cfg.preview_on_select is True
    assert cfg.preview_velocity == 100


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------


def test_preview_velocity_bounds():
    """preview_velocity вне 1–127 → ValidationError."""
    with pytest.raises(ValidationError):
        DrumConfig(preview_velocity=0)
    with pytest.raises(ValidationError):
        DrumConfig(preview_velocity=128)
    # Границы допустимы
    assert DrumConfig(preview_velocity=1).preview_velocity == 1
    assert DrumConfig(preview_velocity=127).preview_velocity == 127


# ---------------------------------------------------------------------------
# Интеграция с AppConfig
# ---------------------------------------------------------------------------


def test_app_config_has_drum():
    """AppConfig содержит секцию drum."""
    cfg = AppConfig()
    assert isinstance(cfg.drum, DrumConfig)
    assert cfg.drum.preview_on_select is True


def test_default_yaml_has_drum_section():
    """DEFAULT_CONFIG_YAML содержит секцию drum."""
    assert "drum:" in DEFAULT_CONFIG_YAML
    assert "preview_on_select" in DEFAULT_CONFIG_YAML


def test_load_config_with_drum(tmp_path):
    """Загрузка config.yaml с секцией drum."""
    yaml_content = """
drum:
  preview_on_select: false
  preview_velocity: 80
"""
    p = tmp_path / "config.yaml"
    p.write_text(yaml_content)
    cfg = load_config(p)
    assert cfg.drum.preview_on_select is False
    assert cfg.drum.preview_velocity == 80
