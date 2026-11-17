# SPDX-License-Identifier: GPL-3.0-or-later
"""The text fields of one substance.

- ``summary``: the base summary and nothing else. The ``summary`` of the API is the
  first text of the wiki page, which is as often a banner, a stub notice or a warning
  box as a summary, so it is never used. A substance without a base summary has none
  and is reported.
- ``effectsSummary``, ``dosageRemark``, ``generalRisks``, ``longtermRisks``: from the
  base file (the API does not have them); line feeds inside are kept.
- ``saferUse``: the base items; absent when no item is left.
- ``addictionPotential`` and ``toxicities``: the API value when it is present and not
  empty, else the base value.

All text is stripped at both ends. Text that still breaks the schema's text rules is
reported and dropped, never repaired.
"""

from typing import Any

from zadrya_data.base import BaseSubstance
from zadrya_data.graphql import ApiSubstance
from zadrya_data.normalize import text
from zadrya_data.normalize.report import Kind, Report

PLACEHOLDER_SUMMARY = "Summary sheet:"


def _why_no_summary(base: BaseSubstance | None, api: ApiSubstance | None) -> str:
    source = "no base summary" if base is not None else "not in the base file"
    if api is None or api.summary is None or not text.strip(api.summary):
        return f"{source}, and the API has none either"
    if PLACEHOLDER_SUMMARY in api.summary:
        return f"{source}; the API summary is a placeholder and is not used"
    return f"{source}; the API summary is the first text of the wiki page and is not used"


def _line(name: str, field: str, raw: str | None, report: Report) -> str | None:
    if raw is None or not text.strip(raw):
        return None
    cleaned = text.line(raw)
    if cleaned is None:
        report.add(
            Kind.TEXT_DROPPED, f"{field} {text.describe(raw)} is not valid text", substance=name
        )
    return cleaned


def _lines(name: str, field: str, raws: tuple[str, ...] | None, report: Report) -> list[str]:
    cleaned = [_line(name, field, raw, report) for raw in raws or ()]
    return [item for item in cleaned if item is not None]


def substance_fields(
    name: str, base: BaseSubstance | None, api: ApiSubstance | None, report: Report
) -> dict[str, Any]:
    """Return the optional text fields of one substance that have a value, and ``toxicities``."""
    fields: dict[str, Any] = {}

    summary = _line(name, "summary", base.summary if base else None, report)
    if summary is not None:
        fields["summary"] = summary
    else:
        report.add(Kind.NO_SUMMARY, _why_no_summary(base, api), substance=name)

    if base is not None:
        for field, raw in (
            ("effectsSummary", base.effects_summary),
            ("dosageRemark", base.dosage_remark),
            ("generalRisks", base.general_risks),
            ("longtermRisks", base.longterm_risks),
        ):
            if raw is None or not text.strip(raw):
                continue
            cleaned = text.paragraphs(raw)
            if cleaned is None:
                report.add(
                    Kind.TEXT_DROPPED,
                    f"{field} {text.describe(raw)} is not valid text",
                    substance=name,
                )
            else:
                fields[field] = cleaned
        safer_use = _lines(name, "saferUse item", base.safer_use, report)
        if safer_use:
            fields["saferUse"] = safer_use

    addiction = _line(name, "addictionPotential", api.addiction_potential if api else None, report)
    if addiction is None:
        addiction = _line(
            name, "addictionPotential", base.addiction_potential if base else None, report
        )
    if addiction is not None:
        fields["addictionPotential"] = addiction

    toxicities = _lines(name, "toxicity", api.toxicity if api else None, report)
    if not toxicities:
        toxicities = _lines(name, "toxicity", base.toxicities if base else None, report)
    fields["toxicities"] = toxicities
    return fields
