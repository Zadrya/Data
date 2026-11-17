# SPDX-License-Identifier: GPL-3.0-or-later
"""Download the three assets of a published dataset release from GitHub.

This is the second, and last, network path of the pipeline (``fetch`` is the
other). It only reads public release assets of ``Zadrya/Data``, through
``PoliteClient``, and never decides anything: ``verify_release`` does. The
addresses, the redirect hosts and the tag scheme are recorded in
``docs/adr/0005-release.md``.

A dataset release is tagged ``dataset-vX.Y.Z``, where ``X.Y.Z`` is the
``datasetVersion`` inside the signed ``substances.json``. ``check_tag`` makes sure
the two agree, so a release cannot be published, or found, under another version.
"""

import re

from zadrya_data.errors import ReleaseRejectedError
from zadrya_data.http import PoliteClient

REPOSITORY_URL = "https://github.com/Zadrya/Data"
RELEASES_URL = f"{REPOSITORY_URL}/releases"
# GitHub answers a release download on github.com with one redirect to its asset
# storage: release-assets.githubusercontent.com today, objects.githubusercontent.com
# before. No other host is ever contacted.
ASSET_HOSTS = frozenset({"release-assets.githubusercontent.com", "objects.githubusercontent.com"})
ASSET_NAMES = ("substances.json", "substances.json.sig", "manifest.json")
LATEST = "latest"
TAG_PREFIX = "dataset-v"

# The same versions as the "semver" definition of the schemas, ASCII digits only.
_VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
_TAG = re.compile(rf"{TAG_PREFIX}({_VERSION})", re.ASCII)


class ReleaseTagError(ReleaseRejectedError):
    """A tag is not a dataset tag, or ``latest`` does not lead to one."""


class ReleaseTagMismatchError(ReleaseRejectedError):
    """The tag of a release and the version inside its signed dataset differ."""


def version_of_tag(tag: str) -> str:
    """Return the dataset version that a ``dataset-vX.Y.Z`` tag names, or raise ``ReleaseTagError``."""
    match = _TAG.fullmatch(tag)
    if match is None:
        raise ReleaseTagError(
            f"{tag!r} is not a dataset release tag: it must be {TAG_PREFIX}MAJOR.MINOR.PATCH"
        )
    return match.group(1)


def resolve_tag(client: PoliteClient, requested: str) -> str:
    """Return the tag to download: ``requested`` itself, or the tag ``latest`` points to.

    ``latest`` is resolved once, by reading where GitHub's latest release page
    redirects, so that the three assets are then downloaded from the same release.
    """
    if requested != LATEST:
        version_of_tag(requested)
        return requested
    location = client.get_redirect(f"{RELEASES_URL}/{LATEST}")
    prefix = f"{RELEASES_URL}/tag/"
    if not location.startswith(prefix):
        raise ReleaseTagError(
            f"the latest release of {REPOSITORY_URL} does not lead to a release tag of it"
        )
    tag = location.removeprefix(prefix)
    version_of_tag(tag)
    return tag


def download_release(client: PoliteClient, tag: str) -> dict[str, bytes]:
    """Return the exact bytes of the three assets of the release, by asset name."""
    version_of_tag(tag)
    return {
        name: client.get_bytes(f"{RELEASES_URL}/download/{tag}/{name}", redirect_hosts=ASSET_HOSTS)
        for name in ASSET_NAMES
    }


def check_tag(tag: str, dataset_version: str) -> None:
    """Raise ``ReleaseTagMismatchError`` unless the tag names the signed dataset version."""
    if version_of_tag(tag) != dataset_version:
        raise ReleaseTagMismatchError(
            f"the release {tag} holds a signed dataset of version {dataset_version}: a release "
            f"is tagged with the version inside its dataset ({TAG_PREFIX}{dataset_version})"
        )
