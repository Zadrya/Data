# SPDX-License-Identifier: GPL-3.0-or-later
"""The diff report as Markdown, from the rows of ``zadrya_data.diff.compare``.

The report has a head and a body. The head is what a reviewer reads first and what
a pull request comment always holds: the labels, the paths outside the dataset that
the change also touches, a warning that counts every kind of change that must never
be missed, and the summary. The body holds the sections.

In each section the rows a reviewer must never miss come first, in bold, and are
never left out. The other rows follow, changes before additions. In the sections
of numbers and of texts, which are long on real data, alike rows (same field, same
kind of change) are folded into one collapsed block each. At most ``max_rows`` of
the other rows are shown per section; the report says how many it left out. Every text that comes from the data is escaped by
``escape``. ``render`` is pure: the same diff always gives the same text.
"""

import html
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from zadrya_data.diff import Change, Diff, Risk, Row

DEFAULT_MAX_ROWS = 100

# ASCII punctuation that has no meaning in Markdown and stays as it is.
_INERT = frozenset(",;'\"/?=%")
_ZERO_WIDTH_SPACE = "&#8203;"
# Places where GitHub would turn text into a link: an address, a www name, a GH-
# issue reference. A zero width space goes before the matched position.
_LINK_BREAKS = re.compile(r"(?<=:)(?=//)|(?<=www)(?=\.)|(?<=gh)(?=-)", re.IGNORECASE)
# GitHub links a run of 7 or more hexadecimal digits as a commit.
_HEX_RUN = re.compile(r"[0-9a-fA-F]{7,}")
_HEX_PIECE = 6

_NUMBER_HEADER = ("Substance", "Route", "Field", "Old", "New", "Note")
_INTERACTION_HEADER = ("Substance", "With", "Old", "New")
_GROUP_HEADER = ("Where", "Change", "Substances")


@dataclass(frozen=True, slots=True)
class Report:
    """The report: ``head`` is always shown, ``body`` holds the sections."""

    head: str
    body: str

    @property
    def text(self) -> str:
        """The whole report."""
        return f"{self.head}\n{self.body}"


def _breaks(text: str) -> set[int]:
    """Return the positions before which a zero width space stops an automatic link."""
    points = {match.start() for match in _LINK_BREAKS.finditer(text)}
    for match in _HEX_RUN.finditer(text):
        points.update(range(match.start() + _HEX_PIECE, match.end(), _HEX_PIECE))
    return points


def escape(text: str) -> str:
    """Return text that Markdown shows as written, in a paragraph, a list or a table cell.

    Every ASCII punctuation character with a meaning in Markdown (or GitHub's tables
    and math) is escaped with a backslash. A zero width space follows ``@`` and
    ``#`` and goes inside ``://``, ``www.``, ``GH-`` and long hexadecimal runs, so
    that data never mentions a user or links an issue, a commit or an address. Line
    breaks and other characters that are not printable become spaces, and the em
    dash becomes its character reference, so the report never contains one.
    """
    breaks = _breaks(text)
    out = []
    for position, char in enumerate(text):
        if position in breaks:
            out.append(_ZERO_WIDTH_SPACE)
        if char in "@#":
            out.append(f"\\{char}{_ZERO_WIDTH_SPACE}")
        elif char.isascii() and not char.isalnum() and not char.isspace() and char not in _INERT:
            out.append(f"\\{char}")
        elif char == "\u2014":
            out.append("&#8212;")
        elif char.isspace() or not char.isprintable():
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def _bold_column(header: Sequence[str]) -> int:
    """The column that says what changed: it is bold in a protected row."""
    return next(header.index(name) for name in ("Note", "Change", "New") if name in header)


def _table(header: Sequence[str], rows: Iterable[Row]) -> list[str]:
    bold = _bold_column(header)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        cells = [escape(cell) for cell in row.cells]
        if row.protected:
            cells[bold] = f"**{cells[bold]}**"
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, ""]


def _ordered(rows: list[Row]) -> list[Row]:
    """Protected rows first, then changes, then additions, each in the order of ``compare``."""
    return sorted(rows, key=lambda row: (not row.protected, row.added))


def _capped(rows: list[Row], max_rows: int) -> tuple[list[Row], int]:
    """Keep every protected row and the first ``max_rows`` other rows."""
    kept, others = [], 0
    for row in rows:
        if row.protected or others < max_rows:
            kept.append(row)
            others += not row.protected
    return kept, len(rows) - len(kept)


def _omitted(count: int) -> list[str]:
    return [f"{count} more row(s) not shown.", ""] if count else []


def _fold(
    kept: list[Row], everything: list[Row], unit: str, body: Callable[[list[Row]], list[str]]
) -> list[str]:
    """One collapsed block per group of alike rows, in the order the groups first appear."""
    totals: dict[str, int] = {}
    for row in everything:
        totals[row.group] = totals.get(row.group, 0) + 1
    groups: dict[str, list[Row]] = {}
    for row in kept:
        groups.setdefault(row.group, []).append(row)
    lines = []
    for name, members in groups.items():
        count = (
            f"{len(members)} of {totals[name]}"
            if len(members) < totals[name]
            else str(totals[name])
        )
        title = html.escape(f"{name}: {count} {unit}".rstrip())
        lines += ["<details>", f"<summary>{title}</summary>", "", *body(members), "</details>", ""]
    return lines


