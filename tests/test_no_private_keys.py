# SPDX-License-Identifier: GPL-3.0-or-later
"""No file of the repository may contain a PEM private key, not even a test key.

Tests create their keys in memory or in a temporary directory. This test reads
every file that git tracks, and every new file that git would add, and fails when
one holds the header of a private key in PEM or OpenSSH form.
"""

import re
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).parents[1]

# Matches the first line of any PEM private key: PKCS#8 (plain or ENCRYPTED), the
# older RSA, EC and DSA forms, and OpenSSH. The expression is assembled from two
# parts so that this file does not contain the text it looks for.
_DASHES = b"-" * 5
PRIVATE_KEY_HEADER = re.compile(_DASHES + rb"BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY" + _DASHES)


def _repository_files() -> list[Path]:
    """Return the tracked files and the untracked ones that are not ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    ).stdout
    return [REPOSITORY / name.decode("utf-8") for name in listed.split(b"\0") if name]


def test_the_expression_finds_every_private_key_header() -> None:
    for kind in ("", "ENCRYPTED ", "RSA ", "EC ", "DSA ", "OPENSSH "):
        header = _DASHES + b"BEGIN " + kind.encode("ascii") + b"PRIVATE KEY" + _DASHES
        assert PRIVATE_KEY_HEADER.search(b"before\n" + header + b"\nafter")


def test_the_expression_ignores_public_keys_and_prose() -> None:
    public = _DASHES + b"BEGIN PUBLIC KEY" + _DASHES
    assert PRIVATE_KEY_HEADER.search(public) is None
    assert PRIVATE_KEY_HEADER.search(b"the BEGIN PRIVATE KEY line of a PEM") is None


def test_no_file_of_the_repository_contains_a_private_key() -> None:
    files = _repository_files()
    # A listing that misses known files would make this test pass on nothing.
    assert REPOSITORY / "pyproject.toml" in files
    assert Path(__file__) in files

    # A file that is listed but gone (deleted and not yet staged) has no content.
    found = [
        str(path.relative_to(REPOSITORY))
        for path in files
        if path.is_file() and PRIVATE_KEY_HEADER.search(path.read_bytes())
    ]

    assert found == []
