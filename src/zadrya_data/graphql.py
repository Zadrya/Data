# SPDX-License-Identifier: GPL-3.0-or-later
"""Client and typed reader of the PsychonautWiki GraphQL API.

One query asks for every substance with the fields the dataset needs. The answer is
kept exactly as received: null stays ``None``, units stay as written (``Hours``, the
Greek letter mu), and class or disambiguation pages without routes stay in the list.
Cleaning is the job of normalization. What this module does check is the shape: an
unknown key, a missing key, a value of another type or a GraphQL ``errors`` member
raises, so a change of the API can never be read by accident.
"""

from collections.abc import Callable
from dataclasses import dataclass

from zadrya_data.http import PoliteClient

ENDPOINT = "https://api.psychonautwiki.org/"

# The limit written in the query. An answer this long may have been cut off.
LIMIT = 2000

QUERY = """\
{
  substances(limit: 2000) {
    name
    url
    featured
    summary
    systematicName
    commonNames
    addictionPotential
    toxicity
    crossTolerances
    class { chemical psychoactive }
    tolerance { full half zero }
    roas {
      name
      dose {
        units
        threshold
        heavy
        light { min max }
        common { min max }
        strong { min max }
      }
      duration {
        onset { min max units }
        comeup { min max units }
        peak { min max units }
        offset { min max units }
        total { min max units }
        afterglow { min max units }
        duration { min max units }
      }
      bioavailability { min max }
    }
    uncertainInteractions { name }
    unsafeInteractions { name }
    dangerousInteractions { name }
  }
}
"""


class ApiFormatError(ValueError):
    """The answer of the API does not have the shape this reader knows."""


class ApiQueryError(RuntimeError):
    """The API answered the query with errors."""


@dataclass(frozen=True, slots=True)
class ApiRange:
    """A range without units: a dose class or a bioavailability."""

    min: float | None
    max: float | None


@dataclass(frozen=True, slots=True)
class ApiDurationRange:
    """Length of one phase, in ``units`` as the API writes them."""

    min: float | None
    max: float | None
    units: str | None


@dataclass(frozen=True, slots=True)
class ApiDose:
    """Dose classes of one route."""

    units: str | None
    threshold: float | None
    heavy: float | None
    light: ApiRange | None
    common: ApiRange | None
    strong: ApiRange | None


@dataclass(frozen=True, slots=True)
class ApiDuration:
    """Length of each phase of one route. ``duration`` is a phase the API also has."""

    onset: ApiDurationRange | None
    comeup: ApiDurationRange | None
    peak: ApiDurationRange | None
    offset: ApiDurationRange | None
    total: ApiDurationRange | None
    afterglow: ApiDurationRange | None
    duration: ApiDurationRange | None


@dataclass(frozen=True, slots=True)
class ApiRoute:
    """One route of administration."""

    name: str
    dose: ApiDose | None
    duration: ApiDuration | None
    bioavailability: ApiRange | None


@dataclass(frozen=True, slots=True)
class ApiClasses:
    """Chemical and psychoactive classes."""

    chemical: tuple[str, ...] | None
    psychoactive: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ApiTolerance:
    """Tolerance timeline in free text."""

    full: str | None
    half: str | None
    zero: str | None


@dataclass(frozen=True, slots=True)
class ApiSubstance:
    """One entry of the API: a substance, or a class or disambiguation page (no routes).

    Attributes are named after the keys of the API in snake case. The three interaction
    lists hold the ``name`` of each target.
    """

    name: str
    url: str | None
    featured: bool | None
    summary: str | None
    systematic_name: str | None
    common_names: tuple[str, ...] | None
    addiction_potential: str | None
    toxicity: tuple[str, ...] | None
    cross_tolerances: tuple[str, ...] | None
    classes: ApiClasses | None
    tolerance: ApiTolerance | None
    roas: tuple[ApiRoute, ...] | None
    uncertain_interactions: tuple[str, ...] | None
    unsafe_interactions: tuple[str, ...] | None
    dangerous_interactions: tuple[str, ...] | None


