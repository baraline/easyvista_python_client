"""HTTP executor for the EasyVista client.

Owns everything EasyVista-specific about talking to the API -- URL building,
auth headers, error mapping, and the executor itself -- except
``RequestSpec``, which stays at the package root because the shared resource
builders and the probe scripts consume it without executing anything.

This module exists once per client tree, and only the async copy is written by
hand: ``unasync_build.py`` generates the sync one from it, and CI's
``--check`` fails if the two have drifted. Edit the async copy and regenerate;
hand-editing the generated one is a mistake the check will catch. Prose here
must therefore read true on both surfaces -- never "see the other transport",
and never a claim that holds on only one of them.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, NoReturn
from urllib.parse import urlsplit

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from easyvista_python_client._transport import RequestSpec
from easyvista_python_client.config import EasyvistaConfig
from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    EasyvistaValidationError,
)

#: Default chunk size, in bytes, for :meth:`Transport.stream_bytes`.
#:
#: 64 KiB is the ceiling this default is chosen to set: a caller streams an
#: attachment precisely so the whole file never sits in memory, and the chunk
#: size is what one step of that costs. Large enough that a 32 MB attachment is
#: ~512 iterations rather than tens of thousands, small enough that the resident
#: peak stays negligible beside the file. Deliberately not a config field --
#: nobody has asked for an instance-wide value, and the one caller who cares
#: about a specific payload can pass ``chunk_size`` per call.
DEFAULT_STREAM_CHUNK_SIZE = 64 * 1024


class BaseTransport:
    """Pure transport logic, independent of how a request is executed (no I/O)."""

    def __init__(self, config: EasyvistaConfig) -> None:
        self.config = config

    def build_url(self, path: str) -> str:
        return f"{self.config.api_root}/{path.lstrip('/')}"

    def resolve_url(self, path_or_url: str) -> str:
        """Return an absolute URL for a resource path or an API-supplied URL.

        Relative paths join to ``api_root`` exactly as :meth:`build_url` does.
        An absolute URL is passed through **only when its scheme and host match
        ``config.server``**, and raises otherwise.

        That check is load-bearing, not decoration. Every request this transport
        makes carries the instance's Bearer token, so following an absolute URL
        taken out of a response body (an attachment's ``DDL_HREF``, say) would
        hand that credential to whatever host the body named.

        What is guaranteed is exactly that and no more: a foreign URL in a
        response **body** is refused. An HTTP **redirect** off the instance is
        still *followed* -- both download paths run with
        ``follow_redirects=True``, which signed-location hops depend on -- and it
        merely loses the credential (verified: no ``authorization`` header on the
        foreign request, for Bearer and for Basic; a same-host redirect keeps
        it). So streamed or downloaded bytes are not proof of instance origin,
        and a caller must not treat them as such.
        """
        parsed = urlsplit(path_or_url)
        if not parsed.scheme and not parsed.netloc:
            return self.build_url(path_or_url)
        server = urlsplit(self.config.server)
        # Host comparison is case-folded because DNS is case-insensitive and
        # this API returns mixed-case URLs (live: an upper-case "HTTPS://"
        # scheme on DDL_HREF). Compare the RAW netloc, not .hostname: that
        # keeps "https://attacker.test@ev.test/x" rejected, because its netloc
        # is "attacker.test@ev.test", not "ev.test".
        if (parsed.scheme, parsed.netloc.lower()) != (
            server.scheme,
            server.netloc.lower(),
        ):
            raise EasyvistaError(
                f"refusing to fetch {parsed.scheme}://{parsed.netloc} — it is "
                f"outside the configured instance "
                f"({server.scheme}://{server.netloc})"
            )
        return path_or_url

    def headers(self) -> dict[str, str]:
        base = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.config.token:
            base["Authorization"] = f"Bearer {self.config.token}"
        return base

    def auth(self) -> httpx.Auth | None:
        if self.config.uses_basic_auth:
            return httpx.BasicAuth(self.config.login or "", self.config.password or "")
        return None

    @staticmethod
    def is_retryable_status(status_code: int) -> bool:
        # 590 is EasyVista's "Internal Easyvista Error" — in practice a *rejected
        # request* (bad catalog, missing mandatory field), so it is deterministic.
        if status_code == 590:
            return False
        return status_code == 429 or status_code >= 500

    def finish(self, response: httpx.Response) -> Any:
        """Return parsed JSON for a success, or raise a mapped exception."""
        if response.is_success:
            if not response.content:
                return {}
            return response.json()
        return self._raise_for_response(response)

    def _raise_for_response(self, response: httpx.Response) -> NoReturn:
        status = response.status_code
        ev_code, ev_message = self._extract_error(response)
        # Never interpolate the raw body: no layer redacts exception TEXT, and a
        # short traceback still emits `E <Type>: <msg>` while the `-r` summary
        # reuses it verbatim -- so an unrecognized body prints wherever the
        # exception surfaces. The byte count keeps the diagnostic ("the server
        # said something we do not parse, and it was this big") without the
        # content; `.ev_message` and `.ev_code` carry the parsed values, and
        # `.body` (below) carries the raw bytes themselves, for a caller with no
        # other way to see what an unrecognized response actually said.
        detail = ev_message or (
            f"<{len(response.content)}-byte body with no recognized error key>"
        )
        message = f"EasyVista request failed ({status}): {detail}"
        kwargs: dict[str, Any] = {
            "status_code": status,
            "ev_code": ev_code,
            "ev_message": ev_message,
            "body": response.content,
        }
        if status in (401, 403):
            raise EasyvistaAuthError(message, **kwargs)
        if status == 404:
            raise EasyvistaNotFound(message, **kwargs)
        if status == 400:
            raise EasyvistaValidationError(message, **kwargs)
        if status == 590:
            raise EasyvistaValidationError(
                f"{message} — EasyVista rejected the request (HTTP 590, code "
                f"{ev_code}); this usually means a missing mandatory field or an "
                f"invalid catalog reference for this catalog.",
                **kwargs,
            )
        if status == 429:
            raise EasyvistaRateLimitError(message, **kwargs)
        if status >= 500:
            raise EasyvistaServerError(message, **kwargs)
        raise EasyvistaError(message, **kwargs)

    @staticmethod
    def _extract_error(response: httpx.Response) -> tuple[str | None, str | None]:
        try:
            data = response.json()
        except ValueError:
            return None, None
        # EasyVista sometimes wraps the real error as a JSON string under "message".
        if isinstance(data, dict) and isinstance(data.get("message"), str):
            inner = data["message"].strip()
            if inner.startswith("{"):
                try:
                    data = {**data, **json.loads(inner)}
                except ValueError:
                    pass
        if not isinstance(data, dict):
            return None, None
        code = data.get("error_code") or data.get("code")
        message = data.get("error") or data.get("error_message") or data.get("message")
        return (
            str(code) if code is not None else None,
            str(message) if message is not None else None,
        )


class _RetryableResponse(Exception):  # internal control-flow signal
    """Raised internally to trigger a tenacity retry on a 429/5xx response."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"retryable status {response.status_code}")
        self.response = response


class Transport(BaseTransport):
    """The executor: runs a :class:`RequestSpec` against the configured instance.

    Blocking in the sync tree and coroutine-returning in the async tree, each
    backed by the matching ``httpx`` client. Same methods, same arguments,
    same results.
    """

    def __init__(self, config: EasyvistaConfig) -> None:
        super().__init__(config)
        self._client = httpx.AsyncClient(
            headers=self.headers(),
            auth=self.auth(),
            timeout=config.timeout,
            verify=config.verify_ssl,
        )

    async def __aenter__(self) -> Transport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _do_send(self, spec: RequestSpec) -> Any:
        response = await self._client.request(
            spec.method, self.build_url(spec.path), params=spec.params, json=spec.json
        )
        if self.is_retryable_status(response.status_code):
            raise _RetryableResponse(response)
        return self.finish(response)

    async def send(self, spec: RequestSpec) -> Any:
        retryer = AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((_RetryableResponse, httpx.TransportError)),
            reraise=True,
        )
        try:
            return await retryer(self._do_send, spec)
        except _RetryableResponse as exc:
            return self.finish(exc.response)
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc

    async def _do_get_bytes(self, path_or_url: str) -> bytes:
        response = await self._client.get(
            self.resolve_url(path_or_url), follow_redirects=True
        )
        if self.is_retryable_status(response.status_code):
            raise _RetryableResponse(response)
        if not response.is_success:
            self._raise_for_response(response)
        return response.content

    async def get_bytes(self, path_or_url: str) -> bytes:
        """GET raw bytes (an attachment), not JSON.

        :meth:`BaseTransport.finish` always calls ``response.json()``, so binary
        responses need their own path. This one reuses the same retry policy and
        the same error mapping, so a 403 on an attachment still surfaces as
        :class:`EasyvistaAuthError`. ``follow_redirects`` is on because a
        download URL commonly redirects to a signed location; httpx strips the
        ``Authorization`` header on a cross-origin redirect, so a foreign
        redirect degrades to an unauthenticated fetch rather than leaking the
        instance token.
        """
        retryer = AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((_RetryableResponse, httpx.TransportError)),
            reraise=True,
        )
        try:
            result: bytes = await retryer(self._do_get_bytes, path_or_url)
            return result
        except _RetryableResponse as exc:
            self._raise_for_response(exc.response)
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc

    async def _open_stream(
        self, path_or_url: str, chunk_size: int
    ) -> tuple[httpx.Response, AsyncIterator[bytes], list[bytes]]:
        """Open a streaming GET and take its first chunk, as one retryable unit.

        Returns the still-open response, its chunk iterator, and the first chunk
        wrapped in a list -- empty for an empty body, which is how "the body is
        over" is distinguished from "there is a chunk" without a sentinel.

        Taking the first chunk *here* rather than in :meth:`stream_bytes` is the
        whole point of this helper: everything inside it can be retried safely
        because nothing it produces has reached the caller yet, so restarting
        the request cannot deliver a byte twice. See :meth:`stream_bytes` for
        the policy that rests on it.

        Two details are forced by streaming. The response must be closed on
        every failure path, because an unread streaming response holds its
        connection open. And :meth:`BaseTransport._raise_for_response` reads
        ``.content``, which on a streaming response raises until the body has
        actually been read -- hence the read before each raise, which is what
        makes the error mapping identical to :meth:`get_bytes`.
        """
        response = await self._client.send(
            self._client.build_request("GET", self.resolve_url(path_or_url)),
            stream=True,
            follow_redirects=True,
        )
        try:
            if self.is_retryable_status(response.status_code):
                await response.aread()
                raise _RetryableResponse(response)
            if not response.is_success:
                await response.aread()
                self._raise_for_response(response)
            chunks = response.aiter_bytes(chunk_size)
            first: list[bytes] = []
            async for chunk in chunks:
                first.append(chunk)
                break
        except BaseException:
            await response.aclose()
            raise
        return response, chunks, first

    async def stream_bytes(
        self, path_or_url: str, *, chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE
    ) -> AsyncGenerator[bytes, None]:
        """GET raw bytes (an attachment) in chunks, never as one object.

        The streaming twin of :meth:`get_bytes`, and deliberately identical to
        it everywhere it can be: the same URL resolution through
        :meth:`BaseTransport.resolve_url` (so a URL outside the configured
        instance is refused here too), the same ``follow_redirects=True`` for
        the signed-location hop, the same attempt count and backoff, and the
        same error mapping -- a 403 on an attachment still raises
        :class:`EasyvistaAuthError`, and a 590 is still not retried. What
        differs is that the body is handed over in ``chunk_size`` pieces as it
        arrives, so a large attachment never has to exist in memory whole.

        **Retrying stops as soon as a byte reaches the caller.** A retryable
        status or a transport error while opening the download is retried like
        any other request, and the first chunk is fetched inside that retried
        unit so that a failure fetching it is still safe to restart. From that
        chunk onwards the request is committed: a transport failure raises
        :class:`EasyvistaConnectionError` instead of starting over, because
        starting over would re-deliver bytes the caller already has. Nothing
        resumes a partly consumed stream -- a caller that must survive a
        mid-stream failure has to decide for itself whether to discard what it
        collected and ask again, and this method will not make that choice by
        silently duplicating data.

        No request is made until iteration begins. This is a generator, so a
        refused URL -- and a non-positive ``chunk_size`` -- raises on the first
        step rather than at the call.
        """
        if chunk_size <= 0:
            # Guarded here rather than left to httpx, which raises from inside
            # its own ByteChunker: `chunk_size=0` surfaces as
            # "ValueError: range() arg 3 must not be zero" and a negative one as
            # "IndexError: list index out of range" -- both several frames below
            # this client, so a caller computing a size (`total // n`, a config
            # value that defaulted to 0) reads it as a library bug rather than
            # bad input.
            raise ValueError(f"chunk_size must be positive, got {chunk_size}")
        retryer = AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((_RetryableResponse, httpx.TransportError)),
            reraise=True,
        )
        opened: tuple[httpx.Response, AsyncIterator[bytes], list[bytes]]
        try:
            opened = await retryer(self._open_stream, path_or_url, chunk_size)
        except _RetryableResponse as exc:
            self._raise_for_response(exc.response)
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc
        response, chunks, first = opened
        try:
            for chunk in first:
                yield chunk
            async for chunk in chunks:
                yield chunk
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc
        finally:
            await response.aclose()
