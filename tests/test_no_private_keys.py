# SPDX-License-Identifier: GPL-3.0-or-later
"""No file of the repository may contain a PEM private key, not even a test key.

Tests create their keys in memory or in a temporary directory. This test looks for
the first line of a private key in PEM or OpenSSH form in two places:

- the working tree: every file that git tracks, and every new file that git would
  add (untracked and not ignored);
- the index: the staged content of every path, which is what the next commit
  records. A key that was staged and then deleted or overwritten in the working
  tree is still found there.

What it does not detect, so it is a safety net and not a guarantee:

- a key in another encoding: DER (binary), a PEM whose lines were re-encoded,
  escaped, split or wrapped in another format, and anything compressed or encrypted;
- a key in a file that ``.gitignore`` excludes and that was never staged;
- a key in the history: commits that already exist are not read, here or in CI.
"""

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPOSITORY = Path(__file__).parents[1]

# Matches the first line of any PEM private key: PKCS#8 (plain or ENCRYPTED), the
# older RSA, EC and DSA forms, and OpenSSH. The expression is assembled from two
# parts so that this file does not contain the text it looks for.
_DASHES = b"-" * 5
PRIVATE_KEY_HEADER = re.compile(_DASHES + rb"BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY" + _DASHES)

_SUBMODULE = b"160000"


def _git(
    arguments: list[str],
    repository: Path,
    environment: Mapping[str, str] | None,
    stdin: bytes | None = None,
) -> bytes:
    """Run git in the repository. ``None`` keeps the environment of this process."""
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=environment,
        input=stdin,
        check=True,
        capture_output=True,
    ).stdout


def working_tree_files(repository: Path, environment: Mapping[str, str] | None) -> list[Path]:
    """Return the tracked files and the untracked ones that are not ignored."""
    listed = _git(
        ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], repository, environment
    )
    return [repository / name.decode("utf-8") for name in listed.split(b"\0") if name]


def index_contents(
    repository: Path, environment: Mapping[str, str] | None
) -> list[tuple[str, bytes]]:
    """Return the staged content of every path of the index, as (path, bytes)."""
    entries: list[tuple[str, bytes]] = []
    for entry in _git(["ls-files", "-z", "--stage"], repository, environment).split(b"\0"):
        if entry:
            details, _, raw_name = entry.partition(b"\t")
            mode, blob, _stage = details.split(b" ")
            if mode != _SUBMODULE:
                entries.append((raw_name.decode("utf-8"), blob))
    blobs = b"".join(blob + b"\n" for _, blob in entries)
    output = _git(["cat-file", "--batch"], repository, environment, stdin=blobs)
    contents: list[tuple[str, bytes]] = []
    position = 0
    for name, blob in entries:
        end_of_header = output.index(b"\n", position)
        found, kind, size = output[position:end_of_header].split(b" ")
        assert (found, kind) == (blob, b"blob")
        start = end_of_header + 1
        contents.append((name, output[start : start + int(size)]))
        position = start + int(size) + 1
    assert position == len(output)
    return contents


def find_private_keys(repository: Path, environment: Mapping[str, str] | None = None) -> list[str]:
    """Return where a private key header is: working tree files and staged content."""
    found = [
        str(path.relative_to(repository))
        # A file that is listed but gone (deleted and not yet staged) has no content.
        for path in working_tree_files(repository, environment)
        if path.is_file() and PRIVATE_KEY_HEADER.search(path.read_bytes())
    ]
    found += [
        f"{name} (staged)"
        for name, content in index_contents(repository, environment)
        if PRIVATE_KEY_HEADER.search(content)
    ]
    return found


def test_the_expression_finds_every_private_key_header() -> None:
    for kind in ("", "ENCRYPTED ", "RSA ", "EC ", "DSA ", "OPENSSH "):
        header = _DASHES + b"BEGIN " + kind.encode("ascii") + b"PRIVATE KEY" + _DASHES
        assert PRIVATE_KEY_HEADER.search(b"before\n" + header + b"\nafter")


