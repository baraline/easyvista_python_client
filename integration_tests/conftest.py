"""Fixtures for live integration tests.

These tests call a real EasyVista instance, so they live apart from the unit
tests inside the package and are **never run in CI** — CI runs
``pytest -m "not integration"``. You supply your own instance: every test here
skips cleanly when credentials are absent, so a checkout with no ``secrets/``
and no ``EASYVISTA_TEST_*`` environment simply skips the suite rather than
failing it.

They are not read-only. A full run creates and closes **21 tickets** (one shared
``rich_ticket``, two ``probe_tickets``, and 18 from ``ticket_factory``), plus 8
actions, 5 document uploads and **6 to 14 ticket updates** (4 fixed PUTs --
title, rename, description, external reference -- plus the ``IMPACT_ID`` /
``OWNER_ID`` read-back in the ticket-identity test, which tries up to 5
candidate values per column and stops at the first the instance accepts, some
of which it may reject outright); ``test_live_smoke`` additionally issues one
create the server is *expected to reject*, so no ticket persists from it. Every
created ticket is registered for cleanup before it is asserted on, and closed
in teardown. Point them at a preprod/test instance, never production.

Credentials resolve from an uppercase env var first, then a lowercase file under
``secrets/``:

    url     <- EASYVISTA_TEST_URL     | secrets/easyvista_test_url
    account <- EASYVISTA_TEST_ACCOUNT | secrets/easyvista_test_account
    token   <- EASYVISTA_TEST_TOKEN   | secrets/easyvista_test_token

``account`` is **not a login**. It is the EasyVista instance identifier that
forms the ``{account}`` path segment of ``https://host/api/{version}/{account}``
-- a number such as ``50004`` -- and it feeds ``EasyvistaConfig.account``.
Nothing authenticates with it. Until 2026-08-25 it was spelled
``EASYVISTA_TEST_USER`` / ``secrets/easyvista_test_user``, which read as a
username and never was one; that name is now **refused** rather than quietly
accepted, so a stale copy cannot resurrect the confusion (see
``_reject_legacy_account_name``).

Eight further per-instance values resolve the same way (env var, else the
matching lowercase ``secrets/`` file), each gating only the tests that need it.
The first six make up ``live_write_config``, which every ticket-creating test
depends on (``sample_catalog_code`` also takes ``catalog_code`` on its own); the
last two gate ``live_action_config`` alone, so an instance with no action type
configured still runs the write tests:

    catalog_code   <- EASYVISTA_TEST_CATALOG_CODE
    origin         <- EASYVISTA_TEST_ORIGIN
    department_id  <- EASYVISTA_TEST_DEPARTMENT_ID
    urgency_id     <- EASYVISTA_TEST_URGENCY_ID
    impact_id      <- EASYVISTA_TEST_IMPACT_ID
    status_guid    <- EASYVISTA_TEST_STATUS_GUID
    action_type_id <- EASYVISTA_TEST_ACTION_TYPE_ID
    group_id       <- EASYVISTA_TEST_GROUP_ID

Auth is **Bearer** (the ``token`` value) — confirmed against the live preprod
instance, and it is the *only* credential that authenticates anything. The
``url`` value is normally the **full API root** (it already ends in
``/api/v1/{account}``), so we split it back into ``server`` + ``account`` so
``EasyvistaConfig.api_root`` reconstructs it exactly — and in that case the
``account`` credential is never read at all. It is consulted only when ``url``
is a bare host with no ``/api/`` segment.

The secret values are loaded by this test process at runtime and never printed.
Nor is live instance content: ``_force_short_traceback`` strips the frame-
argument block from every failure in this directory, which is what stops a test
spilling the fixtures it was handed. See ``_assertions.py`` for the other two
layers of that guarantee and why all three are needed.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import pytest

from easyvista_python_client import (
    EasyvistaAuthError,
    EasyvistaClient,
    EasyvistaConfig,
    EasyvistaConnectionError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    PostRequest,
    ev_equals_filter,
    is_safe_ev_value,
)

_HERE = Path(__file__).resolve().parent


def _force_short_traceback(item: pytest.Item) -> None:
    """Render ``item``'s failures without the frame-argument block (P2).

    This is the leak no assertion style can close. pytest renders a *long*
    traceback entry together with that frame's arguments, and a test function's
    arguments are its fixtures -- so ``test_a_returned_field_is_not_searchable(
    live_client, ticket_with_catalog, ...)`` prints ``ticket_with_catalog =
    {...the entire live ticket payload...}`` above the message on **any**
    failure, including an unexpected exception that never reached an assert.
    Careful asserts do not help: the reprs come from the traceback, not from the
    assertion rewriter. Measured, not assumed.

    The short style omits that block and keeps file, line, failing statement and
    message -- enough, because every message in this suite names a field rather
    than a value. Scoped per item so the unit suite keeps its long tracebacks;
    forcing it here rather than asking callers for ``--tb=short`` keeps the
    guarantee structural, the same reason the marker below is applied by
    location.

    ``--showlocals`` and ``--full-trace`` both defeat a short style on their own
    (measured: each puts the reprs back), so they are neutralized for the
    duration of this one report and restored immediately -- the unit suite still
    honours them.

    Patched at ``_repr_failure_py`` rather than the public ``repr_failure``
    because pytest consults the public name ONLY for the call phase
    (``_pytest/reports.py:262-263``) and calls this one directly for setup and
    teardown (``:266-267``). A session fixture that creates a live record does its
    work in setup, so patching the public name left exactly the credential-bearing
    frames uncovered -- measured on 2026-08-03, when a timed-out create printed its
    whole request payload. One patch here covers all three phases, because both
    ``Function.repr_failure`` and ``Node.repr_failure`` delegate to this method and
    an instance attribute shadows it.
    """

    original = item._repr_failure_py

    def _repr_failure_py(excinfo, style=None, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        option = item.config.option
        saved = (
            getattr(option, "showlocals", False),
            getattr(option, "fulltrace", False),
        )
        option.showlocals = False
        option.fulltrace = False
        try:
            return original(excinfo, style="short")
        finally:
            option.showlocals, option.fulltrace = saved

    item._repr_failure_py = _repr_failure_py  # type: ignore[method-assign]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply both directory-wide guarantees to every test **in this directory**.

    Two things, each structural rather than remembered: the ``integration``
    marker (below) and the redacted traceback (``_force_short_traceback``). Both
    are applied by location for the same reason -- a new module that forgets a
    ``pytestmark`` or writes a careless assert still gets them.

    CI's ``pytest -m "not integration"`` is the guarantee that nothing here ever
    calls a live instance from a runner. Leaving that to a per-module
    ``pytestmark`` makes the guarantee a convention: a new file that forgets it —
    or misspells it — is collected and run, and ``--strict-markers`` does not
    save you (in ``addopts`` pytest 9 silently ignores it — verified). Marking by
    location makes the guarantee structural, so it cannot be forgotten.

    The path check is essential, not defensive: pytest hands this hook **every**
    collected item in the session, not only the ones under this conftest. Without
    it this would mark the entire unit suite ``integration`` and CI would
    deselect all of it.
    """
    for item in items:
        path = getattr(item, "path", None)
        if path is not None and _HERE in Path(path).resolve().parents:
            item.add_marker(pytest.mark.integration)
            _force_short_traceback(item)


