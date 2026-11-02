"""Device plugin registry.

Единственное место, где перечислены зарегистрированные устройства.
Добавить устройство = добавить две строки в секцию «Регистрация».
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.devices.base import ControllerDevice
    from src.devices.definition import DeviceDefinition

_DEFINITIONS: dict[str, DeviceDefinition] = {}


def register(defn: DeviceDefinition) -> None:
    _DEFINITIONS[defn.type_key] = defn


def get_definition(type_key: str) -> DeviceDefinition:
    try:
        return _DEFINITIONS[type_key]
    except KeyError:
        raise ValueError(f"Unknown device type: {type_key!r}") from None


def get_all_definitions() -> list[DeviceDefinition]:
    return list(_DEFINITIONS.values())


def create_device(device_type: str) -> ControllerDevice:
    """Создать экземпляр устройства через фабрику DeviceDefinition."""
    return get_definition(device_type).device_factory()


# ---------------------------------------------------------------------------
# Регистрация
# Добавить новое устройство: from src.devices.<name>.definition import X; register(X)
# ---------------------------------------------------------------------------
from src.devices.lcxl3.definition import LCXL3_DEFINITION
from src.devices.push2.definition import PUSH2_DEFINITION

register(PUSH2_DEFINITION)
register(LCXL3_DEFINITION)
