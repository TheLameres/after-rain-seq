"""Скриптовые proposal-объекты: замысел дорожки как данные.

Живут в core, ниже harmony/session, поэтому проверяют только структуру;
семантику (профиль/voicing/лад) проверяет scripting.validator и фасад.

Слой ``src.core`` ничего не импортирует из harmony/session — это следствие
правила слоёв (решение Q21): конструктор DTO не может знать, существует ли
профиль ``"atmos"`` или voicing ``"1-3-5-7"``, он гарантирует только форму
(непустые строки, диапазоны каналов и ступеней).
"""

from __future__ import annotations

from dataclasses import dataclass


def _check_name(name: str | None, label: str) -> None:
    """Структурная проверка имени дорожки: ``None`` или непустая строка.

    Аргументы:
        name: Имя дорожки (``None`` — автоимя движка).
        label: Имя поля для текста ошибки (``"name"``).

    Raises:
        ValueError: Если имя задано, но не является непустой строкой
            (включая строки из одних пробелов).
    """
    if name is None:
        return
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{label}: если задано — непустая строка, получено {name!r}")


@dataclass(frozen=True, slots=True)
class TrackProposal:
    """Замысел melodic-дорожки для скрипта.

    Атрибуты:
        profile_name: Имя профиля из реестра ``PROFILES`` (существование
            проверяет валидатор/фасад, не DTO).
        name: Имя дорожки; ``None`` — автоимя движка, иначе непустое.
        voicing: Войсинг формата ``"1-3-5"``; ``None`` — дефолт профиля.
        degrees: Ступени прогрессии 0..13 (0-based, две октавы семиступенного
            лада; конвенция движка, ср. ``degree_names.py``); ``None`` —
            оставить профильные. Принимает любую последовательность int
            (список в скрипте), хранит кортеж — DTO frozen, мутабельные
            списки внутрь не пропускаем.
        channel: MIDI-канал 0..15; ``None`` — автоназначение.
    """

    profile_name: str
    name: str | None = None
    voicing: str | None = None
    degrees: tuple[int, ...] | None = None
    channel: int | None = None

    def __post_init__(self) -> None:
        """Структурные проверки полей; ``degrees`` нормализуется в кортеж.

        Raises:
            ValueError: Пустой ``profile_name``; заданное ``name`` — не
                непустая строка; ``channel`` вне 0..15; ``degrees`` не
                последовательность int 0..13 или пуста; ``voicing`` не
                строка и не ``None``.
        """
        if not isinstance(self.profile_name, str) or not self.profile_name.strip():
            raise ValueError(
                f"profile_name: ожидается непустая строка, получено {self.profile_name!r}"
            )
        _check_name(self.name, "name")
        if self.channel is not None and (
            isinstance(self.channel, bool)
            or not isinstance(self.channel, int)
            or not 0 <= self.channel <= 15
        ):
            raise ValueError(
                f"channel: если задан — целое 0..15, получено {self.channel!r}"
            )
        if self.voicing is not None and not isinstance(self.voicing, str):
            raise ValueError(f"voicing: строка или None, получено {self.voicing!r}")
        if self.degrees is not None:
            try:
                degrees = tuple(self.degrees)
            except TypeError as exc:
                raise ValueError(
                    f"degrees: ожидается последовательность int, {exc}"
                ) from None
            if not degrees:
                raise ValueError("degrees: если заданы — непустая последовательность")
            for degree in degrees:
                if (
                    isinstance(degree, bool)
                    or not isinstance(degree, int)
                    or not 0 <= degree <= 13
                ):
                    raise ValueError(
                        f"degrees: ступени — целые 0..13, получено {degree!r}"
                    )
            # frozen + slots: единственный легальный способ нормализовать поле.
            object.__setattr__(self, "degrees", degrees)


@dataclass(frozen=True, slots=True)
class DrumProposal:
    """Замысел drum-дорожки для скрипта.

    Атрибуты:
        name: Имя дорожки; ``None`` — автоимя движка, иначе непустое.
            Канал/шаги drum-машин настраивает движок (конфиг ``drum``),
            proposal их не переопределяет.
    """

    name: str | None = None

    def __post_init__(self) -> None:
        """Структурная проверка имени.

        Raises:
            ValueError: Если имя задано, но не является непустой строкой.
        """
        _check_name(self.name, "name")