# secrets/ lives at the repo root: integration_tests/conftest.py -> parents[1].
_SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"

# Bounded so the Consigne fixture cannot walk a large instance's whole directory.
CONSIGNE_SCAN_LIMIT = 50

# A transient network fault must not read as a defect, so reads, PUTs and closes
# get three attempts with the transport's exponential backoff (0.5s, 1s, capped
# at 10s). Non-idempotent POSTs deliberately do NOT: see live_write_client.
LIVE_TIMEOUT = 30.0
LIVE_MAX_RETRIES = 2

# A create that timed out (LIVE_TIMEOUT) may still be in flight on the server --
# the read timing out proves nothing about whether the write landed. Searching
# for it immediately maximises the odds of observing a pre-commit state: the
# search is honoured, finds nothing (honestly, at that instant), and licenses a
# re-send. If the original request then commits microseconds or seconds later,
# the result is two tickets sharing one nonce title, one of them an orphan
# nothing will ever close. This delay narrows that window; it does not close
# it -- see the residual documented on `_create_tracked` and `_adopt_by_title`.
_RECONCILE_DELAY = 15.0


# Retired 2026-08-25. The value is the API-root ``{account}`` path segment, not a
# login, and the old spelling said otherwise. Accepting it as a silent fallback
# would re-admit the exact confusion the rename removed, so it is refused with a
# message naming its replacement. Only names are printed, never values (P2).
_LEGACY_ACCOUNT_ENV = "EASYVISTA_TEST_USER"
_LEGACY_ACCOUNT_FILE = "easyvista_test_user"