def test_the_expression_ignores_public_keys_and_prose() -> None:
    public = _DASHES + b"BEGIN PUBLIC KEY" + _DASHES
    assert PRIVATE_KEY_HEADER.search(public) is None
    assert PRIVATE_KEY_HEADER.search(b"the BEGIN PRIVATE KEY line of a PEM") is None


def test_no_file_of_the_repository_contains_a_private_key() -> None:
    # A listing that misses known files would make this test pass on nothing.
    files = working_tree_files(REPOSITORY, None)
    assert REPOSITORY / "pyproject.toml" in files
    assert Path(__file__) in files
    staged = dict(index_contents(REPOSITORY, None))
    assert staged["pyproject.toml"].startswith(b"# SPDX-License-Identifier")

    assert find_private_keys(REPOSITORY) == []


# ---- the search itself, on a throwaway repository


@pytest.fixture
def scratch(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Return an empty repository and an environment in which git can only see it.

    Git exports variables such as ``GIT_DIR`` and ``GIT_INDEX_FILE`` to hooks, and
    this test runs inside the pre-commit hook: with them, every git command here
    would act on the real repository. They are removed, and the fixture checks that
    git then resolves the throwaway repository before any test writes to it.
    """
    exported = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], check=True, capture_output=True, text=True
    ).stdout.split()
    assert "GIT_DIR" in exported and "GIT_INDEX_FILE" in exported
    environment = {name: value for name, value in os.environ.items() if name not in exported}
    # Never look for a repository above the temporary directory.
    environment["GIT_CEILING_DIRECTORIES"] = str(tmp_path.resolve())
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(["init", "--quiet"], repository, environment)
    git_directory = _git(["rev-parse", "--absolute-git-dir"], repository, environment)
    assert Path(git_directory.decode("utf-8").strip()) == repository.resolve() / ".git"
    return repository, environment


def _throwaway_key() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def test_a_repository_without_keys_is_clean(scratch: tuple[Path, dict[str, str]]) -> None:
    repository, environment = scratch
    (repository / "notes.txt").write_text("nothing secret\n", encoding="utf-8")
    (repository / "empty.txt").write_bytes(b"")
    _git(["add", "notes.txt", "empty.txt"], repository, environment)

    assert find_private_keys(repository, environment) == []
    assert index_contents(repository, environment) == [
        ("empty.txt", b""),
        ("notes.txt", b"nothing secret\n"),
    ]


def test_a_new_file_with_a_key_is_found_before_it_is_staged(
    scratch: tuple[Path, dict[str, str]],
) -> None:
    repository, environment = scratch
    (repository / "signing.pem").write_bytes(_throwaway_key())

    assert find_private_keys(repository, environment) == ["signing.pem"]


def test_a_staged_key_is_found_in_both_places(scratch: tuple[Path, dict[str, str]]) -> None:
    repository, environment = scratch
    (repository / "signing.pem").write_bytes(_throwaway_key())
    _git(["add", "signing.pem"], repository, environment)

    assert find_private_keys(repository, environment) == ["signing.pem", "signing.pem (staged)"]


def test_a_key_staged_and_then_deleted_is_still_found(
    scratch: tuple[Path, dict[str, str]],
) -> None:
    repository, environment = scratch
    (repository / "signing.pem").write_bytes(_throwaway_key())
    _git(["add", "signing.pem"], repository, environment)
    (repository / "signing.pem").unlink()

    assert find_private_keys(repository, environment) == ["signing.pem (staged)"]


def test_a_key_staged_and_then_overwritten_is_still_found(
    scratch: tuple[Path, dict[str, str]],
) -> None:
    repository, environment = scratch
    (repository / "notes.txt").write_bytes(b"binary \x00 before\n" + _throwaway_key())
    _git(["add", "notes.txt"], repository, environment)
    (repository / "notes.txt").write_text("harmless now\n", encoding="utf-8")

    assert find_private_keys(repository, environment) == ["notes.txt (staged)"]


def test_an_ignored_file_is_a_documented_blind_spot(scratch: tuple[Path, dict[str, str]]) -> None:
    repository, environment = scratch
    (repository / ".gitignore").write_text("*.pem\n", encoding="utf-8")
    (repository / "signing.pem").write_bytes(_throwaway_key())

    assert find_private_keys(repository, environment) == []
