# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the polite HTTP client. No test here touches the network."""

import httpx
import pytest

from zadrya_data import __version__
from zadrya_data.http import MAX_ATTEMPTS, USER_AGENT, FetchError, PoliteClient

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
