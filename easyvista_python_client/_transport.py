"""HTTP transport for the EasyVista client.

This module owns everything EasyVista-specific about talking to the API:
URL building, auth headers, error mapping, and the sync/async executors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx
from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import EasyvistaConfig
from .exceptions import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    EasyvistaValidationError,
)


@dataclass(frozen=True)
class RequestSpec:
    """A resource-relative HTTP request, independent of sync/async execution."""

    method: str
    path: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None


class BaseTransport:
    """Pure transport logic shared by the sync and async executors (no I/O)."""

    def __init__(self, config: EasyvistaConfig) -> None:
        self.config = config

    def build_url(self, path: str) -> str:
        return f"{self.config.api_root}/{path.lstrip('/')}"

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


class SyncTransport(BaseTransport):
    """Blocking executor backed by an ``httpx.Client``."""

    def __init__(self, config: EasyvistaConfig) -> None:
        super().__init__(config)
        self._client = httpx.Client(
            headers=self.headers(),
            auth=self.auth(),
            timeout=config.timeout,
            verify=config.verify_ssl,
        )

    def __enter__(self) -> SyncTransport:
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


class AsyncTransport(BaseTransport):
    """Native-async executor backed by an ``httpx.AsyncClient``."""

    def __init__(self, config: EasyvistaConfig) -> None:
        super().__init__(config)
        self._client = httpx.AsyncClient(
            headers=self.headers(),
            auth=self.auth(),
            timeout=config.timeout,
            verify=config.verify_ssl,
        )

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _do_asend(self, spec: RequestSpec) -> Any:
        response = await self._client.request(
            spec.method, self.build_url(spec.path), params=spec.params, json=spec.json
        )
        if self.is_retryable_status(response.status_code):
            raise _RetryableResponse(response)
        return self.finish(response)

    async def asend(self, spec: RequestSpec) -> Any:
        retryer = AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type((_RetryableResponse, httpx.TransportError)),
            reraise=True,
        )
        try:
            return await retryer(self._do_asend, spec)
        except _RetryableResponse as exc:
            return self.finish(exc.response)
        except httpx.TransportError as exc:
            raise EasyvistaConnectionError(f"connection failed: {exc}") from exc
