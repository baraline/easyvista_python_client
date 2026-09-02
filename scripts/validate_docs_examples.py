#!/usr/bin/env python
"""Validate the documentation examples against the real library (and, optionally,
a live EasyVista test instance).

This script does **not** read the documents. It checks a *hand-maintained
transcription* of what ``docs/user_guide.rst`` / ``docs/installation.rst``
claim -- no ``.rst`` file is ever opened, and nothing mechanically ties a check
here to the passage it stands for. A doc example nobody transcribed cannot fail
here, so a green run is evidence about the transcribed subset only, not about
the documents. Keep that in mind before trusting it: prose examples in
particular (inline literals in a bullet, rather than a ``code-block``) have
gone stale under a green run. It runs three tiers:

1. **offline** (always): every symbol, model field, method signature, attribute
   and serialization claim *transcribed below* is exercised through the
   *public* package surface (``import easyvista_python_client``). No network.
   This is the part that catches a transcribed claim naming a
   field/kwarg/attribute the code does not have.

2. **live read-only** (if credentials resolve): the read examples
   (``search_tickets``, ``get_ticket``, ``search_assets``, ``iter_tickets``,
   ``list_actions``, ``list_documents``) plus the *rejected* create that the docs
   use to demonstrate ``EasyvistaValidationError``. That last one is **not**
   read-only: a 590 rejection was measured to leave a row behind anyway (one
   instance, 2026-08-25 -- 12 attempts, 3 RFC numbers returned, all 12
   tickets present afterwards), so this tier can leak one ticket per run. See
   ``rejected_create`` below.

3. **live writes** (only with ``--writes`` AND credentials): the create / update
   / close / action / document / asset examples, which create real records on
   the target instance. Off by default — the project's live suite is read-only.

Credentials resolve exactly like ``integration_tests/conftest.py``:

    url     <- EASYVISTA_TEST_URL     | secrets/easyvista_test_url
    account <- EASYVISTA_TEST_ACCOUNT | secrets/easyvista_test_account
    token   <- EASYVISTA_TEST_TOKEN   | secrets/easyvista_test_token

``account`` is **not a login**: it is the instance id forming the ``{account}``
path segment of ``https://host/api/{version}/{account}`` (e.g. ``50004``). Auth
is the ``token`` alone. It is read only when ``url`` is a bare host -- a full API
root already carries the account. Spelled ``EASYVISTA_TEST_USER`` before
2026-08-25; that name is now refused, not silently accepted.

A ``.env`` file at the repo root is loaded first if ``python-dotenv`` is
installed. Secret values are never printed.

Usage::

    python scripts/validate_docs_examples.py            # offline + live read-only
    python scripts/validate_docs_examples.py --writes   # also run the write examples
    python scripts/validate_docs_examples.py --offline  # offline only
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
import traceback
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Annotation-only: the package is imported lazily inside the functions below
    # so the offline tier can report a missing install instead of crashing.
    from collections.abc import Callable

    from easyvista_python_client import EasyvistaConfig, Request

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = REPO_ROOT / "secrets"


# --------------------------------------------------------------------------- #
# tiny test harness
# --------------------------------------------------------------------------- #
class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def check(self, name: str, fn: Callable[[], object]) -> None:
        try:
            fn()
        except Exception as exc:
            self.failed += 1
            print(f"  [FAIL] {name}")
            print(f"         {type(exc).__name__}: {exc}")
            tb = traceback.format_exc(limit=2).strip().splitlines()
            for line in tb[-3:]:
                print(f"         {line}")
        else:
            self.passed += 1
            print(f"  [PASS] {name}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped += 1
        print(f"  [SKIP] {name} -- {reason}")

    def check_perm(self, name: str, fn: Callable[[], object]) -> None:
        """Like check(), but a 403 'profile not authorized' is a SKIP, not a FAIL.

        A 403 here is an instance permission limit on the access token, not a
        defect in the example or the client.
        """
        from easyvista_python_client import EasyvistaAuthError

        try:
            fn()
        except EasyvistaAuthError as exc:
            if exc.status_code == 403:
                self.skip(name, "profile not authorized (HTTP 403) on this instance")
                return
            self.failed += 1
            print(f"  [FAIL] {name}")
            print(f"         {type(exc).__name__}: {exc}")
        except Exception as exc:
            self.failed += 1
            print(f"  [FAIL] {name}")
            print(f"         {type(exc).__name__}: {exc}")
        else:
            self.passed += 1
            print(f"  [PASS] {name}")


# --------------------------------------------------------------------------- #
# offline checks: drive the public surface, no network
# --------------------------------------------------------------------------- #
def run_offline(r: Results) -> None:
    print("\n== Offline (public surface, no network) ==")

    # 1. Every symbol the docs reference is importable from the package root.
    def imports() -> None:
        import easyvista_python_client as ev

        names = [
            "EasyvistaClient",
            "AsyncEasyvistaClient",
            "EasyvistaConfig",
            "PostRequest",
            "RequestUpdate",
            "PostAction",
            "PostAsset",
            "Request",
            "Action",
            "Asset",
            "Document",
            "SearchResult",
            "EasyvistaError",
            "EasyvistaAuthError",
            "EasyvistaNotFound",
            "EasyvistaValidationError",
            "EasyvistaRateLimitError",
            "EasyvistaServerError",
            "EasyvistaConnectionError",
        ]
        missing = [n for n in names if not hasattr(ev, n)]
        assert not missing, f"not exported: {missing}"

    r.check("docs symbols importable from easyvista_python_client", imports)

    from easyvista_python_client import (
        AsyncEasyvistaClient,
        EasyvistaAuthError,
        EasyvistaClient,
        EasyvistaConfig,
        EasyvistaConnectionError,
        EasyvistaError,
        EasyvistaNotFound,
        EasyvistaRateLimitError,
        EasyvistaServerError,
        EasyvistaValidationError,
        PostAction,
        PostAsset,
        PostRequest,
        RequestUpdate,
        SearchResult,
    )

    # 2. "Creating a client": Bearer config.
    r.check(
        "EasyvistaConfig(server, account, token=...)  [Creating a client]",
        lambda: EasyvistaConfig(
            server="https://my.easyvista.com", account="12345", token="..."
        ),
    )

    # 3. "Authentication": HTTP Basic config.
    r.check(
        "EasyvistaConfig(server, account, login=, password=)  [Authentication]",
        lambda: EasyvistaConfig(
            server="https://my.easyvista.com",
            account="12345",
            login="rest.user",
            password="...",
        ),
    )

    # 4. from_env reads the documented env vars (URL/ACCOUNT/TOKEN).
    def from_env_token() -> None:
        env_keys = [
            "EASYVISTA_URL",
            "EASYVISTA_SERVER",
            "EASYVISTA_ACCOUNT",
            "EASYVISTA_TOKEN",
            "EASYVISTA_TOKEN_FILE",
            "EASYVISTA_LOGIN",
            "EASYVISTA_PASSWORD",
        ]
        saved = {k: os.environ.pop(k, None) for k in env_keys}
        try:
            os.environ["EASYVISTA_URL"] = "https://my.easyvista.com"
            os.environ["EASYVISTA_ACCOUNT"] = "12345"
            os.environ["EASYVISTA_TOKEN"] = "tok-123"
            cfg = EasyvistaConfig.from_env()
            assert cfg.server == "https://my.easyvista.com", cfg.server
            assert cfg.account == "12345", cfg.account
            assert cfg.token == "tok-123", cfg.token
        finally:
            for k, previous in saved.items():
                os.environ.pop(k, None)
                if previous is not None:
                    os.environ[k] = previous

    r.check(
        "EasyvistaConfig.from_env() reads EASYVISTA_URL/ACCOUNT/TOKEN",
        from_env_token,
    )

    # 4b. from_env Basic fallback (LOGIN/PASSWORD) when no token.
    def from_env_basic() -> None:
        env_keys = [
            "EASYVISTA_URL",
            "EASYVISTA_SERVER",
            "EASYVISTA_ACCOUNT",
            "EASYVISTA_TOKEN",
            "EASYVISTA_TOKEN_FILE",
            "EASYVISTA_LOGIN",
            "EASYVISTA_PASSWORD",
        ]
        saved = {k: os.environ.pop(k, None) for k in env_keys}
        try:
            os.environ["EASYVISTA_SERVER"] = "https://my.easyvista.com"
            os.environ["EASYVISTA_ACCOUNT"] = "12345"
            os.environ["EASYVISTA_LOGIN"] = "rest.user"
            os.environ["EASYVISTA_PASSWORD"] = "pw"
            cfg = EasyvistaConfig.from_env()
            assert cfg.login == "rest.user", cfg.login
            assert cfg.password == "pw", cfg.password
        finally:
            for k, previous in saved.items():
                os.environ.pop(k, None)
                if previous is not None:
                    os.environ[k] = previous

    r.check(
        "EasyvistaConfig.from_env() Basic fallback (LOGIN/PASSWORD)",
        from_env_basic,
    )

    # 5. "Working with tickets": full PostRequest field set from the example.
    def post_request_full() -> None:
        body = PostRequest(
            catalog_code="SAMPLE_CATALOG",
            title="Printer down",
            description="The 3rd-floor printer is offline",
            origin="Phone",
            department_id=9,
            urgency_id=8,
            impact_id=28,
            recipient_mail="user@example.com",
        ).to_api()
        for key in (
            "catalog_code",
            "title",
            "origin",
            "department_id",
            "urgency_id",
            "impact_id",
            "recipient_mail",
        ):
            assert key in body, f"{key} dropped from to_api(): {sorted(body)}"

    r.check(
        "PostRequest(all documented fields).to_api()  [Working with tickets]",
        post_request_full,
    )

    # 6. "Custom fields": e_ prefix behaviour.
    def custom_fields() -> None:
        already = PostRequest(
            catalog_code="X", custom_fields={"e_location": "Paris"}
        ).to_api()
        assert already.get("e_location") == "Paris", already
        bare = PostRequest(
            catalog_code="X", custom_fields={"location": "Paris"}
        ).to_api()
        assert bare.get("e_location") == "Paris", bare
        assert "location" not in bare, bare

    r.check(
        "PostRequest custom_fields serialize to e_*  [Custom fields]",
        custom_fields,
    )

    # 7. RequestUpdate(description=...)
    r.check(
        "RequestUpdate(description=...)  [Fetch/update/close]",
        lambda: RequestUpdate(description="Updated details"),
    )

    # 8. PostAction(action_type_id=, group_id=, description=)
    r.check(
        "PostAction(action_type_id, group_id, description)  [Actions]",
        lambda: PostAction(action_type_id=94, group_id=3, description="Triaged: on it"),
    )

    # 9. PostAsset(catalog_id=, asset_tag=)
    r.check(
        "PostAsset(catalog_id, asset_tag)  [Assets]",
        lambda: PostAsset(catalog_id=3153, asset_tag="LAPTOP-001"),
    )

    # 10. Client method signatures accept the documented keyword arguments.
    def signatures() -> None:
        expected = {
            "create_ticket": {"ticket"},
            "create_tickets": {"tickets"},
            "get_ticket": {"rfc_number"},
            "update_ticket": {"rfc_number", "update"},
            "close_ticket": {"rfc_number", "status_guid", "delete_actions", "comment"},
            "create_action": {"rfc_number", "action"},
            "list_actions": {"rfc_number"},
            "iter_actions": {"rfc_number", "fields", "page_size", "max_records"},
            "create_asset": {"asset"},
            "get_asset": {"asset_id"},
            "search_tickets": {"search", "fields", "sort", "max_rows", "offset"},
            "iter_tickets": {"search", "fields", "sort", "page_size", "max_records"},
            "search_assets": {"search", "fields", "sort", "max_rows", "offset"},
            "iter_assets": {"search", "fields", "sort", "page_size", "max_records"},
            "add_document": {"rfc_number", "filename", "content"},
            "list_documents": {"rfc_number"},
            "download_document": {"document"},
            "stream_document": {"document", "chunk_size"},
        }
        problems = []
        for method, params in expected.items():
            fn = getattr(EasyvistaClient, method, None)
            if fn is None:
                problems.append(f"EasyvistaClient.{method} missing")
                continue
            actual = set(inspect.signature(fn).parameters) - {"self"}
            missing = params - actual
            if missing:
                problems.append(
                    f"{method} missing params {sorted(missing)} (has {sorted(actual)})"
                )
        assert not problems, "; ".join(problems)

    r.check("EasyvistaClient method signatures match documented kwargs", signatures)

    # 10b. Async client exposes the SAME method names (the sync-vs-async claim).
    def async_parity() -> None:
        public = {
            "create_ticket",
            "create_tickets",
            "get_ticket",
            "update_ticket",
            "close_ticket",
            "create_action",
            "list_actions",
            "iter_actions",
            "create_asset",
            "get_asset",
            "search_tickets",
            "iter_tickets",
            "search_assets",
            "iter_assets",
            "add_document",
            "list_documents",
            "download_document",
            "stream_document",
            "from_env",
        }
        missing = [m for m in public if not hasattr(AsyncEasyvistaClient, m)]
        assert not missing, f"AsyncEasyvistaClient missing: {missing}"
        # iter_tickets must be an async generator on the async client.
        assert inspect.isasyncgenfunction(AsyncEasyvistaClient.iter_tickets), (
            "AsyncEasyvistaClient.iter_tickets is not an async generator"
        )
        # And so must stream_document: the user guide documents it as something
        # you iterate, which on the async surface means `async for`.
        assert inspect.isasyncgenfunction(AsyncEasyvistaClient.stream_document), (
            "AsyncEasyvistaClient.stream_document is not an async generator"
        )

    r.check(
        "AsyncEasyvistaClient mirrors sync method names  [Sync vs async]",
        async_parity,
    )

    # 11. SearchResult exposes the documented attributes.
    def search_result_fields() -> None:
        sr: SearchResult[dict[str, Any]] = SearchResult(
            records=[], record_count=0, total_record_count=0, href="h", next_url=None
        )
        for attr in (
            "records",
            "record_count",
            "total_record_count",
            "href",
            "next_url",
        ):
            assert hasattr(sr, attr), attr

    r.check(
        "SearchResult has records/record_count/total_record_count/href/next_url",
        search_result_fields,
    )

    # 11b. Action exposes the label the docs name as an attribute.
    def action_visibility_label() -> None:
        from easyvista_python_client import Action

        action = Action.model_validate(
            {"ACTION_ID": "1", "ACTION_LABEL_FR": "Analyse de Resolution"}
        )
        assert action.action_label_fr == "Analyse de Resolution"
        assert action.reference("ACTION_TYPE").id is None  # absent -> empty, no raise

    r.check("Action.action_label_fr  [Actions]", action_visibility_label)

    # 12. Exception hierarchy + attributes carried by EasyvistaError.
    def exceptions() -> None:
        exc = EasyvistaError("boom", status_code=590, ev_code="2013", ev_message="bad")
        assert (
            exc.status_code == 590 and exc.ev_code == "2013" and exc.ev_message == "bad"
        )
        for sub in (
            EasyvistaAuthError,
            EasyvistaNotFound,
            EasyvistaValidationError,
            EasyvistaRateLimitError,
            EasyvistaServerError,
            EasyvistaConnectionError,
        ):
            assert issubclass(sub, EasyvistaError), sub.__name__

    r.check(
        "EasyvistaError carries status_code/ev_code/ev_message;"
        " subclasses derive from it",
        exceptions,
    )

    # 13. Both clients are context managers (the docs use `with`/`async with`).
    def context_managers() -> None:
        cfg = EasyvistaConfig(
            server="https://my.easyvista.com", account="12345", token="t"
        )
        c = EasyvistaClient(cfg)
        assert hasattr(c, "__enter__") and hasattr(c, "__exit__")
        c.close() if hasattr(c, "close") else None
        a = AsyncEasyvistaClient(cfg)
        assert hasattr(a, "__aenter__") and hasattr(a, "__aexit__")

    r.check(
        "EasyvistaClient is a context manager; AsyncEasyvistaClient an async one",
        context_managers,
    )


# --------------------------------------------------------------------------- #
# credential resolution (mirrors integration_tests/conftest.py)
# --------------------------------------------------------------------------- #
def _resolve(env_names: tuple[str, ...], filename: str) -> str | None:
    for name in env_names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    path = SECRETS_DIR / filename
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


# Retired 2026-08-25: the value is the API-root ``{account}`` path segment, not a
# login. Reading the old spelling as a fallback would re-admit the confusion the
# rename removed, so it is refused. Only names are printed, never values.
_LEGACY_ACCOUNT_ENV = "EASYVISTA_TEST_USER"
_LEGACY_ACCOUNT_FILE = "easyvista_test_user"


def _reject_legacy_account_name() -> None:
    """Abort when the pre-rename account credential is still configured."""
    stale: list[str] = []
    value = os.environ.get(_LEGACY_ACCOUNT_ENV)
    if value and value.strip():
        stale.append("the " + _LEGACY_ACCOUNT_ENV + " environment variable")
    if (SECRETS_DIR / _LEGACY_ACCOUNT_FILE).is_file():
        stale.append("secrets/" + _LEGACY_ACCOUNT_FILE)
    if stale:
        verb = "is" if len(stale) == 1 else "are"
        raise SystemExit(
            " and ".join(stale) + " " + verb + " still set. That name was retired on "
            "2026-08-25 and is no longer read: the value is the EasyVista "
            "account -- the instance id in https://host/api/{version}/{account} "
            "-- and never a login. Rename it to EASYVISTA_TEST_ACCOUNT / "
            "secrets/easyvista_test_account."
        )


def _resolve_int(env_names: tuple[str, ...], filename: str) -> int | None:
    value = _resolve(env_names, filename)
    return int(value) if value is not None else None


def resolve_live_config() -> EasyvistaConfig | None:
    from easyvista_python_client import EasyvistaConfig

    url = _resolve(("EASYVISTA_TEST_URL",), "easyvista_test_url")
    account = _resolve(("EASYVISTA_TEST_ACCOUNT",), "easyvista_test_account")
    token = _resolve(("EASYVISTA_TEST_TOKEN",), "easyvista_test_token")
    if not url or not token:
        return None
    # Ordered after the no-credentials exit, matching integration_tests/conftest.py:
    # a checkout with nothing configured stays gracefully skippable whether or not
    # a stray legacy file is lying around.
    _reject_legacy_account_name()
    root = url.rstrip("/")
    if "/api/" in root:
        server, _, rest = root.partition("/api/")
        version, _, account_tail = rest.partition("/")
        account = account_tail.split("/")[0]
        if not account:
            return None
        return EasyvistaConfig(
            server=server, account=account, token=token, api_version=version
        )
    # A bare host: the account cannot be parsed out of the URL, so it must be
    # supplied separately.
    if not account:
        return None
    return EasyvistaConfig(server=root, account=account, token=token)


# --------------------------------------------------------------------------- #
# live read-only checks
# --------------------------------------------------------------------------- #
def run_live_readonly(
    r: Results, config: EasyvistaConfig, catalog_code: str | None
) -> None:
    print("\n== Live read-only (real instance) ==")
    from easyvista_python_client import (
        Action,
        Asset,
        Document,
        EasyvistaClient,
        EasyvistaValidationError,
        PostRequest,
        Request,
        ev_equals_filter,
    )

    with EasyvistaClient(config) as client:
        # A sample RFC for the ticket sub-resource reads, a *real*,
        # instance-specific STATUS_ID to filter on (never hardcode one --
        # nobody running this script has confirmed any particular id exists
        # on the target instance), and the unfiltered baseline count.
        #
        # The baseline matters: EasyVista silently ignores a search condition
        # it cannot resolve and returns the WHOLE TABLE instead of erroring
        # (see the search-syntax warning in docs/user_guide.rst) -- a filtered
        # count is meaningless on its own, since a filter that matched every
        # record looks identical to a filter that was silently ignored. The
        # only way to tell them apart is to compare against this baseline.
        sample_rfc = None
        sample_status_id = None
        probe = client.search_tickets(max_rows=1)
        baseline_total = probe.total_record_count
        if probe.records and probe.records[0].rfc_number:
            sample_rfc = probe.records[0].rfc_number
            # search_tickets' default field set omits STATUS_ID (verified
            # live: it comes back None here); a full single-ticket GET
            # returns it.
            sample_status_id = client.get_ticket(sample_rfc).status_id
        status_filter = ev_equals_filter("STATUS_ID", sample_status_id)

        def search_tickets() -> None:
            res = client.search_tickets(search=status_filter, max_rows=5)
            assert isinstance(res.total_record_count, int)
            assert all(isinstance(x, Request) for x in res.records)
            # The defect this script exists to catch: a filtered count sitting
            # at (or above) the unfiltered baseline is the silent-ignore
            # failure signature, not a pass. `== baseline` must FAIL here.
            assert 0 < res.total_record_count < baseline_total, (
                f"search_tickets(search={status_filter!r}) returned "
                f"{res.total_record_count} of {baseline_total} total records "
                "-- the filter looks like it was silently ignored"
            )

        if status_filter is not None:
            r.check(
                f"search_tickets(search={status_filter!r}, max_rows=5)"
                " [asserts filtered < baseline]",
                search_tickets,
            )
        else:
            r.skip(
                "search_tickets(search='STATUS_ID:\"<id>\"', max_rows=5)",
                "no ticket with a status id available to derive a real filter",
            )

        def get_ticket() -> None:
            if not sample_rfc:
                raise AssertionError("no ticket available on instance to read")
            t = client.get_ticket(sample_rfc)
            assert isinstance(t, Request)

        if sample_rfc:
            r.check(f"get_ticket('{sample_rfc}')", get_ticket)
        else:
            r.skip("get_ticket(<rfc>)", "no tickets on instance")

        def iter_tickets() -> None:
            seen = 0
            for t in client.iter_tickets(
                search=status_filter, page_size=50, max_records=3
            ):
                assert isinstance(t, Request)
                seen += 1
            assert seen <= 3

        if status_filter is not None:
            r.check("iter_tickets(..., page_size=50, max_records=3)", iter_tickets)
        else:
            r.skip(
                "iter_tickets(..., page_size=50, max_records=3)",
                "no ticket with a status id available to derive a real filter",
            )

        def search_assets() -> None:
            res = client.search_assets(max_rows=5)
            assert isinstance(res.total_record_count, int)
            assert all(isinstance(x, Asset) for x in res.records)

        r.check("search_assets(max_rows=5)", search_assets)

        def list_actions() -> None:
            if not sample_rfc:
                raise AssertionError("no ticket available")
            actions = client.list_actions(sample_rfc)
            assert isinstance(actions, list)
            assert all(isinstance(a, Action) for a in actions)

        if sample_rfc:
            r.check(f"list_actions('{sample_rfc}')", list_actions)
        else:
            r.skip("list_actions(<rfc>)", "no tickets on instance")

        def iter_actions() -> None:
            if not sample_rfc:
                raise AssertionError("no ticket available")
            # Bounded: the offset contract is unverified on this endpoint,
            # so a sweep that never advances is possible.
            seen = list(client.iter_actions(sample_rfc, max_records=30))
            assert all(isinstance(a, Action) for a in seen)
            ids = [a.action_id for a in seen if a.action_id is not None]
            assert len(ids) == len(set(ids)), (
                "iter_actions repeated an action id: the endpoint ignored "
                "offset, so paging loops instead of advancing"
            )

        if sample_rfc:
            r.check(f"iter_actions('{sample_rfc}', max_records=30)", iter_actions)
        else:
            r.skip("iter_actions(<rfc>)", "no tickets on instance")

        def list_documents() -> None:
            if not sample_rfc:
                raise AssertionError("no ticket available")
            docs = client.list_documents(sample_rfc)
            assert isinstance(docs, list)
            assert all(isinstance(d, Document) for d in docs)

        if sample_rfc:
            r.check(f"list_documents('{sample_rfc}')", list_documents)
        else:
            r.skip("list_documents(<rfc>)", "no tickets on instance")

        def ticket_to_markdown() -> None:
            if not sample_rfc:
                raise AssertionError("no ticket available")
            md = client.get_ticket_context(sample_rfc).to_markdown()
            assert isinstance(md, str) and md.startswith("# Ticket")
            assert "/api/" not in md, "rendered markdown leaked an API URL"

        if sample_rfc:
            r.check(
                f"get_ticket_context('{sample_rfc}').to_markdown() [no /api/ URL]",
                ticket_to_markdown,
            )
        else:
            r.skip("get_ticket_context(<rfc>).to_markdown()", "no tickets on instance")

        def reporting() -> None:
            total = client.count_tickets(search=status_filter)
            assert isinstance(total, int) and total >= 0
            stats = client.ticket_statistics(
                search=status_filter, dimensions=["STATUS"], max_records=5
            )
            assert isinstance(stats.total, int)
            # Every breakdown reconciles to the (possibly capped) total.
            for counts in stats.breakdowns.values():
                assert sum(counts.values()) == stats.total

        if status_filter is not None:
            r.check(
                "count_tickets + ticket_statistics(dimensions=['STATUS'])", reporting
            )
        else:
            r.skip(
                "count_tickets + ticket_statistics(dimensions=['STATUS'])",
                "no ticket with a status id available to derive a real filter",
            )

        def rejected_create() -> None:
            # The error-handling example: an under-specified body (a valid
            # catalog, but none of the ids the catalog needs) is rejected
            # server-side with HTTP 590. `title` is NOT the mandatory field --
            # the full documented body with no title creates fine -- so do not
            # describe this as a missing-title test.
            #
            # NOT read-only. A 590 rejection was measured to write the row
            # anyway (one instance, 2026-08-25: 12 attempts, 3 RFC_NUMBERs
            # returned, all 12 tickets present afterwards), so each run of this
            # check can leave an orphan on the target instance. It is left in
            # place because the docs demonstrate exactly this call, but it is
            # the one live-read-only check that writes.
            #
            # catalog_code must be *valid* on this instance so the missing ids
            # are the payload's only defect -- an unknown catalog would also
            # 590, and the assertion below couldn't tell the two failures apart.
            try:
                client.create_ticket(PostRequest(catalog_code=catalog_code))
            except EasyvistaValidationError as exc:
                assert exc.status_code == 590, f"expected 590, got {exc.status_code}"
            else:
                raise AssertionError("expected EasyvistaValidationError, none raised")

        if catalog_code:
            r.check(
                "create_ticket(under-specified) -> EasyvistaValidationError(590)"
                "  [Error handling]",
                rejected_create,
            )
        else:
            r.skip(
                "create_ticket(under-specified) -> EasyvistaValidationError(590)"
                "  [Error handling]",
                "no EASYVISTA_TEST_CATALOG_CODE"
                " (or secrets/easyvista_test_catalog_code)",
            )


# --------------------------------------------------------------------------- #
# live write checks (create real records -- opt-in only)
# --------------------------------------------------------------------------- #
def _ident_from(ticket: Request) -> str | None:
    """Best identifier for follow-up calls.

    ``create_*`` responses return only ``{"HREF": ".../requests/<id>"}`` -- no
    ``RFC_NUMBER`` -- so the documented ``ticket.rfc_number`` is ``None`` right
    after a create. Fall back to the trailing path segment of ``href``.
    """
    if getattr(ticket, "rfc_number", None):
        return ticket.rfc_number
    href = getattr(ticket, "href", None)
    if isinstance(href, str) and href:
        return href.rstrip("/").rsplit("/", 1)[-1]
    return None


def run_live_writes(
    r: Results,
    config: EasyvistaConfig,
    catalog_code: str,
    status_guid: str | None,
    asset_catalog_id: int,
    autoclose: bool,
) -> None:
    print("\n== Live WRITES (creates real records) ==")
    from easyvista_python_client import (
        Action,
        Asset,
        Document,
        EasyvistaClient,
        PostAction,
        PostAsset,
        PostRequest,
        Request,
        RequestUpdate,
    )

    created_rfcs: list[str] = []
    # Plain alphanumeric text only: EasyVista evaluates some field content
    # server-side and rejects tokens like '--', '[', ']', '/', '.' (HTTP 590).
    title = "docs validation please ignore"
    body = "Created by docs validation script"

    with EasyvistaClient(config) as client:
        # create_ticket  [End-to-end] payload (catalog requires origin/dept/
        # urgency/impact; recipient_mail omitted -- a placeholder email 406s).
        def create_ticket() -> None:
            t = client.create_ticket(
                PostRequest(
                    catalog_code=catalog_code,
                    title=title,
                    description=body,
                    origin=7,
                    department_id=9,
                    urgency_id=7,
                    impact_id=21,
                )
            )
            assert isinstance(t, Request)
            ident = _ident_from(t)
            assert ident, "create_ticket returned neither rfc_number nor a usable href"
            created_rfcs.append(ident)
            if not t.rfc_number:
                print(
                    "         NOTE: create_ticket did NOT populate rfc_number"
                    " (response is HREF-only). Docs that use"
                    " `ticket.rfc_number` after create are broken;"
                    " the id must be parsed from `ticket.href`."
                )

        r.check_perm(
            "create_ticket(...)  [Working with tickets / End-to-end]",
            create_ticket,
        )
        rfc = created_rfcs[0] if created_rfcs else None

        # create_tickets fans out to one POST per ticket (EasyVista creates only
        # the first item of a multi-item body), so BOTH tickets are created.
        def create_tickets() -> None:
            made = client.create_tickets(
                [
                    PostRequest(
                        catalog_code=catalog_code,
                        title="docs validation A",
                        origin=7,
                        department_id=9,
                        urgency_id=7,
                        impact_id=21,
                    ),
                    PostRequest(
                        catalog_code=catalog_code,
                        title="docs validation B",
                        origin=7,
                        department_id=9,
                        urgency_id=7,
                        impact_id=21,
                    ),
                ]
            )
            for t in made:
                ident = _ident_from(t)
                if ident:
                    created_rfcs.append(ident)
            assert len(made) == 2, f"expected 2 tickets created, got {len(made)}"
            assert all(_ident_from(t) for t in made), (
                "a created ticket had no usable id"
            )

        r.check_perm("create_tickets([...])  [Working with tickets]", create_tickets)

        if rfc:
            r.check(f"get_ticket('{rfc}')", lambda: client.get_ticket(rfc))
            r.check_perm(
                "update_ticket(rfc, RequestUpdate(description=...))"
                "  [Fetch/update/close]",
                lambda: client.update_ticket(
                    rfc, RequestUpdate(description="Updated by validation")
                ),
            )

            def create_action() -> None:
                a = client.create_action(
                    rfc,
                    PostAction(
                        action_type_id=94, group_id=3, description="Investigating"
                    ),
                )
                assert isinstance(a, Action)

            r.check_perm(
                "create_action(rfc, PostAction(...))  [Actions]",
                create_action,
            )

            def add_document() -> None:
                d = client.add_document(
                    rfc,
                    filename="docsvalidation.txt",
                    content=b"docs validation upload\n",
                )
                assert isinstance(d, Document)

            r.check_perm(
                "add_document(rfc, filename=, content=)  [Documents]",
                add_document,
            )
        else:
            r.skip("get_ticket/update/action/document", "no ticket was created")

        # create_asset  [Assets] -- catalog_id not vendor-documented; profile may 403.
        def create_asset() -> None:
            a = client.create_asset(
                PostAsset(catalog_id=asset_catalog_id, asset_tag="DOCSVAL001")
            )
            assert isinstance(a, Asset)

        r.check_perm(
            f"create_asset(PostAsset(catalog_id={asset_catalog_id}, ...))  [Assets]",
            create_asset,
        )

        # close_ticket  [End-to-end] -- also our cleanup for created tickets.
        if autoclose and status_guid:
            for target in list(created_rfcs):
                r.check_perm(
                    f"close_ticket('{target}', status_guid=..., delete_actions=1,"
                    " comment=...)",
                    partial(
                        client.close_ticket,
                        target,
                        status_guid=status_guid,
                        delete_actions=1,
                        comment="Resolved by validation",
                    ),
                )
        elif not status_guid:
            r.skip("close_ticket(...)", "no status_guid available")
        else:
            r.skip("close_ticket(...) cleanup", "autoclose disabled")

    if created_rfcs:
        print(f"\n  Tickets created this run: {', '.join(created_rfcs)}")
        if not (autoclose and status_guid):
            print("  NOTE: these were NOT closed -- inspect/close them manually.")


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="offline checks only")
    parser.add_argument(
        "--writes",
        action="store_true",
        help="also run write examples (creates records)",
    )
    parser.add_argument(
        "--catalog-code",
        default=_resolve(
            ("EASYVISTA_TEST_CATALOG_CODE",), "easyvista_test_catalog_code"
        ),
        help=(
            "catalog_code for the write create (env EASYVISTA_TEST_CATALOG_CODE,"
            " or secrets/easyvista_test_catalog_code)"
        ),
    )
    parser.add_argument(
        "--status-guid",
        default=_resolve(("EASYVISTA_TEST_STATUS_GUID",), "easyvista_test_status_guid"),
        help=(
            "closed status GUID for close_ticket (env EASYVISTA_TEST_STATUS_GUID,"
            " or secrets/easyvista_test_status_guid)"
        ),
    )
    parser.add_argument(
        "--asset-catalog-id",
        type=int,
        default=_resolve_int(
            ("EASYVISTA_TEST_ASSET_CATALOG_ID",), "easyvista_test_asset_catalog_id"
        ),
        help=(
            "catalog_id for create_asset (env EASYVISTA_TEST_ASSET_CATALOG_ID,"
            " or secrets/easyvista_test_asset_catalog_id)"
        ),
    )
    parser.add_argument(
        "--no-autoclose",
        action="store_true",
        help=(
            "with --writes, do NOT close created tickets (leaves them on the instance)"
        ),
    )
    args = parser.parse_args()

    # Best-effort .env load so EASYVISTA_TEST_* in a .env are picked up.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    r = Results()
    run_offline(r)

    if not args.offline:
        config = resolve_live_config()
        if config is None:
            print("\n== Live tiers SKIPPED ==")
            print("  No credentials. Set EASYVISTA_TEST_URL and")
            print("  EASYVISTA_TEST_TOKEN, or add secrets/easyvista_test_url and")
            print("  secrets/easyvista_test_token. EASYVISTA_TEST_ACCOUNT (or")
            print("  secrets/easyvista_test_account) is needed only when the URL")
            print("  has no /api/ segment -- it is the instance id, not a login.")
            r.skip("live read-only tier", "no credentials")
            if args.writes:
                r.skip("live writes tier", "no credentials")
        else:
            run_live_readonly(r, config, args.catalog_code)
            if args.writes:
                missing = []
                if not args.catalog_code:
                    missing.append(
                        "EASYVISTA_TEST_CATALOG_CODE"
                        " (or secrets/easyvista_test_catalog_code)"
                    )
                if not args.asset_catalog_id:
                    missing.append(
                        "EASYVISTA_TEST_ASSET_CATALOG_ID"
                        " (or secrets/easyvista_test_asset_catalog_id)"
                    )
                if missing:
                    print("\n== Live writes tier SKIPPED ==")
                    print("  Missing required config:")
                    for item in missing:
                        print(f"    - {item}")
                    r.skip("live writes tier", "missing instance-specific config")
                else:
                    run_live_writes(
                        r,
                        config,
                        args.catalog_code,
                        args.status_guid,
                        args.asset_catalog_id,
                        autoclose=not args.no_autoclose,
                    )
            else:
                print(
                    "\n  (write examples skipped; pass --writes to create real records)"
                )

    print(f"\nSummary: {r.passed} passed, {r.failed} failed, {r.skipped} skipped")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