class _Object:
    """A JSON object being read: every key must be present, null is allowed where asked."""

    def __init__(self, value: object, path: str) -> None:
        if not isinstance(value, dict):
            raise ApiFormatError(f"{path}: expected an object, found {_kind(value)}")
        self._value: dict[str, object] = value
        self._path = path
        self._read: set[str] = set()

    def _get(self, key: str) -> object:
        self._read.add(key)
        if key not in self._value:
            raise ApiFormatError(f"{self._path}: missing key '{key}'")
        return self._value[key]

    def _fail(self, key: str, wanted: str, value: object) -> ApiFormatError:
        return ApiFormatError(f"{self._path}.{key}: expected {wanted}, found {_kind(value)}")

    def text(self, key: str) -> str:
        value = self._get(key)
        if not isinstance(value, str):
            raise self._fail(key, "a string", value)
        return value

    def optional_text(self, key: str) -> str | None:
        return None if self._get(key) is None else self.text(key)

    def optional_boolean(self, key: str) -> bool | None:
        value = self._get(key)
        if value is not None and not isinstance(value, bool):
            raise self._fail(key, "a boolean or null", value)
        return value

    def optional_number(self, key: str) -> float | None:
        value = self._get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self._fail(key, "a number or null", value)
        return value

    def optional_texts(self, key: str) -> tuple[str, ...] | None:
        items = self._optional_list(key)
        if items is None:
            return None
        texts: list[str] = []
        for index, item in enumerate(items):
            if not isinstance(item, str):
                raise self._fail(f"{key}[{index}]", "a string", item)
            texts.append(item)
        return tuple(texts)

    def optional_objects[T](
        self, key: str, parse: Callable[[object, str], T]
    ) -> tuple[T, ...] | None:
        items = self._optional_list(key)
        if items is None:
            return None
        return tuple(
            parse(item, f"{self._path}.{key}[{index}]") for index, item in enumerate(items)
        )

    def optional_object[T](self, key: str, parse: Callable[[object, str], T]) -> T | None:
        value = self._get(key)
        return None if value is None else parse(value, f"{self._path}.{key}")

    def finish(self) -> None:
        """Fail if the object has a key that nothing read."""
        unknown = sorted(set(self._value) - self._read)
        if unknown:
            names = ", ".join(f"'{key}'" for key in unknown)
            raise ApiFormatError(f"{self._path}: unknown key(s) {names}")

    def _optional_list(self, key: str) -> list[object] | None:
        value = self._get(key)
        if value is not None and not isinstance(value, list):
            raise self._fail(key, "a list or null", value)
        return value


def _kind(value: object) -> str:
    names = {dict: "an object", list: "a list", str: "a string", bool: "a boolean"}
    if value is None:
        return "null"
    return names.get(type(value), "a number")


def _range(value: object, path: str) -> ApiRange:
    source = _Object(value, path)
    result = ApiRange(min=source.optional_number("min"), max=source.optional_number("max"))
    source.finish()
    return result


def _duration_range(value: object, path: str) -> ApiDurationRange:
    source = _Object(value, path)
    result = ApiDurationRange(
        min=source.optional_number("min"),
        max=source.optional_number("max"),
        units=source.optional_text("units"),
    )
    source.finish()
    return result


def _dose(value: object, path: str) -> ApiDose:
    source = _Object(value, path)
    result = ApiDose(
        units=source.optional_text("units"),
        threshold=source.optional_number("threshold"),
        heavy=source.optional_number("heavy"),
        light=source.optional_object("light", _range),
        common=source.optional_object("common", _range),
        strong=source.optional_object("strong", _range),
    )
    source.finish()
    return result


def _duration(value: object, path: str) -> ApiDuration:
    source = _Object(value, path)
    result = ApiDuration(
        onset=source.optional_object("onset", _duration_range),
        comeup=source.optional_object("comeup", _duration_range),
        peak=source.optional_object("peak", _duration_range),
        offset=source.optional_object("offset", _duration_range),
        total=source.optional_object("total", _duration_range),
        afterglow=source.optional_object("afterglow", _duration_range),
        duration=source.optional_object("duration", _duration_range),
    )
    source.finish()
    return result