def _reject_legacy_account_name() -> None:
    """Fail loudly when the pre-rename account credential is still configured."""
    stale: list[str] = []
    value = os.environ.get(_LEGACY_ACCOUNT_ENV)
    if value and value.strip():
        stale.append("the " + _LEGACY_ACCOUNT_ENV + " environment variable")
    if (_SECRETS_DIR / _LEGACY_ACCOUNT_FILE).is_file():
        stale.append("secrets/" + _LEGACY_ACCOUNT_FILE)
    if stale:
        verb = "is" if len(stale) == 1 else "are"
        pytest.fail(
            " and ".join(stale) + " " + verb + " still set. That name was retired on "
            "2026-08-25 and is no longer read: the value is the EasyVista "
            "account -- the instance id in https://host/api/{version}/{account} "
            "-- and never a login. Rename it to EASYVISTA_TEST_ACCOUNT / "
            "secrets/easyvista_test_account.",
            pytrace=False,
        )


def _resolve(env_names: tuple[str, ...], filename: str) -> str | None:
    for name in env_names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    path = _SECRETS_DIR / filename
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


@pytest.fixture(scope="session")
def live_config() -> EasyvistaConfig:
    url = _resolve(("EASYVISTA_TEST_URL",), "easyvista_test_url")
    token = _resolve(("EASYVISTA_TEST_TOKEN",), "easyvista_test_token")
    if not url or not token:
        pytest.skip(
            "live credentials unavailable (need url + token; set EASYVISTA_TEST_* "
            "env vars or add secrets/easyvista_test_* files)"
        )
    # Ordered after the skip so an unconfigured checkout stays offline and green:
    # with no url/token there is no live run for a stale name to mislead.
    _reject_legacy_account_name()
    account = _resolve(("EASYVISTA_TEST_ACCOUNT",), "easyvista_test_account")

    root = url.rstrip("/")
    if "/api/" in root:
        # url is the full API root, e.g. https://host/api/v1/12345 -> split it.
        server, _, rest = root.partition("/api/")
        version, _, account_tail = rest.partition("/")
        account = account_tail.split("/")[0]
        if not account:
            # Names the shape expected, never the configured URL: this module
            # promises the secret values are never printed, and a skip reason is
            # rendered output like any other (P2).
            pytest.skip(
                "could not parse an account from the configured API root URL "
                "(expected .../api/{version}/{account})"
            )
        return EasyvistaConfig(
            server=server,
            account=account,
            token=token,
            api_version=version,
            timeout=LIVE_TIMEOUT,
            max_retries=LIVE_MAX_RETRIES,
        )
    # url is a bare host, so the account cannot be parsed out of it.
    if not account:
        pytest.skip(
            "URL has no /api/ segment, so EASYVISTA_TEST_ACCOUNT (or "
            "secrets/easyvista_test_account) is required -- the instance id in "
            "https://host/api/{version}/{account}, not a login"
        )
    return EasyvistaConfig(
        server=root,
        account=account,
        token=token,
        timeout=LIVE_TIMEOUT,
        max_retries=LIVE_MAX_RETRIES,
    )


