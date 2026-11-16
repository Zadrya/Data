# SPDX-License-Identifier: GPL-3.0-or-later
"""The one HTTP client of the pipeline: slow, bounded and anonymous.

Only the ``fetch`` command uses the network. Every request goes through
``PoliteClient``, which waits at least one second between requests, gives up after a
timeout, retries a few times on a timeout or a server error (5xx) and identifies
itself as ``dataset-builder/<version>`` with nothing that names a person or a project.
Responses are read as strict JSON.

It also refuses to be steered or stalled: proxy and certificate variables of the
environment are ignored, an answer larger than ``MAX_RESPONSE_BYTES`` is dropped
while it streams, an answer that drips in for longer than ``DEADLINE_SECONDS`` counts
as a timeout, and a ``Retry-After`` on a 503 is honoured up to
``MAX_RETRY_AFTER_SECONDS`` and is a failure beyond that.
"""

import time
from collections.abc import Callable, Mapping
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


class FetchError(RuntimeError):
    """A request failed for good, or its answer is not what the pipeline can read."""


class _TooSlow(Exception):
    """One request went past its overall deadline."""


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
        return self._request(url, json=payload)

    def post_form(self, url: str, fields: Mapping[str, str]) -> object:
        """POST form fields and return the JSON answer."""
        return self._request(url, data=fields)

    def _request(
        self,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> object:
        failure = "no attempt was made"
        for _ in range(MAX_ATTEMPTS):
            self._wait_for_turn()
            self.request_count += 1
            started = self._clock()
            try:
                with self._client.stream("POST", url, json=json, data=data) as response:
                    if response.status_code >= 500:
                        failure = f"HTTP {response.status_code}"
                        self._honour_retry_after(response, url)
                        continue
                    if response.status_code != 200:
                        raise FetchError(f"{url}: HTTP {response.status_code}")
                    body = self._read(response, url, started)
            except httpx.TimeoutException:
                failure = "timed out"
                continue
            except _TooSlow:
                failure = f"took longer than {DEADLINE_SECONDS:g} seconds"
                continue
            except httpx.HTTPError as error:
                raise FetchError(f"{url}: {type(error).__name__}: {error}") from error
            try:
                return loads(body.decode("utf-8"))
            except (UnicodeDecodeError, StrictJsonError) as error:
                raise FetchError(f"{url}: the answer is not JSON: {error}") from error
        raise FetchError(f"{url}: {failure}, gave up after {MAX_ATTEMPTS} attempts")

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
