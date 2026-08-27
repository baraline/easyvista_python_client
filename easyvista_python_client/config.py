"""Connection configuration for the EasyVista client."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EasyvistaConfig:
    """Immutable connection settings.

    Provide either ``token`` (Bearer) or ``login`` + ``password`` (Basic).

    ``account`` is **not a user account**, despite sitting next to ``login`` and
    ``password``. It is the EasyVista *instance* identifier -- a number such as
    ``"50004"`` -- that forms the final path segment of :attr:`api_root`,
    ``https://host/api/{version}/{account}``. Every request is routed through it,
    but nothing authenticates with it: authentication is ``token``, or ``login``
    plus ``password``. The two are unrelated values and normally differ.

    ``server`` is the bare instance host, e.g. ``"https://my.easyvista.com"``. A
    trailing slash is stripped; do not append the ``/api/...`` path, which
    :attr:`api_root` builds from ``api_version`` and ``account``.
    """

    server: str
    account: str
    token: str | None = field(default=None, repr=False)
    login: str | None = None
    password: str | None = field(default=None, repr=False)
    timeout: float = 30.0
    max_retries: int = 0
    verify_ssl: bool = True
    default_max_rows: int = 100
    api_version: str = "v1"
    _server_normalized: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_server_normalized", self.server.rstrip("/"))
        if not self.token and not (self.login and self.password):
            raise ValueError(
                "An EasyVista credential is required: pass token=... or "
                "login=... and password=..."
            )

    @property
    def api_root(self) -> str:
        return f"{self._server_normalized}/api/{self.api_version}/{self.account}"

    @property
    def uses_basic_auth(self) -> bool:
        return self.token is None

    @classmethod
    def from_env(cls) -> EasyvistaConfig:
        """Build config from environment variables.

        Reads ``EASYVISTA_URL`` (or ``EASYVISTA_SERVER``), ``EASYVISTA_ACCOUNT``,
        then ``EASYVISTA_TOKEN`` or ``EASYVISTA_TOKEN_FILE``, else
        ``EASYVISTA_LOGIN`` / ``EASYVISTA_PASSWORD``.

        ``EASYVISTA_ACCOUNT`` is the instance identifier path segment, not a
        username -- see the class docstring. ``EASYVISTA_LOGIN`` is the username.
        """
        server = os.environ.get("EASYVISTA_URL") or os.environ.get("EASYVISTA_SERVER")
        account = os.environ.get("EASYVISTA_ACCOUNT")
        if not server or not account:
            raise ValueError(
                "EASYVISTA_URL (or EASYVISTA_SERVER) and EASYVISTA_ACCOUNT must be set."
            )

        token = os.environ.get("EASYVISTA_TOKEN")
        token_file = os.environ.get("EASYVISTA_TOKEN_FILE")
        if not token and token_file:
            with open(token_file, encoding="utf-8") as handle:
                token = handle.read().strip()

        return cls(
            server=server,
            account=account,
            token=token,
            login=os.environ.get("EASYVISTA_LOGIN"),
            password=os.environ.get("EASYVISTA_PASSWORD"),
        )