@pytest.fixture(scope="session")
def live_client(live_config: EasyvistaConfig) -> Iterator[EasyvistaClient]:
    with EasyvistaClient(live_config) as client:
        yield client


@pytest.fixture(scope="session")
def live_write_client(live_config: EasyvistaConfig) -> Iterator[EasyvistaClient]:
    """A ZERO-retry client, for the POSTs that duplicate when retried.

    ``retry_if_exception_type`` in the transport is method-blind, so it cannot
    tell a safe GET from a ``create_action``. Rather than weaken the retry that
    makes reads trustworthy, the non-idempotent verbs get their own client with
    retries off: ``create_ticket``, ``create_action`` and ``add_document``.
    ``update_ticket`` (fixed-value PUTs) and ``close_ticket`` are idempotent and
    stay on ``live_client``.

    ``replace`` on a frozen dataclass re-runs ``__post_init__``, which is required
    because ``_server_normalized`` is ``field(init=False)``.
    """
    with EasyvistaClient(replace(live_config, max_retries=0)) as client:
        yield client


@pytest.fixture(scope="session")
def sample_rfc(live_client: EasyvistaClient) -> str:
    """An RFC number from the live instance, for ticket sub-resource reads."""
    result = live_client.search_tickets(max_rows=1)
    if not result.records:
        pytest.skip("no tickets on the live instance to exercise ticket reads")
    rfc = result.records[0].rfc_number
    if not rfc:
        pytest.skip("live ticket returned without an RFC_NUMBER")
    return rfc


@pytest.fixture(scope="session")
def sample_department_id(live_client: EasyvistaClient) -> int:
    """A department id from the live instance, for directory reads."""
    result = live_client.search_departments(max_rows=1)
    if not result.records or result.records[0].department_id is None:
        pytest.skip("no departments on the live instance to exercise directory reads")
    return result.records[0].department_id


@pytest.fixture(scope="session")
def sample_department_code(live_client: EasyvistaClient) -> str:
    """A real DEPARTMENT_CODE from the live instance, for search-syntax probes."""
    result = live_client.search_departments(max_rows=25)
    for dept in result.records:
        code = dept.department_code
        if code and code.strip() and len(code.strip()) >= 3:
            return code.strip()
    pytest.skip("no department with a usable DEPARTMENT_CODE on the live instance")


@pytest.fixture(scope="session")
def sample_catalog_code() -> str:
    """A catalog code valid on the live instance.

    Resolved at runtime, never hardcoded: a test that needs a *valid* catalog to
    isolate a different failure cannot use a made-up one, and the real code must
    not live in a tracked file.
    """
    value = _resolve(("EASYVISTA_TEST_CATALOG_CODE",), "easyvista_test_catalog_code")
    if not value:
        pytest.skip(
            "needs EASYVISTA_TEST_CATALOG_CODE (or secrets/easyvista_test_catalog_code)"
        )
    return value


@pytest.fixture(scope="session")
def live_write_config() -> dict[str, str]:
    """Instance-specific fields needed to create and close probe tickets.

    Skips unless every value is configured: these are per-instance and must not
    be hardcoded into a tracked test.
    """
    keys = {
        "catalog_code": ("EASYVISTA_TEST_CATALOG_CODE", "easyvista_test_catalog_code"),
        "origin": ("EASYVISTA_TEST_ORIGIN", "easyvista_test_origin"),
        "department_id": (
            "EASYVISTA_TEST_DEPARTMENT_ID",
            "easyvista_test_department_id",
        ),
        "urgency_id": ("EASYVISTA_TEST_URGENCY_ID", "easyvista_test_urgency_id"),
        "impact_id": ("EASYVISTA_TEST_IMPACT_ID", "easyvista_test_impact_id"),
        "status_guid": ("EASYVISTA_TEST_STATUS_GUID", "easyvista_test_status_guid"),
    }
    resolved: dict[str, str] = {}
    for name, (env, filename) in keys.items():
        value = _resolve((env,), filename)
        if not value:
            pytest.skip(f"write probes need {env} (or secrets/{filename})")
        resolved[name] = value
    return resolved


