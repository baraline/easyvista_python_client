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
from typing import Any, NoReturn
from urllib.parse import urlsplit

import httpx
from tenacity import (
    Retrying,
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
        hand that credential to whatever host the body named. The API is trusted
        to describe its own instance, not to redirect us off it.
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
        message = f"EasyVista request failed ({status}): {ev_message or response.text}"
        kwargs: dict[str, Any] = {
            "status_code": status,
            "ev_code": ev_code,
            "ev_message": ev_message,
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
        self._client = httpx.Client(
            headers=self.headers(),
            auth=self.auth(),
            timeout=config.timeout,
            verify=config.verify_ssl,
        )

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _do_send(self, spec: RequestSpec) -> Any:
        response = self._client.request(
            spec.method, self.build_url(spec.path), params=spec.params, json=spec.json
        )
        if self.is_retryable_status(response.status_code):
            raise _RetryableResponse(response)
        return self.finish(response)

    def send(self, spec: RequestSpec) -> Any:
        retryer = Retrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((_RetryableResponse, httpx.TransportError)),
            reraise=True,
        )
        try:
            return retryer(self._do_send, spec)
        except _RetryableResponse as exc:
            return self.finish(exc.response)
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc

    def _do_get_bytes(self, path_or_url: str) -> bytes:
        response = self._client.get(
            self.resolve_url(path_or_url), follow_redirects=True
        )
        if self.is_retryable_status(response.status_code):
            raise _RetryableResponse(response)
        if not response.is_success:
            self._raise_for_response(response)
        return response.content

    def get_bytes(self, path_or_url: str) -> bytes:
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
        retryer = Retrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((_RetryableResponse, httpx.TransportError)),
            reraise=True,
        )
        try:
            result: bytes = retryer(self._do_get_bytes, path_or_url)
            return result
        except _RetryableResponse as exc:
            self._raise_for_response(exc.response)
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc
