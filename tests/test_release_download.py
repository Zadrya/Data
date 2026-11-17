# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the download of a published release. No test here touches the network."""

import httpx
import pytest

from zadrya_data.errors import ReleaseRejectedError
from zadrya_data.http import FetchError, PoliteClient
from zadrya_data.release_download import (
    ASSET_HOSTS,
    RELEASES_URL,
    ReleaseTagError,
    ReleaseTagMismatchError,
    check_tag,
    resolve_tag,
    version_of_tag,
)


def _client(location: str | None) -> tuple[PoliteClient, list[str]]:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if location is None:
            return httpx.Response(200, content=b"<html></html>")
        return httpx.Response(302, headers={"location": location})

    return PoliteClient(httpx.MockTransport(handle), sleep=lambda _: None), seen


def test_the_release_addresses_are_the_ones_the_adr_records() -> None:
    assert RELEASES_URL == "https://github.com/Zadrya/Data/releases"
    assert ASSET_HOSTS == {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }


@pytest.mark.parametrize(
    ("tag", "version"),
    [("dataset-v1.0.0", "1.0.0"), ("dataset-v0.10.200", "0.10.200")],
)
def test_a_dataset_tag_names_its_version(tag: str, version: str) -> None:
    assert version_of_tag(tag) == version


@pytest.mark.parametrize(
    "tag",
    [
        "v1.0.0",
        "dataset-1.0.0",
        "dataset-v1.0",
        "dataset-v01.0.0",
        "dataset-v1.0.0-rc.1",
        "dataset-v1.0.0/../../evil",
        "dataset-v1.0.0\n",
        "dataset-v١.0.0",
        "pipeline-v1.0.0",
        "",
    ],
)
def test_anything_else_is_not_a_dataset_tag(tag: str) -> None:
    with pytest.raises(ReleaseTagError, match="is not a dataset release tag"):
        version_of_tag(tag)


def test_a_named_tag_is_used_without_a_request() -> None:
    client, seen = _client(None)

    with client:
        assert resolve_tag(client, "dataset-v2.1.0") == "dataset-v2.1.0"

    assert seen == []


def test_latest_is_resolved_once_from_the_redirect() -> None:
    client, seen = _client(f"{RELEASES_URL}/tag/dataset-v1.3.0")

    with client:
        assert resolve_tag(client, "latest") == "dataset-v1.3.0"

    assert seen == [f"{RELEASES_URL}/latest"]


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("https://github.com/Other/Data/releases/tag/dataset-v1.0.0", "does not lead"),
        ("/Zadrya/Data/releases/tag/dataset-v1.0.0", "does not lead"),
        (f"{RELEASES_URL}/tag/pipeline-v0.2.0", "is not a dataset release tag"),
    ],
)
def test_latest_must_lead_to_a_dataset_tag_of_this_repository(location: str, reason: str) -> None:
    client, _ = _client(location)

    with client, pytest.raises(ReleaseTagError, match=reason):
        resolve_tag(client, "latest")


def test_latest_without_a_redirect_fails() -> None:
    client, _ = _client(None)

    with client, pytest.raises(FetchError, match="expected a redirect"):
        resolve_tag(client, "latest")


def test_the_tag_must_name_the_signed_version() -> None:
    check_tag("dataset-v1.0.0", "1.0.0")

    with pytest.raises(ReleaseTagMismatchError) as error:
        check_tag("dataset-v1.0.0", "1.0.1")

    assert isinstance(error.value, ReleaseRejectedError)
