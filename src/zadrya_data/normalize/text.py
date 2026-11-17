# SPDX-License-Identifier: GPL-3.0-or-later
"""Text cleaning: strip the ends, then accept or reject. Nothing else is repaired.

The two rules a text must meet are the ``text`` and ``paragraphs`` patterns of the
substances schema, read from the schema itself so that this module and the validator
can never disagree. Text that still breaks its rule after stripping is not repaired:
the caller reports it and drops it.
"""

import re
from functools import cache

from zadrya_data.schema import SchemaName, load_schema

# What stripping removes at both ends: whitespace as Python sees it, and the byte
# order mark, which the schema treats as whitespace too.
_EDGE = re.compile(r"^[\s﻿]+|[\s﻿]+$")


@cache
def _pattern(definition: str) -> re.Pattern[str]:
    pattern: str = load_schema(SchemaName.SUBSTANCES)["$defs"][definition]["pattern"]
    return re.compile(pattern)


def strip(text: str) -> str:
    """Remove whitespace and byte order marks from both ends."""
    return _EDGE.sub("", text)


def line(text: str) -> str | None:
    """Return the stripped text if it is valid single-line text, else ``None``."""
    stripped = strip(text)
    return stripped if _pattern("text").search(stripped) else None


def paragraphs(text: str) -> str | None:
    """Return the stripped text if it is valid text of paragraphs, else ``None``."""
    stripped = strip(text)
    return stripped if _pattern("paragraphs").search(stripped) else None


def describe(text: str) -> str:
    """Return a short, printable description of a rejected text for the report."""
    shown = strip(text)[:40].encode("unicode_escape").decode("ascii")
    return f"'{shown}'" if shown else "(empty)"
