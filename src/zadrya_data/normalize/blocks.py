# SPDX-License-Identifier: GPL-3.0-or-later
"""The merge policy for one block of a route: dose, one duration phase, bioavailability.

Each source offers a candidate for the block. The policy is:

1. the API candidate, when it is present and consistent;
2. otherwise the base candidate, when it is present and consistent;
3. otherwise no block.

A block is never assembled from both sources. Whatever is not plain case 1 is
reported: an API block that was rejected, a base block used because the API has none,
a block dropped because neither source has a consistent one, and a base block that is
lost because it is inconsistent while the API only states units. A candidate can be
"weak" (a dose that only states units): a weak candidate is used only when the other
source has nothing better.
"""

from dataclasses import dataclass

from zadrya_data.normalize.report import Kind, Report

type Note = tuple[Kind, str]


@dataclass(frozen=True, slots=True)
class Candidate[T]:
    """What one source offers for a block.

    ``value`` is the normalized block, or ``None`` when the source has none or it is
    inconsistent, in which case ``problem`` says why. ``notes`` are findings that apply
    only if this candidate is the one used.
    """

    value: T | None = None
    problem: str | None = None
    notes: tuple[Note, ...] = ()
    weak: bool = False


def choose[T](
    api: Candidate[T],
    base: Candidate[T],
    *,
    what: str,
    substance: str,
    route: str,
    in_both_sources: bool,
    report: Report,
) -> T | None:
    """Apply the merge policy to one block and record what was done."""
    ranked = [
        (api, "API", not api.weak),
        (base, "base", not base.weak),
        (api, "API", True),
        (base, "base", True),
    ]
    for candidate, source, eligible in ranked:
        if candidate.value is None or not eligible:
            continue
        if source == "base":
            if api.problem is not None:
                report.add(
                    Kind.API_BLOCK_REJECTED,
                    f"{what}: {api.problem}; the base block is used",
                    substance=substance,
                    route=route,
                )
            elif in_both_sources:
                detail = (
                    "the API states units only" if api.value is not None else "the API has none"
                )
                report.add(
                    Kind.BASE_BLOCK_USED,
                    f"{what}: {detail}; the base block is used",
                    substance=substance,
                    route=route,
                )
        if source == "API" and candidate.weak and base.problem is not None:
            report.add(
                Kind.BLOCK_DROPPED,
                f"{what}: the base block is not used ({base.problem}); the API states units "
                "only, and they are kept",
                substance=substance,
                route=route,
            )
        for kind, detail in candidate.notes:
            report.add(kind, f"{what}: {detail}", substance=substance, route=route)
        return candidate.value

    problems = [
        f"{source}: {candidate.problem}"
        for candidate, source in ((api, "API"), (base, "base"))
        if candidate.problem is not None
    ]
    if problems:
        report.add(
            Kind.BLOCK_DROPPED,
            f"{what}: no consistent block ({'; '.join(problems)})",
            substance=substance,
            route=route,
        )
    return None
