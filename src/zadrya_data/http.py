# SPDX-License-Identifier: GPL-3.0-or-later
"""The one HTTP client of the pipeline: slow, bounded and anonymous.

Two commands use the network: ``fetch`` (the PsychonautWiki API and wiki) and
``verify --release`` (the assets of a published release). Every request goes through
``PoliteClient``, which waits at least one second between requests, gives up after a
timeout, retries a few times on a timeout or a server error (5xx) and identifies
itself as ``dataset-builder/<version>`` with nothing that names a person or a project.
Answers to a POST are read as strict JSON; a GET returns the bytes as they came.

It also refuses to be steered or stalled: proxy and certificate variables of the
environment are ignored, an answer larger than ``MAX_RESPONSE_BYTES`` is dropped
while it streams, an answer that drips in for longer than ``DEADLINE_SECONDS`` counts
as a timeout, and a ``Retry-After`` on a 503 is honoured up to
``MAX_RETRY_AFTER_SECONDS`` and is a failure beyond that. Redirects are not followed,
except by ``get_bytes``: once, over HTTPS, and only to a host the caller names.
"""

import time
from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

from zadrya_data import __version__
from zadrya_data.strict_json import StrictJsonError, loads

USER_AGENT = f"dataset-builder/{__version__}"
TIMEOUT_SECONDS = 30.0
MIN_INTERVAL_SECONDS = 1.0
MAX_ATTEMPTS = 3
# The real answers are under 1 MB.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# The timeout above is per read. This bounds one whole request.
DEADLINE_SECONDS = 120.0
MAX_RETRY_AFTER_SECONDS = 60
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class FetchError(RuntimeError):
    """A request failed for good, or its answer is not what the pipeline can read."""


class _TooSlow(Exception):
    """One request went past its overall deadline."""


@dataclass(frozen=True)
class _Answer:
    """The body of a 200 answer, or the target of a redirect that the caller accepts."""

    body: bytes = b""
    location: str | None = None


class PoliteClient:
    """An ``httpx`` client with a rate limit, a timeout, bounded retries and a fixed User-Agent."""

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = httpx.Client(
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            trust_env=False,
        )
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.request_count = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release the connections."""
        self._client.close()

    def post_json(self, url: str, payload: Mapping[str, object]) -> object:
        """POST a JSON body and return the JSON answer."""
        return self._json(url, self._request("POST", url, json=payload).body)

    def post_form(self, url: str, fields: Mapping[str, str]) -> object:
        """POST form fields and return the JSON answer."""
        return self._json(url, self._request("POST", url, data=fields).body)

    def get_redirect(self, url: str) -> str:
        """GET a URL that answers with a redirect, and return its target without following it."""
        answer = self._request("GET", url, redirect_ok=True)
        if answer.location is None:
            raise FetchError(f"{url}: expected a redirect, got HTTP 200")
        return answer.location

    def get_bytes(self, url: str, *, redirect_hosts: Set[str] = frozenset()) -> bytes:
        """GET a URL and return the bytes of the answer.

        One redirect is followed, and only to an ``https`` address on one of
        ``redirect_hosts`` (exact host names, default port, no user name). Any other
        redirect, and a second one, is a ``FetchError``. The target is never shown in
        full, because a download address can carry a temporary token.
        """
        answer = self._request("GET", url, redirect_ok=True)
        if answer.location is None:
            return answer.body
        # httpx has already refused a Location it cannot parse (a FetchError above).
        target = httpx.URL(answer.location)
        if (
            target.scheme != "https"
            or target.host not in redirect_hosts
            or target.userinfo != b""
            or target.port is not None
        ):
            host = target.host or "an invalid address"
            raise FetchError(f"{url}: redirects to {host}, which is not an allowed download host")
        return self._request("GET", str(target), shown=f"{url} (via {target.host})").body

    @staticmethod
    def _json(url: str, body: bytes) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, StrictJsonError) as error:
            raise FetchError(f"{url}: the answer is not JSON: {error}") from error

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        data: Mapping[str, str] | None = None,
        redirect_ok: bool = False,
        shown: str | None = None,
    ) -> _Answer:
        shown = url if shown is None else shown
        failure = "no attempt was made"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait_for_turn()
            self.request_count += 1
            started = self._clock()
            try:
                with self._client.stream(method, url, json=json, data=data) as response:
                    if response.status_code >= 500:
                        failure = f"HTTP {response.status_code}"
                        if attempt < MAX_ATTEMPTS:
                            self._honour_retry_after(response, shown)
                        continue
                    if redirect_ok and response.status_code in REDIRECT_STATUSES:
                        return _Answer(location=response.headers.get("location", ""))
                    if response.status_code != 200:
                        raise FetchError(f"{shown}: HTTP {response.status_code}")
                    return _Answer(body=self._read(response, shown, started))
            except httpx.TimeoutException:
                failure = "timed out"
                continue
            except _TooSlow:
                failure = f"took longer than {DEADLINE_SECONDS:g} seconds"
                continue
            except httpx.HTTPError as error:
                raise FetchError(f"{shown}: {type(error).__name__}: {error}") from error
        raise FetchError(f"{shown}: {failure}, gave up after {MAX_ATTEMPTS} attempts")

    def _read(self, response: httpx.Response, url: str, started: float) -> bytes:
        """Read the body while it streams, within the size cap and the deadline."""
        too_large = FetchError(f"{url}: the answer is larger than {MAX_RESPONSE_BYTES} bytes")
        declared = response.headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > MAX_RESPONSE_BYTES:
            raise too_large
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > MAX_RESPONSE_BYTES:
                raise too_large
            if self._clock() - started > DEADLINE_SECONDS:
                raise _TooSlow
        return bytes(body)

    def _honour_retry_after(self, response: httpx.Response, url: str) -> None:
        """Wait as long as a 503 asks, or fail if it asks for more than the bound.

        Only the form in whole seconds is understood. Any other value is ignored, and
        the next attempt follows the usual interval.
        """
        asked = response.headers.get("retry-after", "")
        if response.status_code != 503 or not asked.isdecimal():
            return
        seconds = int(asked)
        if seconds > MAX_RETRY_AFTER_SECONDS:
            raise FetchError(
                f"{url}: HTTP 503 asks to retry after {seconds} seconds, more than the "
                f"{MAX_RETRY_AFTER_SECONDS} this client waits"
            )
        self._sleep(seconds)

    def _wait_for_turn(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self._last_request + MIN_INTERVAL_SECONDS - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request = now