# Three attempts, and a re-send is licensed ONLY by an honoured, empty
# reconciliation search taken _RECONCILE_DELAY after the timeout. That is
# evidence the previous attempt had not committed AS OF that search -- not
# proof it never will. A residual race remains: see `_create_tracked` and
# `_adopt_by_title` for the orphan it can still produce.
_CREATE_ATTEMPTS = 3


class _InconclusiveCreate(RuntimeError):
    """A create whose outcome could not be established, so it must NOT be re-sent.

    Deliberately distinct from an ordinary failure. Re-sending risks a duplicate
    ticket the suite never learns the RFC of -- an orphan on someone else's
    instance -- and that is worse than stopping loudly.
    """


def _adopt_by_title(search_client: EasyvistaClient, title: str) -> str | None:
    """Return the RFC of the ticket titled exactly ``title``, or ``None`` if
    the search was honoured and found none AS OF THE MOMENT IT RAN.

    That ``None`` is a point-in-time observation, not proof of permanent
    absence: it licenses the caller to re-send (see ``_create_tracked``,
    which pairs it with ``_RECONCILE_DELAY`` to narrow, not close, the window),
    but a create still in flight when this search ran can still commit
    afterward -- an orphan this function has no way to detect, because by
    construction it never learns the RFC of a ticket that did not exist yet
    when it searched.

    Raises :class:`_InconclusiveCreate` when the question cannot be answered, which
    is the only safe third outcome: on this API a condition it cannot honour is
    silently dropped and **every** record comes back, so "no answer" and "no match"
    must never collapse into each other. The honoured-search check below catches
    exactly that shape: a server-reported total that disagrees with the number of
    rows actually returned, which is what a genuine whole-table response looks
    like. It does NOT catch every way an empty answer could be spurious -- a bare
    JSON ``null`` or ``[]`` search body would parse to zero records with no
    reported total, which folds into ``total_record_count == len(records) == 0``
    indistinguishably from a real honoured-and-empty search. This API has never
    been observed to return either shape, so that gap is accepted rather than
    guarded against; revisit if it ever is.
    """
    __tracebackhide__ = True
    if not is_safe_ev_value(title):
        raise _InconclusiveCreate(
            "the intended title contains a double quote, which EasyVista cannot "
            "match in any rendering (verified live), so this create cannot be "
            "reconciled"
        )
    search = ev_equals_filter("TITLE", title)
    if search is None:
        raise _InconclusiveCreate("the intended title is blank")
    try:
        # fields= is REQUIRED, not optional: the default list projection returns
        # the TITLE key present but EMPTY (measured live -- 400 tickets scanned via
        # a plain search_tickets, zero with a populated title), so without this
        # projection `row.title == title` below can never be true and every
        # reconciliation would be inconclusive. See
        # test_title_search_requires_the_fields_projection_to_return_a_value in
        # test_live_search_syntax.py for the live regression guard.
        result = search_client.search_tickets(
            search=search, max_rows=2, fields=["RFC_NUMBER", "TITLE"]
        )
    except Exception as exc:
        # Broad on purpose: an unmodelled failure (e.g. a response body that fails
        # the client's own pydantic validation) is exactly as unreconcilable as a
        # transport error -- every unknown failure must become a no-resend stop,
        # which is this helper's whole thesis. `from None`, never `from exc`:
        # EasyvistaError.__str__ interpolates server prose and a pydantic
        # ValidationError embeds the offending input_value, and pytest's chain
        # repr renders __cause__/__context__ even under --tb=short (P2).
        raise _InconclusiveCreate(
            f"the reconciliation search itself failed ({type(exc).__name__})"
        ) from None

    returned = len(result.records)
    if result.total_record_count != returned:
        raise _InconclusiveCreate(
            f"the TITLE condition was dropped: {result.total_record_count} total "
            f"against {returned} returned rows, i.e. the whole table"
        )
    if returned > 2:
        raise _InconclusiveCreate(f"reconciliation returned {returned} rows")

    matches = [row for row in result.records if row.title == title]
    if not matches:
        if result.records:
            raise _InconclusiveCreate(
                f"reconciliation returned {returned} row(s) whose TITLE is not the "
                f"intended one"
            )
        return None
    if len(matches) > 1:
        # Two rows can legitimately share one exact title (max_rows=2 admits it).
        # Adopting matches[0] would silently orphan the other -- the same class of
        # bug this whole helper exists to close, just one row later.
        raise _InconclusiveCreate(
            f"reconciliation matched {len(matches)} rows with the intended title"
        )
    rfc = matches[0].rfc_number
    if not rfc:
        raise _InconclusiveCreate("the reconciled row carries no RFC_NUMBER")
    return rfc


