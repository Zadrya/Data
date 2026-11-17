# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes of administration of one substance: the union of both sources, block by block.

The routes are the union of the routes of the base file and of the API, by name, in
the order of the schema's route list. A route name outside that list stops the
normalization: a new route is a schema change, not something to drop. For each route,
the dose, each duration phase and the bioavailability are chosen separately by the
merge policy in ``blocks``.
"""

from functools import cache
from typing import Any

from zadrya_data.base import BaseRoute, BaseSubstance
from zadrya_data.graphql import ApiRoute, ApiSubstance
from zadrya_data.normalize import dose as dose_rules
from zadrya_data.normalize.bioavailability import bioavailability
from zadrya_data.normalize.blocks import Candidate, choose
from zadrya_data.normalize.duration import PHASES, phase
from zadrya_data.normalize.errors import NormalizationError
from zadrya_data.normalize.report import Kind, Report
from zadrya_data.schema import SchemaName, load_schema


@cache
def route_order() -> tuple[str, ...]:
    """Return the route names of the schema, in the order the dataset lists them."""
    names: list[str] = load_schema(SchemaName.SUBSTANCES)["$defs"]["roa"]["properties"]["route"][
        "enum"
    ]
    return tuple(names)


def _by_name[T: (BaseRoute, ApiRoute)](
    routes: tuple[T, ...], source: str, substance: str
) -> dict[str, T]:
    found: dict[str, T] = {}
    for route in routes:
        if route.name not in route_order():
            raise NormalizationError(
                f"'{substance}' has the route '{route.name}' in the {source}, which is "
                "not in the schema"
            )
        if route.name in found:
            raise NormalizationError(
                f"'{substance}' has the route '{route.name}' twice in the {source}"
            )
        found[route.name] = route
    return found


def normalize_routes(
    name: str, base: BaseSubstance | None, api: ApiSubstance | None, report: Report
) -> list[dict[str, Any]]:
    """Return the routes of one substance in schema order."""
    base_routes = _by_name(base.roas if base else (), "base file", name)
    api_routes = _by_name((api.roas or ()) if api else (), "API", name)
    in_both_sources = base is not None and api is not None

    routes: list[dict[str, Any]] = []
    for route in route_order():
        base_route, api_route = base_routes.get(route), api_routes.get(route)
        if base_route is None and api_route is None:
            continue
        if in_both_sources and api_route is None:
            report.add(
                Kind.ROUTE_ONLY_IN_BASE,
                "the API does not list this route",
                substance=name,
                route=route,
            )
        if in_both_sources and base_route is None:
            report.add(
                Kind.ROUTE_ONLY_IN_API,
                "the base file does not list this route",
                substance=name,
                route=route,
            )
        both = base_route is not None and api_route is not None
        result: dict[str, Any] = {"route": route}

        base_dose = base_route.dose if base_route else None
        dose = choose(
            dose_rules.from_api(api_route.dose if api_route else None, base_dose),
            dose_rules.from_base(base_dose),
            what="dose",
            substance=name,
            route=route,
            in_both_sources=both,
            report=report,
        )
        if dose is not None:
            result["dose"] = dose

        api_duration = api_route.duration if api_route else None
        base_duration = base_route.duration if base_route else None
        duration: dict[str, Any] = {}
        for phase_name in PHASES:
            api_phase = getattr(api_duration, phase_name) if api_duration else None
            base_phase = getattr(base_duration, phase_name) if base_duration else None
            chosen = choose(
                phase(api_phase.min, api_phase.max, api_phase.units) if api_phase else Candidate(),
                (
                    phase(base_phase.min, base_phase.max, base_phase.units)
                    if base_phase
                    else Candidate()
                ),
                what=f"duration {phase_name}",
                substance=name,
                route=route,
                in_both_sources=both,
                report=report,
            )
            if chosen is not None:
                duration[phase_name] = chosen
        if duration:
            result["duration"] = duration
        if api_duration is not None and api_duration.duration is not None:
            extra = api_duration.duration
            bounds = " to ".join(
                "?" if bound is None else f"{bound:g}" for bound in (extra.min, extra.max)
            )
            report.add(
                Kind.API_PHASE_IGNORED,
                f"the API phase 'duration' ({bounds}, {extra.units or 'no unit'}) is not in "
                "the schema",
                substance=name,
                route=route,
            )

        api_bio = api_route.bioavailability if api_route else None
        base_bio = base_route.bioavailability if base_route else None
        chosen_bio = choose(
            bioavailability(api_bio.min, api_bio.max) if api_bio else Candidate(),
            bioavailability(base_bio.min, base_bio.max) if base_bio else Candidate(),
            what="bioavailability",
            substance=name,
            route=route,
            in_both_sources=both,
            report=report,
        )
        if chosen_bio is not None:
            result["bioavailability"] = chosen_bio
        routes.append(result)
    return routes
