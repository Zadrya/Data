# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the polite HTTP client. No test here touches the network."""

from collections.abc import Iterator

import httpx
import pytest

from zadrya_data import __version__
from zadrya_data.http import (
    DEADLINE_SECONDS,
    MAX_ATTEMPTS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    USER_AGENT,
    FetchError,
    PoliteClient,
)

URL = "https://api.example.test/"


class FakeTime:
    """A clock that only moves when the client sleeps."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(handler: httpx.MockTransport, fake: FakeTime | None = None) -> PoliteClient:
    fake = fake or FakeTime()
    return PoliteClient(handler, sleep=fake.sleep, clock=fake.clock)


def _answers(
    *responses: httpx.Response | Exception,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    queue = list(responses)
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return httpx.MockTransport(handle), seen


def test_user_agent_is_generic_and_carries_only_the_version() -> None:
    transport, seen = _answers(httpx.Response(200, json={"ok": True}))

    with _client(transport) as client:
        assert client.post_json(URL, {"query": "{ x }"}) == {"ok": True}

    assert USER_AGENT == f"dataset-builder/{__version__}"
    assert seen[0].headers["user-agent"] == USER_AGENT
    assert "from" not in seen[0].headers and "referer" not in seen[0].headers
    assert seen[0].headers["content-type"] == "application/json"


def test_form_fields_are_posted_url_encoded() -> None:
    transport, seen = _answers(httpx.Response(200, json=[]))

    with _client(transport) as client:
        assert client.post_form(URL, {"titles": "LSD|Βk-2C-B"}) == []

    assert seen[0].headers["content-type"] == "application/x-www-form-urlencoded"
    assert seen[0].content == b"titles=LSD%7C%CE%92k-2C-B"


def test_requests_are_at_least_one_second_apart() -> None:
    fake = FakeTime()
    transport, _ = _answers(*(httpx.Response(200, json={}) for _ in range(3)))

    with _client(transport, fake) as client:
        client.post_json(URL, {})
        fake.now += 0.25
        client.post_json(URL, {})
        fake.now += 5
        client.post_json(URL, {})

    assert fake.sleeps == [0.75]
    assert client.request_count == 3


def test_a_server_error_is_retried() -> None:
    fake = FakeTime()
    transport, seen = _answers(httpx.Response(500), httpx.Response(200, json={"ok": True}))

    with _client(transport, fake) as client:
        assert client.post_json(URL, {}) == {"ok": True}

    assert len(seen) == 2
    assert fake.sleeps == [1.0]


def test_a_timeout_is_retried_a_bounded_number_of_times() -> None:
    transport, seen = _answers(*(httpx.ReadTimeout("slow") for _ in range(MAX_ATTEMPTS)))

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.post_json(URL, {})

    assert len(seen) == MAX_ATTEMPTS == 3
    assert str(error.value) == f"{URL}: timed out, gave up after 3 attempts"


def test_repeated_server_errors_give_up() -> None:
    transport, seen = _answers(*(httpx.Response(503) for _ in range(MAX_ATTEMPTS)))

    with _client(transport) as client, pytest.raises(FetchError, match="HTTP 503, gave up"):
        client.post_json(URL, {})

    assert len(seen) == MAX_ATTEMPTS


def test_a_client_error_is_not_retried() -> None:
    transport, seen = _answers(httpx.Response(404))

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.post_json(URL, {})

    assert len(seen) == 1
    assert str(error.value) == f"{URL}: HTTP 404"


def test_a_redirect_is_not_followed() -> None:
    transport, seen = _answers(httpx.Response(302, headers={"location": "https://elsewhere.test/"}))

    with _client(transport) as client, pytest.raises(FetchError, match="HTTP 302"):
        client.post_json(URL, {})

    assert len(seen) == 1


def test_a_connection_failure_is_not_retried() -> None:
    transport, seen = _answers(httpx.ConnectError("no route"))

    with _client(transport) as client, pytest.raises(FetchError, match="ConnectError: no route"):
        client.post_json(URL, {})

    assert len(seen) == 1


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("<html>Bad gateway</html>", "not valid JSON"),
        ('{"min": NaN}', "NaN is not a JSON number"),
        ('{"a": 1, "a": 2}', "appears twice"),
    ],
)
def test_an_answer_that_is_not_strict_json_fails(body: str, reason: str) -> None:
    transport, _ = _answers(httpx.Response(200, text=body))

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.post_json(URL, {})

    assert "the answer is not JSON" in str(error.value)
    assert reason in str(error.value)


def test_the_environment_cannot_reroute_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:3128")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/ca.pem")

    with PoliteClient() as client:
        inner = client._client

    assert inner.trust_env is False
    assert all(transport is None for transport in inner._mounts.values())


def test_an_answer_that_declares_too_many_bytes_is_refused() -> None:
    headers = {"content-length": str(MAX_RESPONSE_BYTES + 1)}
    transport, seen = _answers(httpx.Response(200, headers=headers, content=b""))

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.post_json(URL, {})

    assert str(error.value) == f"{URL}: the answer is larger than {MAX_RESPONSE_BYTES} bytes"
    assert len(seen) == 1


def test_an_answer_that_streams_too_many_bytes_is_dropped_while_it_streams() -> None:
    produced: list[int] = []

    def endless() -> Iterator[bytes]:
        while True:
            produced.append(1)
            yield b"x" * (1024 * 1024)

    transport, seen = _answers(httpx.Response(200, content=endless()))

    with _client(transport) as client, pytest.raises(FetchError, match="is larger than"):
        client.post_json(URL, {})

    assert len(seen) == 1
    assert len(produced) <= MAX_RESPONSE_BYTES // (1024 * 1024) + 1


def test_an_answer_that_drips_past_the_deadline_counts_as_a_timeout() -> None:
    fake = FakeTime()

    def drip() -> Iterator[bytes]:
        for _ in range(1000):
            fake.now += DEADLINE_SECONDS / 4
            yield b" "

    transport, seen = _answers(*(httpx.Response(200, content=drip()) for _ in range(MAX_ATTEMPTS)))

    with _client(transport, fake) as client, pytest.raises(FetchError) as error:
        client.post_json(URL, {})

    assert str(error.value) == f"{URL}: took longer than 120 seconds, gave up after 3 attempts"
    assert len(seen) == MAX_ATTEMPTS


def test_a_slow_answer_within_the_deadline_is_read() -> None:
    fake = FakeTime()

    def slow() -> Iterator[bytes]:
        for part in (b'{"ok"', b": tr", b"ue}"):
            fake.now += DEADLINE_SECONDS / 4
            yield part

    transport, _ = _answers(httpx.Response(200, content=slow()))

    with _client(transport, fake) as client:
        assert client.post_json(URL, {}) == {"ok": True}


def test_retry_after_on_a_503_is_honoured() -> None:
    fake = FakeTime()
    transport, seen = _answers(
        httpx.Response(503, headers={"retry-after": "7"}), httpx.Response(200, json={"ok": True})
    )

    with _client(transport, fake) as client:
        assert client.post_json(URL, {}) == {"ok": True}

    assert fake.sleeps == [7]
    assert len(seen) == 2


def test_retry_after_beyond_the_bound_fails_instead_of_waiting() -> None:
    fake = FakeTime()
    headers = {"retry-after": str(MAX_RETRY_AFTER_SECONDS + 1)}
    transport, seen = _answers(httpx.Response(503, headers=headers))

    with _client(transport, fake) as client, pytest.raises(FetchError) as error:
        client.post_json(URL, {})

    assert str(error.value) == (
        f"{URL}: HTTP 503 asks to retry after 61 seconds, more than the 60 this client waits"
    )
    assert fake.sleeps == [] and len(seen) == 1


@pytest.mark.parametrize(
    ("status", "value"),
    [(503, "Wed, 21 Oct 2026 07:28:00 GMT"), (503, "-5"), (500, "30")],
)
def test_other_retry_after_values_fall_back_to_the_usual_interval(status: int, value: str) -> None:
    fake = FakeTime()
    transport, _ = _answers(
        httpx.Response(status, headers={"retry-after": value}), httpx.Response(200, json={})
    )

    with _client(transport, fake) as client:
        assert client.post_json(URL, {}) == {}

    assert fake.sleeps == [1.0]


def test_an_answer_that_is_not_utf_8_fails() -> None:
    transport, _ = _answers(httpx.Response(200, content=b'{"name": "\xff"}'))

    with _client(transport) as client, pytest.raises(FetchError, match="the answer is not JSON"):
        client.post_json(URL, {})


def test_retry_after_is_not_waited_for_after_the_last_attempt() -> None:
    fake = FakeTime()
    transport, seen = _answers(
        *(httpx.Response(503, headers={"retry-after": "7"}) for _ in range(MAX_ATTEMPTS))
    )

    with _client(transport, fake) as client, pytest.raises(FetchError, match="HTTP 503, gave up"):
        client.post_json(URL, {})

    assert len(seen) == MAX_ATTEMPTS
    assert fake.sleeps == [7, 7]


ASSET_URL = "https://github.example.test/releases/download/v1/file"
ASSET_HOSTS = frozenset({"assets.example.test"})


def test_get_bytes_returns_the_body_as_it_came() -> None:
    transport, seen = _answers(httpx.Response(200, content=b"\x00raw bytes\n"))

    with _client(transport) as client:
        assert client.get_bytes(ASSET_URL) == b"\x00raw bytes\n"

    assert seen[0].method == "GET"
    assert seen[0].headers["user-agent"] == USER_AGENT


def test_get_bytes_follows_one_redirect_to_an_allowed_host() -> None:
    target = "https://assets.example.test/file?token=temporary"
    transport, seen = _answers(
        httpx.Response(302, headers={"location": target}), httpx.Response(200, content=b"data")
    )

    with _client(transport) as client:
        assert client.get_bytes(ASSET_URL, redirect_hosts=ASSET_HOSTS) == b"data"

    assert [str(request.url) for request in seen] == [ASSET_URL, target]


@pytest.mark.parametrize(
    ("location", "shown"),
    [
        ("https://elsewhere.test/file", "elsewhere.test"),
        ("http://assets.example.test/file", "assets.example.test"),
        ("https://assets.example.test:8443/file", "assets.example.test"),
        ("https://user@assets.example.test/file", "assets.example.test"),
        ("https://assets.example.test.evil.test/file", "assets.example.test.evil.test"),
        ("/relative/file", "an invalid address"),
        ("", "an invalid address"),
    ],
)
def test_get_bytes_refuses_a_redirect_anywhere_else(location: str, shown: str) -> None:
    transport, seen = _answers(httpx.Response(302, headers={"location": location}))

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.get_bytes(ASSET_URL, redirect_hosts=ASSET_HOSTS)

    assert str(error.value) == (
        f"{ASSET_URL}: redirects to {shown}, which is not an allowed download host"
    )
    assert len(seen) == 1


def test_get_bytes_fails_on_a_redirect_to_an_address_that_cannot_be_parsed() -> None:
    location = "https://assets.example.test:x/file"
    transport, seen = _answers(httpx.Response(302, headers={"location": location}))

    with _client(transport) as client, pytest.raises(FetchError, match="Invalid URL in location"):
        client.get_bytes(ASSET_URL, redirect_hosts=ASSET_HOSTS)

    assert len(seen) == 1


def test_get_bytes_follows_no_redirect_without_allowed_hosts() -> None:
    transport, seen = _answers(
        httpx.Response(302, headers={"location": "https://assets.example.test/file"})
    )

    with _client(transport) as client, pytest.raises(FetchError, match="not an allowed"):
        client.get_bytes(ASSET_URL)

    assert len(seen) == 1


def test_get_bytes_refuses_a_second_redirect_and_hides_the_token() -> None:
    transport, seen = _answers(
        httpx.Response(302, headers={"location": "https://assets.example.test/f?token=secret"}),
        httpx.Response(302, headers={"location": "https://assets.example.test/again"}),
    )

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.get_bytes(ASSET_URL, redirect_hosts=ASSET_HOSTS)

    assert str(error.value) == f"{ASSET_URL} (via assets.example.test): HTTP 302"
    assert len(seen) == 2


def test_get_bytes_keeps_the_size_cap_after_a_redirect() -> None:
    headers = {"content-length": str(MAX_RESPONSE_BYTES + 1)}
    transport, _ = _answers(
        httpx.Response(302, headers={"location": "https://assets.example.test/f"}),
        httpx.Response(200, headers=headers, content=b""),
    )

    with _client(transport) as client, pytest.raises(FetchError, match="is larger than"):
        client.get_bytes(ASSET_URL, redirect_hosts=ASSET_HOSTS)


def test_get_redirect_returns_the_target_without_following_it() -> None:
    transport, seen = _answers(httpx.Response(302, headers={"location": "https://x.test/tag/a"}))

    with _client(transport) as client:
        assert client.get_redirect(ASSET_URL) == "https://x.test/tag/a"

    assert len(seen) == 1


def test_get_redirect_fails_on_an_answer_that_is_not_a_redirect() -> None:
    transport, _ = _answers(httpx.Response(200, content=b"page"))

    with _client(transport) as client, pytest.raises(FetchError) as error:
        client.get_redirect(ASSET_URL)

    assert str(error.value) == f"{ASSET_URL}: expected a redirect, got HTTP 200"
