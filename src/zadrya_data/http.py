# SPDX-License-Identifier: GPL-3.0-or-later
"""The one HTTP client of the pipeline: slow, bounded and anonymous.

Only the ``fetch`` command uses the network. Every request goes through
``PoliteClient``, which waits at least one second between requests, gives up after a
timeout, retries a few times on a timeout or a server error (5xx) and identifies
itself as ``dataset-builder/<version>`` with nothing that names a person or a project.
Responses are read as strict JSON.
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


class FetchError(RuntimeError):
    """A request failed for good, or its answer is not what the pipeline can read."""


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
            try:
                response = self._client.post(url, json=json, data=data)
            except httpx.TimeoutException:
                failure = "timed out"
                continue
            except httpx.HTTPError as error:
                raise FetchError(f"{url}: {type(error).__name__}: {error}") from error
            if response.status_code >= 500:
                failure = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise FetchError(f"{url}: HTTP {response.status_code}")
            try:
                return loads(response.text)
            except StrictJsonError as error:
                raise FetchError(f"{url}: the answer is not JSON: {error}") from error
        raise FetchError(f"{url}: {failure}, gave up after {MAX_ATTEMPTS} attempts")

    def _wait_for_turn(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self._last_request + MIN_INTERVAL_SECONDS - now
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request = now
