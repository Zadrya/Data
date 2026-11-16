# SPDX-License-Identifier: GPL-3.0-or-later
"""The vendored base file is pinned by hash, so it can never drift silently."""

import hashlib
from pathlib import Path

BASE_FILE = Path(__file__).parents[1] / "sources" / "base" / "Substances.json"

# Substances.json at tag v11.11 (commit 73f013752cea2f05558c1ed091cdccd3dfcde62b) of
# isaakhanimann/psychonautwiki-journal-android. See NOTICE and DATA_LICENSES.md.
BASE_SHA256 = "a2300bea9bf8013fc97c4279eeb7393f1800766ec55455ac117502a1208a666f"


def test_vendored_base_file_is_byte_for_byte_the_v11_11_file() -> None:
    assert hashlib.sha256(BASE_FILE.read_bytes()).hexdigest() == BASE_SHA256
