# SPDX-License-Identifier: GPL-3.0-or-later
"""Access to the schema fixture documents in ``tests/fixtures/schema``."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "schema"


def fixture_names(schema: str, kind: str) -> list[str]:
    """Return the sorted fixture names (file names without ``.json``) of one directory."""
    return sorted(path.stem for path in (FIXTURES / schema / kind).glob("*.json"))


def load_fixture(schema: str, kind: str, name: str) -> object:
    """Return one fixture document as parsed JSON."""
    document: object = json.loads((FIXTURES / schema / kind / f"{name}.json").read_text("utf-8"))
    return document
