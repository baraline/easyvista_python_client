"""Connection configuration for the EasyVista client."""

from __future__ import annotations

import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ._version import __version__ as _package_version

#: ``User-Agent`` sent when :attr:`EasyvistaConfig.user_agent` is unset.
#:
#: No vendor documentation requires or constrains a User-Agent, so this
#: identifies the client in the instance's access log and nothing more. A caller
#: extending rather than replacing it can build on this value:
#: ``user_agent=f"{DEFAULT_USER_AGENT} my-app/1.4"``.
DEFAULT_USER_AGENT = f"easyvista-python-client/{_package_version}"


def reject_authorization(headers: Mapping[str, str], source: str) -> None:
    """Raise :class:`ValueError` if ``headers`` carries an ``Authorization`` key.

    Case-insensitively, because HTTP header names are. Shared by
    :class:`EasyvistaConfig` and
    :class:`~easyvista_python_client._transport.RequestSpec` so the rule is
    stated once: a header bag may override anything this client sets EXCEPT the
    credential. Silently shadowing ``config.token`` would send a secret the
    client cannot see, redact from a ``repr``, or rotate.
    """
    for key in headers:
        if key.lower() == "authorization":
            raise ValueError(
                f"{source} must not set {key!r}. The credential comes from "
                "config.token or config.login/password; setting it here would "
                "silently shadow it."
            )


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

    Several settings exist so a deployment that differs from the verified one
    needs no fork. None is a vendor-documented knob; they are client-side
    plumbing.

    ``extra_headers`` is merged over every header this client sends to the
    instance, so it overrides the JSON defaults and the User-Agent alike. It may
    **not** carry an ``Authorization`` key, in any casing -- that raises here, at
    construction, rather than silently shadowing ``token``. It is the insertion
    point for an API gateway's key (``Ocp-Apim-Subscription-Key``, ``X-Api-Key``)
    or a tenant selector. It is deliberately **not** sent to a host allow-listed
    by ``additional_download_hosts``, which is where a second secret would leak.

    ``user_agent`` replaces :data:`DEFAULT_USER_AGENT`. Some corporate WAFs in
    front of an ITSM tool throttle or block a generic client string, and a vendor
    asked to whitelist an integration needs something to whitelist.

    ``default_params`` are query parameters added to every JSON API request,
    **under** any the call itself sets. They are not applied to
    ``download_document`` / ``stream_document``: appending a query parameter to a
    signed download location is a plausible way to invalidate it, and it would be
    meaningless on a fetch that returns bytes. The motivating case is
    ``formatDate``, which the vendor lists as a query parameter (tier 1) without
    documenting its values -- so this config can send it, and makes no claim
    about what it does.

    ``additional_download_hosts`` opts specific **https** hosts in as attachment
    sources, for a deployment that serves attachments from a CDN or a vanity
    hostname rather than the instance itself. A fetch from one carries no
    credential and no ``extra_headers`` -- see
    :meth:`~easyvista_python_client._async._transport.BaseTransport.download_headers`.
    Hosts are normalised to lower case, and the instance's own origin is never
    treated as foreign, so listing it redundantly is inert.

    ``verify_ssl`` is passed to ``httpx`` unchanged, so besides ``True`` /
    ``False`` it accepts a CA-bundle path or a prepared :class:`ssl.SSLContext` --
    which is what a corporate private CA or a client certificate needs. Disabling
    verification is not the only answer to a private CA, and should not be
    reached for as though it were.
    """

    server: str
    account: str
    token: str | None = field(default=None, repr=False)
    login: str | None = None
    password: str | None = field(default=None, repr=False)
    timeout: float = 30.0
    max_retries: int = 0
    verify_ssl: bool | str | ssl.SSLContext = True
    default_max_rows: int = 100
    api_version: str = "v1"
    extra_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    user_agent: str | None = None
    default_params: Mapping[str, Any] = field(default_factory=dict)
    additional_download_hosts: frozenset[str] = frozenset()
    #: Extra ``datetime.strptime`` patterns to accept when reading a timestamp
    #: column, tried only after EasyVista's own ISO-8601 form fails. Empty by
    #: default, which is exactly today's behaviour.
    #:
    #: This exists because the read models refuse a timestamp they cannot parse
    #: rather than guessing an instant, and a search validates a whole page at
    #: once -- so on a deployment whose format differs, one column fails every
    #: record on the page. Naming the format is the way through that is not a
    #: fork. Nothing is guessed: a value matching none of the listed patterns
    #: still raises, and a pattern can never change how a real ISO-8601 stamp
    #: parses, because that is tried first. A pattern that yields a naive
    #: datetime is read as UTC.
    datetime_input_formats: tuple[str, ...] = ()
    _server_normalized: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_server_normalized", self.server.rstrip("/"))
        if not self.token and not (self.login and self.password):
            raise ValueError(
                "An EasyVista credential is required: pass token=... or "
                "login=... and password=..."
            )
        reject_authorization(self.extra_headers, "EasyvistaConfig.extra_headers")
        # Copy, then freeze. A frozen dataclass holding a live dict is not
        # frozen: the caller's dict stays aliased, and the attribute stays
        # writable through it.
        object.__setattr__(
            self, "extra_headers", MappingProxyType(dict(self.extra_headers))
        )
        object.__setattr__(
            self, "default_params", MappingProxyType(dict(self.default_params))
        )
        object.__setattr__(
            self,
            "additional_download_hosts",
            frozenset(
                host.strip().lower()
                for host in self.additional_download_hosts
                if host.strip()
            ),
        )

    def __hash__(self) -> int:
        """Hash the scalar identity only, so a config stays usable as a key.

        ``extra_headers`` and ``default_params`` are mappings, and the hash
        ``@dataclass`` would generate over every field raises ``TypeError`` the
        moment either is non-empty. Two configs differing only in those mappings
        therefore collide; that is allowed -- the contract is that equal objects
        hash equal, not that unequal ones differ -- and ``__eq__``, which does
        compare every field, still tells them apart.
        """
        return hash(
            (
                self.server,
                self.account,
                self.token,
                self.login,
                self.password,
                self.api_version,
            )
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

        A convenience for a 12-factor deployment, not the primary way to
        configure this package: **every** setting is a constructor argument, and
        for a pip-installed library that is the better route. Reach for this when
        the process is already configured through the environment.

        Reads ``EASYVISTA_URL`` (or ``EASYVISTA_SERVER``), ``EASYVISTA_ACCOUNT``,
        then ``EASYVISTA_TOKEN`` or ``EASYVISTA_TOKEN_FILE``, else
        ``EASYVISTA_LOGIN`` / ``EASYVISTA_PASSWORD``.

        ``EASYVISTA_ACCOUNT`` is the instance identifier path segment, not a
        username -- see the class docstring. ``EASYVISTA_LOGIN`` is the username.

        It deliberately reads none of the per-deployment adaptation settings --
        ``extra_headers``, ``user_agent``, ``default_params``,
        ``additional_download_hosts``, or a non-boolean ``verify_ssl``. Those
        describe how one deployment differs from another, and an environment
        variable is the wrong home for them; pass them to the constructor. The
        variable names are fixed, so two instances in one process (production and
        preproduction, say) want two explicit ``EasyvistaConfig`` objects rather
        than two environments.
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