def _create_tracked(
    cfg: dict[str, str],
    tracked: list[str],
    *,
    write_client: EasyvistaClient,
    search_client: EasyvistaClient,
    title: str,
    description: str,
) -> str:
    """Create one ticket and register its RFC in ``tracked`` the instant it is known.

    The append happens BEFORE any assertion, which is the whole point: the old
    order asserted on the RFC first, so a create that committed server-side but
    returned no usable body left a ticket nothing would ever close.

    ``write_client`` and ``search_client`` are keyword-only on purpose: both
    parameters are ``EasyvistaClient``, so a positional swap type-checks and
    passes review, and would route every create through the *retrying* client
    -- reintroducing the duplicate-POST hazard this whole helper exists to
    close. A keyword makes the swap a name, not a position, and is un-writable
    by accident.

    ``write_client`` must be the zero-retry client. This function does its own
    retrying, and a re-send is licensed only by an *honoured, empty* result from
    ``_adopt_by_title`` taken ``_RECONCILE_DELAY`` after the timeout -- that is
    evidence the previous attempt had not committed AS OF that search, not proof
    it never will. A create that commits AFTER the search observed its absence
    still yields an orphan: a real, uncleaned ticket with a byte-identical nonce
    title, indistinguishable server-side from the one this function goes on to
    track. ``_RECONCILE_DELAY`` narrows that window; it does not close it. A
    deterministic rejection (``EasyvistaValidationError``, HTTP 590) is not a
    transient and propagates untouched.
    """
    for _attempt in range(_CREATE_ATTEMPTS):
        try:
            ticket = write_client.create_ticket(
                PostRequest(
                    catalog_code=cfg["catalog_code"],
                    title=title,
                    description=description,
                    origin=int(cfg["origin"]),
                    department_id=int(cfg["department_id"]),
                    urgency_id=int(cfg["urgency_id"]),
                    impact_id=int(cfg["impact_id"]),
                )
            )
        except (
            EasyvistaConnectionError,
            EasyvistaRateLimitError,
            EasyvistaServerError,
        ):
            pass  # the request may or may not have committed; never re-send blind
        else:
            rfc = ticket.rfc_number
            if rfc:
                tracked.append(rfc)
                return rfc

        # Reached on every path that doesn't already have a trackable RFC in
        # hand -- not only the "timed out, might still be in flight" case
        # _RECONCILE_DELAY exists for. It also fires when create_ticket
        # returned successfully but with an empty body (the ticket already
        # committed; there is no in-flight ambiguity left to wait out), when
        # the title is unquotable and _adopt_by_title is about to raise
        # without ever searching (probe_tickets' second ticket), and once
        # more on the final attempt, immediately before the terminal
        # AssertionError below. Worst case is _CREATE_ATTEMPTS *
        # _RECONCILE_DELAY (45s) of dead wait. Kept uniform rather than
        # skipped on those paths: they are the rare, already-degraded cases
        # (a failure already happened, or the loop is already ending), and
        # branching this call per-path is complexity this trade is not worth
        # paying for on an already-slow, live-only code path.
        time.sleep(_RECONCILE_DELAY)
        adopted = _adopt_by_title(search_client, title)
        if adopted is not None:
            tracked.append(adopted)
            return adopted
        # The search was honoured and found nothing AS OF THIS MOMENT. It does
        # not prove the earlier attempt will never commit -- see the docstring's
        # residual-race note -- only that re-sending now is the intended trade.

    raise AssertionError(
        f"create_ticket produced no usable ticket in {_CREATE_ATTEMPTS} attempts"
    )


