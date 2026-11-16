# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed loader of the base file: ``Substances.json`` of PsychonautWiki Journal v11.11.

The loader mirrors the file exactly. It changes no value (names, units, numbers and
their int or float type stay as written) and keeps the difference between a key
that is absent (``None``) and a list that is empty. Anything it does not know
(an unknown or repeated key, a missing required key, a value of another type, a
number that is not finite) raises
``BaseFormatError`` with the path of the offending value, so a different base file
can never be read by accident. Normalization happens elsewhere.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class BaseFormatError(ValueError):
    """The base file does not have the shape this loader knows."""


@dataclass(frozen=True, slots=True)
class BaseCategory:
    """A category. ``color`` is an ARGB integer of the original app."""

    name: str
    description: str
    color: int
    url: str | None


@dataclass(frozen=True, slots=True)
class BaseTolerance:
    """Tolerance timeline in free text."""

    full: str | None
    half: str | None
    zero: str | None


@dataclass(frozen=True, slots=True)
class BaseDose:
    """Lower bound of each dose class, in ``units``."""

    units: str
    light_min: float | None
    common_min: float | None
    strong_min: float | None
    heavy_min: float | None


@dataclass(frozen=True, slots=True)
class BaseDurationRange:
    """Length of one phase, in ``units`` (seconds, minutes, hours or days)."""

    min: float | None
    max: float | None
    units: str


@dataclass(frozen=True, slots=True)
class BaseDuration:
    """Length of each phase of one route."""

    onset: BaseDurationRange | None
    comeup: BaseDurationRange | None
    peak: BaseDurationRange | None
    offset: BaseDurationRange | None
    total: BaseDurationRange | None
    afterglow: BaseDurationRange | None


@dataclass(frozen=True, slots=True)
class BaseBioavailability:
    """Bioavailability in percent."""

    min: float | None
    max: float | None


@dataclass(frozen=True, slots=True)
class BaseRoute:
    """One route of administration."""

    name: str
    dose: BaseDose | None
    duration: BaseDuration | None
    bioavailability: BaseBioavailability | None


@dataclass(frozen=True, slots=True)
class BaseInteractions:
    """Interaction targets by severity, as plain names (substances, classes or other things)."""

    dangerous: tuple[str, ...]
    unsafe: tuple[str, ...]
    uncertain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaseSubstance:
    """One substance, with attributes named after the keys of the file in snake case."""

    name: str
    common_names: tuple[str, ...]
    url: str
    is_approved: bool
    tolerance: BaseTolerance | None
    cross_tolerances: tuple[str, ...]
    addiction_potential: str | None
    toxicities: tuple[str, ...]
    categories: tuple[str, ...]
    summary: str | None
    effects_summary: str | None
    dosage_remark: str | None
    general_risks: str | None
    longterm_risks: str | None
    safer_use: tuple[str, ...] | None
    interactions: BaseInteractions | None
    roas: tuple[BaseRoute, ...]


@dataclass(frozen=True, slots=True)
class BaseFile:
    """The whole base file."""

    categories: tuple[BaseCategory, ...]
    substances: tuple[BaseSubstance, ...]


class _Object:
    """A JSON object being read: typed access by key, and a final check for unread keys."""

    def __init__(self, value: object, path: str) -> None:
        if not isinstance(value, dict):
            raise BaseFormatError(f"{path}: expected an object, found {_kind(value)}")
        self._value: dict[str, object] = value
        self._path = path
        self._read: set[str] = set()

    def _get(self, key: str, required: bool) -> object | None:
        self._read.add(key)
        if key not in self._value:
            if required:
                raise BaseFormatError(f"{self._path}: missing key '{key}'")
            return None
        value = self._value[key]
        if value is None:
            raise BaseFormatError(f"{self._path}.{key}: expected a value, found null")
        return value

    def text(self, key: str) -> str:
        value = self._get(key, required=True)
        if not isinstance(value, str):
            raise BaseFormatError(f"{self._path}.{key}: expected a string, found {_kind(value)}")
        return value

    def optional_text(self, key: str) -> str | None:
        return None if key not in self._value else self.text(key)

    def boolean(self, key: str) -> bool:
        value = self._get(key, required=True)
        if not isinstance(value, bool):
            raise BaseFormatError(f"{self._path}.{key}: expected a boolean, found {_kind(value)}")
        return value

    def integer(self, key: str) -> int:
        value = self._get(key, required=True)
        if isinstance(value, bool) or not isinstance(value, int):
            raise BaseFormatError(f"{self._path}.{key}: expected an integer, found {_kind(value)}")
        return value

    def optional_number(self, key: str) -> float | None:
        value = self._get(key, required=False)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BaseFormatError(f"{self._path}.{key}: expected a number, found {_kind(value)}")
        if not math.isfinite(value):
            raise BaseFormatError(f"{self._path}.{key}: expected a finite number, found {value}")
        return value

    def texts(self, key: str) -> tuple[str, ...]:
        texts: list[str] = []
        for index, item in enumerate(self._list(key)):
            if not isinstance(item, str):
                raise BaseFormatError(
                    f"{self._path}.{key}[{index}]: expected a string, found {_kind(item)}"
                )
            texts.append(item)
        return tuple(texts)

    def optional_texts(self, key: str) -> tuple[str, ...] | None:
        return None if key not in self._value else self.texts(key)

    def objects[T](self, key: str, parse: Callable[[object, str], T]) -> tuple[T, ...]:
        return tuple(
            parse(item, f"{self._path}.{key}[{index}]")
            for index, item in enumerate(self._list(key))
        )

    def optional_object[T](self, key: str, parse: Callable[[object, str], T]) -> T | None:
        value = self._get(key, required=False)
        return None if value is None else parse(value, f"{self._path}.{key}")

    def finish(self) -> None:
        """Fail if the object has a key that nothing read."""
        unknown = sorted(set(self._value) - self._read)
        if unknown:
            names = ", ".join(f"'{key}'" for key in unknown)
            raise BaseFormatError(f"{self._path}: unknown key(s) {names}")

    def _list(self, key: str) -> list[object]:
        value = self._get(key, required=True)
        if not isinstance(value, list):
            raise BaseFormatError(f"{self._path}.{key}: expected a list, found {_kind(value)}")
        return value


