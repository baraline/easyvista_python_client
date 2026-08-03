"""Fixtures for live integration tests.

These tests call a real EasyVista instance, so they live apart from the unit
tests inside the package and are **never run in CI** — CI runs
``pytest -m "not integration"``. You supply your own instance: every test here
skips cleanly when credentials are absent, so a checkout with no ``secrets/``
and no ``EASYVISTA_TEST_*`` environment simply skips the suite rather than
failing it.

They are not read-only. The ``probe_tickets`` fixture creates two tickets and
closes both in teardown; ``test_live_smoke`` additionally issues one create that
the server is *expected to reject*, so no ticket persists from it. Point them at
a preprod/test instance, never production.

Credentials resolve from an uppercase env var first, then a lowercase file under
``secrets/``:

    url    <- EASYVISTA_TEST_URL    | secrets/easyvista_test_url
    user   <- EASYVISTA_TEST_USER (or _ACCOUNT) | secrets/easyvista_test_user
    token  <- EASYVISTA_TEST_TOKEN  | secrets/easyvista_test_token

Two further per-instance ids resolve the same way (env var, else the matching
lowercase ``secrets/`` file), gating only the tests that need them
(``live_action_config``, see below):

    action_type_id <- EASYVISTA_TEST_ACTION_TYPE_ID
    group_id       <- EASYVISTA_TEST_GROUP_ID

Auth is **Bearer** (the ``token`` value) — confirmed against the live preprod
instance. The ``url`` value is the **full API root** (it already ends in
``/api/v1/{account}``), so we split it back into ``server`` + ``account`` so
``EasyvistaConfig.api_root`` reconstructs it exactly. If the URL is instead a
bare host (no ``/api/`` segment), the ``user`` value is used as the account.

The secret values are loaded by this test process at runtime and never printed.
Nor is live instance content: ``_force_short_traceback`` strips the frame-
argument block from every failure in this directory, which is what stops a test
spilling the fixtures it was handed. See ``_assertions.py`` for the other two
layers of that guarantee and why all three are needed.
"""

from __future__ import annotations

import os
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
    user = _resolve(
        ("EASYVISTA_TEST_USER", "EASYVISTA_TEST_ACCOUNT"), "easyvista_test_user"
    )
    token = _resolve(("EASYVISTA_TEST_TOKEN",), "easyvista_test_token")
    if not url or not token:
        pytest.skip(
            "live credentials unavailable (need url + token; set EASYVISTA_TEST_* "
            "env vars or add secrets/easyvista_test_* files)"
        )

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
    # url is a bare host; the account comes from the user value.
    if not user:
        pytest.skip("URL has no /api/ segment, so a user/account value is required")
    return EasyvistaConfig(
        server=root,
        account=user,
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


# Three attempts, and a re-send happens ONLY after a search has proved the
# previous attempt did not commit -- so N attempts still yield at most one ticket.
_CREATE_ATTEMPTS = 3


class _InconclusiveCreate(RuntimeError):
    """A create whose outcome could not be established, so it must NOT be re-sent.

    Deliberately distinct from an ordinary failure. Re-sending risks a duplicate
    ticket the suite never learns the RFC of -- an orphan on someone else's
    instance -- and that is worse than stopping loudly.
    """


def _adopt_by_title(search_client: EasyvistaClient, title: str) -> str | None:
    """Return the RFC of the ticket titled exactly ``title``, or ``None`` if absent.

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
        result = search_client.search_tickets(search=search, max_rows=2)
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
    write_client: EasyvistaClient,
    search_client: EasyvistaClient,
    cfg: dict[str, str],
    tracked: list[str],
    *,
    title: str,
    description: str,
) -> str:
    """Create one ticket and register its RFC in ``tracked`` the instant it is known.

    The append happens BEFORE any assertion, which is the whole point: the old
    order asserted on the RFC first, so a create that committed server-side but
    returned no usable body left a ticket nothing would ever close.

    ``write_client`` must be the zero-retry client. This function does its own
    retrying, and it re-sends only after a search has *proved* the previous attempt
    did not commit -- so at most one ticket exists however many attempts are made.
    A deterministic rejection (``EasyvistaValidationError``, HTTP 590) is not a
    transient and propagates untouched.
    """
    for _attempt in range(_CREATE_ATTEMPTS):
        rfc: str | None = None
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

        adopted = _adopt_by_title(search_client, title)
        if adopted is not None:
            tracked.append(adopted)
            return adopted
        # The search was honoured and found nothing, so nothing committed and the
        # next attempt cannot duplicate.

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
            live_write_client,
            live_client,
            cfg,
            tracked,
            title=f"EVCLI{nonce}A",
            description=description,
        )
        rfc_quoted = _create_tracked(
            live_write_client,
            live_client,
            cfg,
            tracked,
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
            live_write_client,
            live_client,
            cfg,
            tracked,
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
            live_write_client,
            live_client,
            cfg,
            tracked,
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