def _close_tracked(
    client: EasyvistaClient, cfg: dict[str, str], tracked: list[str], reason: str
) -> None:
    """Close every RFC in ``tracked``, attempting all of them regardless of failures.

    Error records carry the exception's TYPE and status code, never the exception
    object: ``str(exc)`` is the transport's message, which interpolates server prose
    this suite did not author (P2).
    """
    errors: list[tuple[str, str, int | None]] = []
    for rfc in tracked:
        try:
            client.close_ticket(
                rfc,
                status_guid=cfg["status_guid"],
                delete_actions=1,
                comment=reason,
            )
        except EasyvistaError as exc:
            errors.append((rfc, type(exc).__name__, exc.status_code))
        except Exception as exc:  # every ticket must be attempted regardless
            errors.append((rfc, type(exc).__name__, None))
    if errors:
        raise RuntimeError(f"failed to close ticket(s): {errors}")


@pytest.fixture(scope="session")
def probe_tickets(
    live_client, live_write_client, live_write_config
) -> Iterator[tuple[str, str, str]]:
    """Create two probe tickets; always close both.

    Yields (nonce, rfc_control, rfc_quoted):
      - control ticket title: ``EVCLI{nonce}A``            (quote-free)
      - quoted  ticket title: ``EVCLI{nonce}B 22" monitor`` (contains a literal ")

    The quoted title is unreconcilable by construction -- EasyVista cannot match a
    literal ``"`` in any rendering -- so an inconclusive create for THAT ticket
    stops loudly rather than risking a duplicate. The control ticket is created
    first, so it is tracked and closed either way.
    """
    cfg = live_write_config
    nonce = uuid.uuid4().hex[:10].upper()
    description = "search-syntax characterization probe; safe to close"
    tracked: list[str] = []
    try:
        rfc_control = _create_tracked(
            cfg,
            tracked,
            write_client=live_write_client,
            search_client=live_client,
            title=f"EVCLI{nonce}A",
            description=description,
        )
        rfc_quoted = _create_tracked(
            cfg,
            tracked,
            write_client=live_write_client,
            search_client=live_client,
            title=f'EVCLI{nonce}B 22" monitor',
            description=description,
        )
        yield nonce, rfc_control, rfc_quoted
    finally:
        _close_tracked(live_client, cfg, tracked, "probe cleanup")


class RichTicket(NamedTuple):
    """The shared read-only ticket: its RFC plus the synthetic content it carries.

    Consumers need the authored title and description to assert round-trips
    against values this suite wrote (design principle P2), so they travel with
    the RFC rather than being re-declared in every module.
    """

    rfc: str
    title: str
    description: str


@pytest.fixture(scope="session")
def live_action_config() -> dict[str, str]:
    """Instance-specific ids needed to CREATE an action.

    Deliberately separate from ``live_write_config``: that fixture gates ticket
    creation for the whole suite (``probe_tickets`` included), and folding these
    two keys into it would skip every write test on an instance that has simply
    not configured an action type. Only the action-creating tests depend on this.
    """
    keys = {
        "action_type_id": (
            "EASYVISTA_TEST_ACTION_TYPE_ID",
            "easyvista_test_action_type_id",
        ),
        "group_id": ("EASYVISTA_TEST_GROUP_ID", "easyvista_test_group_id"),
    }
    resolved: dict[str, str] = {}
    for name, (env, filename) in keys.items():
        value = _resolve((env,), filename)
        if not value:
            pytest.skip(f"action tests need {env} (or secrets/{filename})")
        resolved[name] = value
    return resolved