def _kind(value: object) -> str:
    names = {dict: "an object", list: "a list", str: "a string", bool: "a boolean"}
    if value is None:
        return "null"
    return names.get(type(value), "a number")


def _category(value: object, path: str) -> BaseCategory:
    source = _Object(value, path)
    category = BaseCategory(
        name=source.text("name"),
        description=source.text("description"),
        color=source.integer("color"),
        url=source.optional_text("url"),
    )
    source.finish()
    return category


def _tolerance(value: object, path: str) -> BaseTolerance:
    source = _Object(value, path)
    tolerance = BaseTolerance(
        full=source.optional_text("full"),
        half=source.optional_text("half"),
        zero=source.optional_text("zero"),
    )
    source.finish()
    return tolerance


def _dose(value: object, path: str) -> BaseDose:
    source = _Object(value, path)
    dose = BaseDose(
        units=source.text("units"),
        light_min=source.optional_number("lightMin"),
        common_min=source.optional_number("commonMin"),
        strong_min=source.optional_number("strongMin"),
        heavy_min=source.optional_number("heavyMin"),
    )
    source.finish()
    return dose


def _duration_range(value: object, path: str) -> BaseDurationRange:
    source = _Object(value, path)
    duration_range = BaseDurationRange(
        min=source.optional_number("min"),
        max=source.optional_number("max"),
        units=source.text("units"),
    )
    source.finish()
    return duration_range


def _duration(value: object, path: str) -> BaseDuration:
    source = _Object(value, path)
    duration = BaseDuration(
        onset=source.optional_object("onset", _duration_range),
        comeup=source.optional_object("comeup", _duration_range),
        peak=source.optional_object("peak", _duration_range),
        offset=source.optional_object("offset", _duration_range),
        total=source.optional_object("total", _duration_range),
        afterglow=source.optional_object("afterglow", _duration_range),
    )
    source.finish()
    return duration


def _bioavailability(value: object, path: str) -> BaseBioavailability:
    source = _Object(value, path)
    bioavailability = BaseBioavailability(
        min=source.optional_number("min"),
        max=source.optional_number("max"),
    )
    source.finish()
    return bioavailability


def _route(value: object, path: str) -> BaseRoute:
    source = _Object(value, path)
    route = BaseRoute(
        name=source.text("name"),
        dose=source.optional_object("dose", _dose),
        duration=source.optional_object("duration", _duration),
        bioavailability=source.optional_object("bioavailability", _bioavailability),
    )
    source.finish()
    return route


def _interactions(value: object, path: str) -> BaseInteractions:
    source = _Object(value, path)
    interactions = BaseInteractions(
        dangerous=source.texts("dangerous"),
        unsafe=source.texts("unsafe"),
        uncertain=source.texts("uncertain"),
    )
    source.finish()
    return interactions


def _substance(value: object, path: str) -> BaseSubstance:
    source = _Object(value, path)
    substance = BaseSubstance(
        name=source.text("name"),
        common_names=source.texts("commonNames"),
        url=source.text("url"),
        is_approved=source.boolean("isApproved"),
        tolerance=source.optional_object("tolerance", _tolerance),
        cross_tolerances=source.texts("crossTolerances"),
        addiction_potential=source.optional_text("addictionPotential"),
        toxicities=source.texts("toxicities"),
        categories=source.texts("categories"),
        summary=source.optional_text("summary"),
        effects_summary=source.optional_text("effectsSummary"),
        dosage_remark=source.optional_text("dosageRemark"),
        general_risks=source.optional_text("generalRisks"),
        longterm_risks=source.optional_text("longtermRisks"),
        safer_use=source.optional_texts("saferUse"),
        interactions=source.optional_object("interactions", _interactions),
        roas=source.objects("roas", _route),
    )
    source.finish()
    return substance


def parse_base(document: object) -> BaseFile:
    """Turn the parsed JSON of a base file into its typed form, or raise ``BaseFormatError``."""
    source = _Object(document, "$")
    base = BaseFile(
        categories=source.objects("categories", _category),
        substances=source.objects("substances", _substance),
    )
    source.finish()
    return base


def _reject_constant(constant: str) -> object:
    raise ValueError(f"{constant} is not a JSON number")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"duplicate key '{key}'")
        document[key] = value
    return document


def load_base(path: Path) -> BaseFile:
    """Read a base file from disk, or raise ``BaseFormatError``.

    Stricter than plain ``json.loads``: ``NaN`` and ``Infinity`` are rejected, and so
    is an object with the same key twice, where the last value would win silently.
    """
    try:
        document: object = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ValueError as error:
        raise BaseFormatError(f"{path}: not valid JSON: {error}") from error
    return parse_base(document)