def _route(value: object, path: str) -> ApiRoute:
    source = _Object(value, path)
    result = ApiRoute(
        name=source.text("name"),
        dose=source.optional_object("dose", _dose),
        duration=source.optional_object("duration", _duration),
        bioavailability=source.optional_object("bioavailability", _range),
    )
    source.finish()
    return result


def _classes(value: object, path: str) -> ApiClasses:
    source = _Object(value, path)
    result = ApiClasses(
        chemical=source.optional_texts("chemical"),
        psychoactive=source.optional_texts("psychoactive"),
    )
    source.finish()
    return result


def _tolerance(value: object, path: str) -> ApiTolerance:
    source = _Object(value, path)
    result = ApiTolerance(
        full=source.optional_text("full"),
        half=source.optional_text("half"),
        zero=source.optional_text("zero"),
    )
    source.finish()
    return result


def _target(value: object, path: str) -> str:
    source = _Object(value, path)
    name = source.text("name")
    source.finish()
    return name


def _substance(value: object, path: str) -> ApiSubstance:
    source = _Object(value, path)
    result = ApiSubstance(
        name=source.text("name"),
        url=source.optional_text("url"),
        featured=source.optional_boolean("featured"),
        summary=source.optional_text("summary"),
        systematic_name=source.optional_text("systematicName"),
        common_names=source.optional_texts("commonNames"),
        addiction_potential=source.optional_text("addictionPotential"),
        toxicity=source.optional_texts("toxicity"),
        cross_tolerances=source.optional_texts("crossTolerances"),
        classes=source.optional_object("class", _classes),
        tolerance=source.optional_object("tolerance", _tolerance),
        roas=source.optional_objects("roas", _route),
        uncertain_interactions=source.optional_objects("uncertainInteractions", _target),
        unsafe_interactions=source.optional_objects("unsafeInteractions", _target),
        dangerous_interactions=source.optional_objects("dangerousInteractions", _target),
    )
    source.finish()
    return result


def parse_data(data: object) -> tuple[ApiSubstance, ...]:
    """Turn the ``data`` member of the answer into typed substances, or raise ``ApiFormatError``."""
    source = _Object(data, "$")
    substances = source.optional_objects("substances", _substance)
    source.finish()
    if substances is None:
        raise ApiFormatError("$.substances: expected a list, found null")
    if not substances:
        raise ApiFormatError("$.substances: the list is empty")
    if len(substances) >= LIMIT:
        raise ApiFormatError(
            f"$.substances: {len(substances)} entries reach the limit of the query ({LIMIT}), "
            "so the answer may be cut off"
        )
    seen: set[str] = set()
    for index, substance in enumerate(substances):
        if not substance.name.strip():
            raise ApiFormatError(f"$.substances[{index}].name: the name is empty")
        if substance.name in seen:
            raise ApiFormatError(
                f"$.substances[{index}].name: second entry named '{substance.name}'"
            )
        seen.add(substance.name)
    return substances


def fetch_data(client: PoliteClient) -> dict[str, object]:
    """Ask the API for every substance and return the checked ``data`` member, unchanged."""
    answer = client.post_json(ENDPOINT, {"query": QUERY})
    if not isinstance(answer, dict):
        raise ApiFormatError(f"$: expected an object, found {_kind(answer)}")
    if "errors" in answer:
        raise ApiQueryError(f"the API answered with errors: {_messages(answer['errors'])}")
    unknown = sorted(set(answer) - {"data"})
    if unknown:
        raise ApiFormatError(f"$: unknown key(s) {', '.join(repr(key) for key in unknown)}")
    data = answer.get("data")
    if not isinstance(data, dict):
        raise ApiFormatError(f"$.data: expected an object, found {_kind(data)}")
    parse_data(data)
    return data


def _messages(errors: object) -> str:
    if isinstance(errors, list):
        found = [error.get("message") for error in errors if isinstance(error, dict)]
        texts = [message for message in found if isinstance(message, str)]
        if texts:
            return "; ".join(texts)
    return repr(errors)