@pytest.fixture(scope="session")
def rich_ticket(
    live_client, live_write_client, live_write_config
) -> Iterator[RichTicket]:
    """One ticket created with every settable field; closed in teardown.

    All-synthetic content, so any round-trip assertion compares our own strings
    against themselves. Session-scoped and treated as read-only by its consumers:
    a test that MUTATES a ticket takes a fresh one from ``ticket_factory`` instead,
    so a title-update test can never invalidate a title-read test regardless of
    collection order.

    The create sits INSIDE the ``try`` and reconciles a lost response, because this
    fixture's setup exception is cached by pytest and re-raised to all 17 of its
    consumers -- one transient used to end the session's write coverage.
    """
    cfg = live_write_config
    nonce = uuid.uuid4().hex[:10].upper()
    title = f"EVCLI{nonce}RICH"
    description = f"EVCLI{nonce} capability-suite fixture ticket; safe to close"
    tracked: list[str] = []
    try:
        rfc = _create_tracked(
            cfg,
            tracked,
            write_client=live_write_client,
            search_client=live_client,
            title=title,
            description=description,
        )
        yield RichTicket(rfc=rfc, title=title, description=description)
    finally:
        _close_tracked(live_client, cfg, tracked, "fixture cleanup")


@pytest.fixture
def ticket_factory(
    live_client, live_write_client, live_write_config
) -> Iterator[Callable[[], str]]:
    """Create fresh tickets for mutating tests; close every one in teardown.

    Returns a zero-argument callable that creates one ticket and returns its RFC.
    Teardown attempts EVERY created ticket regardless of individual failures and
    raises once at the end, so one failed close never orphans the rest.
    """
    cfg = live_write_config
    tracked: list[str] = []

    def _make() -> str:
        nonce = uuid.uuid4().hex[:10].upper()
        return _create_tracked(
            cfg,
            tracked,
            write_client=live_write_client,
            search_client=live_client,
            title=f"EVCLI{nonce}",
            description=f"EVCLI{nonce} capability-suite ticket; safe to close",
        )

    try:
        yield _make
    finally:
        _close_tracked(live_client, cfg, tracked, "factory cleanup")


def _is_per_record_gap(exc: EasyvistaError) -> bool:
    """Whether ``exc`` means "this record has no memo" rather than a real fault.

    403 is profile-gating on the memo endpoint and 404 is a missing memo; both are
    facts about the record, so the scan continues (design principle P1). **401 is
    not**, and the distinction cannot be made on the exception class:
    ``_transport.py`` raises ``EasyvistaAuthError`` for ``status in (401, 403)``,
    so catching the class turns an expired mid-run token into "this instance has no
    Consigne data" after scanning fifty departments.
    """
    if isinstance(exc, EasyvistaNotFound):
        return True
    return isinstance(exc, EasyvistaAuthError) and exc.status_code == 403


@pytest.fixture(scope="session")
def consigne_department_id(live_client) -> int:
    """A department id whose note (``COMMENT_DEPARTMENT``) is non-empty.

    Yields the **id only** -- never the note text, never the department label
    (design principle P2). Skips when the scan finds none, which is a fact about
    the instance rather than a defect (P1).
    """
    scanned = 0
    for dept in live_client.iter_departments(max_records=CONSIGNE_SCAN_LIMIT):
        if dept.department_id is None:
            continue
        scanned += 1
        try:
            note = live_client.get_department_comment(dept.department_id)
        except (EasyvistaAuthError, EasyvistaNotFound) as exc:
            # Narrowed on the STATUS CODE, not the class: see _is_per_record_gap.
            if not _is_per_record_gap(exc):
                raise
            continue  # profile-gated or missing on this record; keep scanning
        if note and note.strip():
            return dept.department_id
    pytest.skip(f"no department with a non-empty note in {scanned} scanned")
