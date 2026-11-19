"""Таблицы и константы мутации — данные для выбора механизма дрейфа."""

#: Механизм мутации по профилю (C6): какой дрейф ведёт дорожку.
MECH_NOTE: str = "note"  # NoteDrift — дрейф ступеней
MECH_EUCLIDEAN: str = "euclidean"  # FloatingEuclidean — дрейф pulses
MECH_PARAM: str = "param"  # ParamDrift — дрейф гейта/плотности/регистра

PROFILE_MECHANISM: dict[str, str] = {
    "lead": MECH_NOTE,
    "texture": MECH_NOTE,
    "seq": MECH_EUCLIDEAN,
    "arp": MECH_EUCLIDEAN,
    "stab": MECH_EUCLIDEAN,  # C6: нарезка евклидом
    "pad": MECH_PARAM,
    "atmos": MECH_PARAM,
    "bass": MECH_PARAM,
    "sub": MECH_PARAM,  # C6: регистр/гейт
}

#: Параметры ParamDrift по профилю (порядок — для детерминированных тестов).
PARAM_DRIFT_PARAMS: dict[str, tuple[tuple[str, float, float, float, float], ...]] = {
    "pad": (
        ("gate", 0.9, 0.1, 1.0, 0.05),
        ("density", 0.5, 0.0, 1.0, 0.1),
        ("register", 0.0, -2.0, 2.0, 1.0),
    ),
    "atmos": (
        ("gate", 1.0, 0.1, 1.0, 0.05),
        ("register", 0.0, -2.0, 2.0, 1.0),
    ),
    "bass": (
        ("gate", 0.8, 0.1, 1.0, 0.05),
        ("register", 0.0, -2.0, 2.0, 1.0),
    ),
    "sub": (
        ("register", 0.0, -2.0, 2.0, 1.0),
        ("gate", 1.0, 0.1, 1.0, 0.05),
    ),
}