def _section(rows: list[Row], max_rows: int, header: Sequence[str], fold: bool) -> list[str]:
    """Protected rows first as a table; the others in a table too, or folded by group."""
    if not rows:
        return ["None.", ""]
    ordered = _ordered(rows)
    kept, omitted = _capped(ordered, max_rows)
    if not fold:
        return _table(header, kept) + _omitted(omitted)
    protected = [row for row in kept if row.protected]
    lines = _table(header, protected) if protected else []
    others = [row for row in ordered if not row.protected]
    shown = [row for row in kept if not row.protected]
    lines += _fold(shown, others, "row(s)", lambda members: _table(header, members))
    return lines + _omitted(omitted)


def _warning(diff: Diff) -> list[str]:
    risks = diff.risks()
    if not risks:
        return []
    lines = ["> **Review these first:**", ">"]
    for risk, count in risks.items():
        line = f"> - {risk.value}: {count}"
        if risk is Risk.RENAMED_SUBSTANCE:
            renames = "; ".join(f"{escape(r.old)} -> {escape(r.new)}" for r in diff.renamed)
            line += f" ({renames})"
        lines.append(line)
    return [*lines, ""]


def _changed_paths(paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    return [
        f"> **This change also touches {len(paths)} file(s) outside dataset/, and the "
        "report was built by its code: review them before trusting the report.**",
        ">",
        *(f"> - {escape(path)}" for path in paths),
        "",
    ]


def _summary(diff: Diff) -> list[str]:
    counts = {change: len(rows) for change, rows in diff.interactions.items()}
    return [
        "## Summary",
        "",
        f"- Substances: {diff.old_count} old, {diff.new_count} new",
        f"- Added: {len(diff.added)}, removed: {len(diff.removed)}, "
        f"renamed: {len(diff.renamed)}",
        f"- Changed numbers and units: {len(diff.numbers)}",
        "- Interactions: " + ", ".join(f"{counts[change]} {change}" for change in Change),
        f"- Group and cross tolerance changes: {len(diff.groups)}",
        f"- Categories and texts changed: {len(diff.flags)} field(s) "
        f"(unchanged substances: {diff.unflagged})",
        *(f"- {escape(version)}" for version in diff.versions),
        "",
    ]


def _substances(diff: Diff, max_rows: int) -> list[str]:
    lines = ["## Substances", "", "### Removed (never truncated)", ""]
    removed = [
        f"- **{escape(name)}**" + (f" ({escape(diff.hints[name])})" if name in diff.hints else "")
        for name in diff.removed
    ]
    lines += [*removed, ""] if removed else ["None.", ""]
    lines += ["### Renamed (never truncated)", ""]
    renamed = [f"- {escape(r.old)} -> {escape(r.new)} ({escape(r.reason)})" for r in diff.renamed]
    lines += [*renamed, ""] if renamed else ["None.", ""]
    lines += ["### Added", ""]
    added = [f"- {escape(name)}" for name in diff.added[:max_rows]]
    lines += [*added, ""] if added else ["None.", ""]
    return lines + _omitted(len(diff.added) - len(added))


def _interactions(diff: Diff, max_rows: int) -> list[str]:
    titles = {
        Change.LOWERED: "### **LOWERED** interactions (never truncated)",
        Change.REMOVED: "### **REMOVED** interactions (never truncated)",
        Change.RAISED: "### Raised interactions",
        Change.ADDED: "### Added interactions",
    }
    lines = ["## Interactions", ""]
    for change in Change:
        rows = diff.interactions[change]
        lines += [titles[change], ""]
        if not rows:
            lines += ["None.", ""]
            continue
        kept, omitted = _capped(rows, max_rows)
        lines += _table(_INTERACTION_HEADER, kept) + _omitted(omitted)
    return lines


def _flags(diff: Diff, max_rows: int) -> list[str]:
    lines = ["## Categories and texts", "", "Only whether a field changed, never its text.", ""]
    if not diff.flags:
        return [*lines, "None.", ""]
    kept, omitted = _capped(diff.flags, max_rows)

    def where(members: list[Row]) -> list[str]:
        return [", ".join(escape(row.cells[0]) for row in members), ""]

    lines += _fold(kept, diff.flags, "", where)
    return lines + _omitted(omitted)


def render(
    diff: Diff,
    *,
    old_label: str,
    new_label: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    changed_paths: Sequence[str] = (),
) -> Report:
    """Return the report. ``changed_paths`` are the files outside dataset/ the change touches."""
    head = [
        "# Dataset diff report",
        "",
        f"Old: {escape(old_label)}",
        "",
        f"New: {escape(new_label)}",
        "",
    ]
    head += _changed_paths(changed_paths) + _warning(diff) + _summary(diff)
    body = _substances(diff, max_rows)
    body += ["## Doses, durations, tolerance and bioavailability", ""]
    body += _section(diff.numbers, max_rows, _NUMBER_HEADER, fold=True)
    body += _interactions(diff, max_rows)
    body += ["## Groups and cross tolerance", ""]
    body += _section(diff.groups, max_rows, _GROUP_HEADER, fold=False)
    body += _flags(diff, max_rows)
    return Report("\n".join(head), "\n".join(body).rstrip("\n") + "\n")
