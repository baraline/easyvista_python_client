#!/usr/bin/env python
"""Live content-fidelity validator for the EasyVista **test** instance.

Purpose
-------
Prove, against the real test instance, that a ticket created through
``easyvista_python_client`` — with a rich description, comments (actions) and
document attachments — round-trips and renders faithfully, and map exactly which
content the instance **accepts / normalizes / mangles / rejects**.

What it does (default run)
--------------------------
1. Connects using **only** the ``*_test_*`` credentials (never ``*_prod_*``) and
   refuses to run if the resolved host matches the recorded prod host.
2. Creates ONE ticket with a known-good structural payload (plain title/body).
3. Writes rich content in isolatable pieces, each wrapped so a rejection is a
   *recorded data point*, never fatal:
     - a rich **HTML description** via ``update_ticket``;
     - a set of **comment** probes (``create_action``): plain French, HTML
       formatting, line breaks, punctuation, quotes, emoji/unicode, a long line,
       and deliberately adversarial ``<script>``/SQL-ish/path-ish payloads;
     - a few **document** probes (``add_document``): ASCII text, accented
       filename + body, and a small binary PNG.
4. Reads everything back (``resolve_memo`` for the description, ``list_actions``,
   ``list_documents``) and classifies each piece with the pure
   :func:`classify_fidelity` (unit-tested in
   ``scripts/tests/test_validate_live_content_fidelity.py``).
5. Prints a fidelity table, the API's own Markdown view of the ticket
   (``get_ticket_context().to_markdown()``), and the **RFC + URLs**. The ticket
   is left **OPEN** for manual inspection in the EasyVista web UI.

Known limitation
----------------
The client has no binary **download**, so a document's *content* cannot be
byte-verified — only its attachment and filename. Those rows are marked
``UNVERIFIABLE`` for content.

Cleanup
-------
Nothing is closed automatically. When you are done inspecting, close the ticket::

    python scripts/validate_live_content_fidelity.py --close I260713_00001

Credentials resolve like ``integration_tests/conftest.py`` but **test-only**::

    url    <- EASYVISTA_TEST_URL   | secrets/easyvista_test_url
    user   <- EASYVISTA_TEST_USER  | secrets/easyvista_test_user   (account fallback)
    token  <- EASYVISTA_TEST_TOKEN | secrets/easyvista_test_token

A repo-root ``.env`` is loaded first if ``python-dotenv`` is installed. Secret
values are never printed.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import traceback
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from easyvista_python_client._html import html_to_text

if TYPE_CHECKING:
    # Annotation-only: the package is imported lazily inside the functions below
    # so that --help and the credential checks work without a live install.
    from collections.abc import Callable, Sequence

    from easyvista_python_client import (
        Action,
        Document,
        EasyvistaClient,
        EasyvistaConfig,
        Request,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = REPO_ROOT / "secrets"


# --------------------------------------------------------------------------- #
# pure fidelity classifier (unit-tested; no network)
# --------------------------------------------------------------------------- #
#: The returned value is byte-identical to what we sent.
EXACT = "EXACT"
#: Raw bytes differ, but the readable text is preserved — the server only
#: reformatted inert markup (added a wrapper, re-encoded an entity, reflowed
#: whitespace). Inspect the raw returned value to judge markup-level changes.
EQUIVALENT = "EQUIVALENT"
#: The readable text itself changed — characters dropped, altered, or truncated.
MANGLED = "MANGLED"
#: The server refused the write (HTTP 590); nothing was stored. Recorded at
#: write time, never by :func:`classify_fidelity`.
REJECTED = "REJECTED"
#: We cannot read the stored content back to compare (e.g. a document's bytes —
#: the client has no binary download), or the read-back list was 403-blocked.
UNVERIFIABLE = "UNVERIFIABLE"
#: The write appeared to succeed but the item was absent from the read-back.
MISSING = "MISSING"


def _semantic(value: str, *, html: bool) -> str:
    """Reduce a value to the readable text that a change would have to alter.

    With ``html=True`` (rich-text memos: descriptions, comments) strip tags and
    decode entities via the package's own reducer, so entity-encoding and added
    wrappers are inert. With ``html=False`` (filenames, plain identifiers) treat
    the value literally — an escaped ``&lt;`` is a real change, not decoration.
    Whitespace runs are always collapsed, since the server may reflow them.
    """
    text = html_to_text(value) if html else value
    return re.sub(r"\s+", " ", text).strip()


def classify_fidelity(sent: str, returned: str | None, *, html: bool = True) -> str:
    """Classify how faithfully ``returned`` preserved ``sent``.

    Returns one of :data:`EXACT`, :data:`EQUIVALENT`, :data:`MANGLED`, or
    :data:`MISSING`. :data:`REJECTED` / :data:`UNVERIFIABLE` are outcomes the
    caller records around the write/read, not text comparisons.
    """
    if returned is None:
        return MISSING
    if sent == returned:
        return EXACT
    if _semantic(sent, html=html) == _semantic(returned, html=html):
        return EQUIVALENT
    return MANGLED


# --------------------------------------------------------------------------- #
# content samples
# --------------------------------------------------------------------------- #
# Rich HTML description, applied via update_ticket (each write is isolated, so a
# rejection here does not lose the ticket). Real accents test encoding fidelity.
RICH_DESCRIPTION_HTML = (
    "<p>Validation de fidélité du contenu.</p>"
    "<p>Mise en forme : <b>gras</b>, <i>italique</i>, <u>souligné</u>.</p>"
    "<p>Accents français : café, élève, garçon, Noël, cœur, €.</p>"
    "<ul><li>Premier élément</li><li>Deuxième élément</li>"
    "<li>Troisième élément</li></ul>"
    '<p>Un lien : <a href="https://example.com/page">exemple</a></p>'
    "<p>Ligne un<br>Ligne deux<br>Ligne trois</p>"
)

# (label, payload). Each is prefixed with a unique ASCII marker at run time so
# the read-back can find its action even if the payload is mangled. html=True:
# comments are rich-text memos.
COMMENT_PROBES: list[tuple[str, str]] = [
    ("plain_french", "Commentaire simple avec accents : café élève garçon Noël."),
    (
        "html_formatting",
        "<b>Gras</b>, <i>italique</i>, et une liste <ul><li>un</li><li>deux</li></ul>.",
    ),
    ("line_breaks", "Ligne un<br>Ligne deux<br>Ligne trois"),
    ("punctuation", "Ponctuation : -- [ ] ( ) / . , ; : ! ? # & % + = * fin."),
    # Intentional confusable/typographic characters — that is what we are probing.
    ("quotes", "Apostrophe ' et \" et « guillemets » et typographique ’."),  # noqa: RUF001
    ("emoji_unicode", "Emoji 😀 🚀 ✅ symboles ☃ ∑ → et CJK 日本語 テスト."),
    ("long_2000_chars", "A" * 2000),
    (
        "html_injection",
        "<script>alert('xss')</script> texte </div> balise orpheline "
        "<img src=x onerror=1>.",
    ),
    ("sql_like", "Robert'); DROP TABLE requests;-- OR '1'='1' UNION SELECT."),
    ("path_like", "Chemins C:\\Windows\\system32 et /etc/passwd et ../../secret."),
]

# A minimal valid 1x1 transparent PNG (content is unverifiable via the client,
# but a real PNG makes the UI attachment preview meaningful).
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg=="
)

# (label, filename, content). Each filename carries a unique ASCII token
# ("pvfdocN") so the read-back can match it. html=False: filenames are literal.
DOC_PROBES: list[tuple[str, str, bytes]] = [
    ("ascii_txt", "pvfdoc1_validation.txt", b"Contenu ASCII simple.\nLigne deux.\n"),
    (
        "accented_txt",
        "pvfdoc2_accentué éàù.txt",
        "Contenu avec accents : café élève garçon.\n".encode(),
    ),
    ("png_binary", "pvfdoc3_pixel.png", TINY_PNG),
]


# --------------------------------------------------------------------------- #
# credential resolution — TEST instance only
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


def _resolve_int(env_names: tuple[str, ...], filename: str) -> int | None:
    value = _resolve(env_names, filename)
    return int(value) if value is not None else None


def _host(url: str) -> str:
    # urlsplit().hostname strips any userinfo/port and lowercases; fall back to
    # the first path segment for a bare host with no netloc.
    parsed = urlsplit(url if "//" in url else f"//{url}")
    return (parsed.hostname or parsed.path.split("/")[0]).lower()


def resolve_test_config() -> EasyvistaConfig | None:
    """Build config from the TEST credentials only; refuse the prod host.

    Returns ``EasyvistaConfig`` or ``None`` when credentials are unavailable.
    Raises ``SystemExit`` if the resolved host matches the recorded prod host.
    """
    from easyvista_python_client import EasyvistaConfig

    url = _resolve(("EASYVISTA_TEST_URL",), "easyvista_test_url")
    user = _resolve(
        ("EASYVISTA_TEST_USER", "EASYVISTA_TEST_ACCOUNT"), "easyvista_test_user"
    )
    token = _resolve(("EASYVISTA_TEST_TOKEN",), "easyvista_test_token")
    if not url or not token:
        return None

    root = url.rstrip("/")

    # Safety guard: never run against the production host. Read the recorded prod
    # URL from its specific env var or secret file (NOT the generic EASYVISTA_URL,
    # which could itself be the test URL and wrongly trip the guard).
    prod_url = _resolve(("EASYVISTA_PROD_URL",), "easyvista_prod_url")
    if prod_url and _host(root) == _host(prod_url):
        raise SystemExit(
            "REFUSING TO RUN: the resolved test host matches the recorded prod "
            "host. This validator writes real records and is test-only."
        )

    if "/api/" in root:
        server, _, rest = root.partition("/api/")
        version, _, account_tail = rest.partition("/")
        account = account_tail.split("/")[0]
        if not account:
            return None
        return EasyvistaConfig(
            server=server, account=account, token=token, api_version=version
        )
    if not user:
        return None
    return EasyvistaConfig(server=root, account=user, token=token)


# --------------------------------------------------------------------------- #
# probe bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class Probe:
    channel: str  # "description" | "comment" | "document" | "tolerance"
    label: str
    sent: str
    html: bool
    marker: str | None = None  # match token for comment/document read-back
    ref: str | None = None  # id captured at write time (action id / ticket rfc)
    verdict: str | None = None  # filled in during the run
    returned: str | None = None
    note: str = ""


def _ident_from(ticket: Request) -> str | None:
    """Best identifier for follow-up calls (RFC, else the HREF's trailing id)."""
    if getattr(ticket, "rfc_number", None):
        return ticket.rfc_number
    href = getattr(ticket, "href", None)
    if isinstance(href, str) and href:
        return href.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    return None


def _find_marked(
    records: Sequence[Document], marker: str, attrs: tuple[str, ...]
) -> str | None:
    """Return the first record's text (via named ``attrs``) that contains ``marker``.

    Used for documents, where we specifically want the filename field to compare.
    """
    for record in records:
        for attr in attrs:
            value = getattr(record, attr, None)
            if isinstance(value, str) and marker in value:
                return value
    return None


def _action_ident(action: Action) -> str | None:
    """The created action's id, when the API actually returns one.

    There used to be an HREF-parsing fallback here, on the assumption that a
    missing ``ACTION_ID`` could still be recovered from the create response's
    trailing HREF segment, the way a created ticket's RFC is. Verified live
    (see ``e221fe8`` and ``Action._derive_action_id_from_href``):
    ``POST requests/{rfc}/actions`` echoes an HREF naming the **parent
    request**, not the new action, and carries no ``ACTION_ID`` at all. That
    HREF's trailing segment is the ticket's own RFC number, not an action id,
    so parsing it could only ever produce a wrong value -- never a real one.
    The fallback is removed rather than fixed because there is nothing to
    fall back to: a created action's id is not recoverable from its create
    response by any means. ``_find_action_note`` already handles a ``None``
    ref by scanning every action on the ticket for the probe's marker.
    """
    aid = getattr(action, "action_id", None)
    return str(aid) if aid else None


# --------------------------------------------------------------------------- #
# live run
# --------------------------------------------------------------------------- #
@dataclass
class RunOptions:
    catalog_code: str
    origin: int
    department_id: int
    urgency_id: int
    impact_id: int
    action_type_id: int
    group_id: int
    title: str = "content fidelity validation please ignore"
    # Plain ASCII, no '.', '[', ']', '/', '--' tokens: the CREATE is not wrapped,
    # so a server-side content rejection (HTTP 590) here would abort the whole run.
    # All risky/rich content is exercised later through the wrapped write path.
    create_description: str = "Ticket created by the content fidelity validator"


def _write(probe: Probe, write: Callable[[], object]) -> None:
    """Run a write, recording REJECTED (590) / ERROR on failure, else leaving
    ``verdict`` pending (``None``) for the read-back pass."""
    from easyvista_python_client import EasyvistaError, EasyvistaValidationError

    try:
        write()
    except EasyvistaValidationError as exc:
        probe.verdict = REJECTED
        probe.note = f"HTTP {exc.status_code} code {exc.ev_code}: {exc.ev_message}"
    except EasyvistaError as exc:
        probe.verdict = "ERROR"
        probe.note = f"{type(exc).__name__}: {exc}"


def run_fidelity(client: EasyvistaClient, opts: RunOptions) -> tuple[str, list[Probe]]:
    """Create a ticket, write every probe, read back and classify.

    Returns ``(rfc, probes)``.
    """
    from easyvista_python_client import (
        PostAction,
        PostRequest,
        RequestUpdate,
    )

    probes: list[Probe] = []

    # 0. connectivity + auth smoke (read) — fail before creating anything.
    print("  [connect] search_tickets(max_rows=1) ...", flush=True)
    client.search_tickets(max_rows=1)

    # 1. create the ticket with a known-good, plain payload.
    print("  [create]  create_ticket(...) ...", flush=True)
    created = client.create_ticket(
        PostRequest(
            catalog_code=opts.catalog_code,
            title=opts.title,
            description=opts.create_description,
            origin=opts.origin,
            department_id=opts.department_id,
            urgency_id=opts.urgency_id,
            impact_id=opts.impact_id,
        )
    )
    rfc = _ident_from(created)
    if not rfc:
        raise RuntimeError("create_ticket returned neither an RFC nor a usable HREF")
    print(f"  [create]  ticket = {rfc}", flush=True)

    # 2. rich HTML description via update.
    desc = Probe("description", "rich_html_update", RICH_DESCRIPTION_HTML, html=True)
    probes.append(desc)
    print("  [write]   description (rich HTML) via update_ticket ...", flush=True)
    _write(
        desc,
        lambda: client.update_ticket(
            rfc, RequestUpdate(description=RICH_DESCRIPTION_HTML)
        ),
    )

    # 3. comments via create_action — TWO attempts. EasyVista attaches the note to
    #    a parent workflow action; the FIRST succeeds, the SECOND typically 590s
    #    ("many parent actions found"). Both outcomes are recorded. The note text
    #    lands at actions/{id}/description (NOT the inline COMMENT column), so the
    #    created action's id is captured here for the read-back memo resolve.
    for index in range(1, 3):
        label, payload = COMMENT_PROBES[index - 1]
        marker = f"PVFC{index:02d}"
        sent = f"{marker} {payload}"
        probe = Probe(
            "comment", f"create_action_{index}_{label}", sent, html=True, marker=marker
        )
        probes.append(probe)
        print(f"  [write]   comment {marker} via create_action ...", flush=True)

        def _post(p: Probe = probe, s: str = sent) -> None:
            action = client.create_action(
                rfc,
                PostAction(
                    action_type_id=opts.action_type_id,
                    group_id=opts.group_id,
                    description=s,
                ),
            )
            p.ref = _action_ident(action)

        _write(probe, _post)

    # 4. document probes.
    for label, filename, content in DOC_PROBES:
        marker = filename.split("_", 1)[0]  # "pvfdocN"
        probe = Probe("document", label, filename, html=False, marker=marker)
        probes.append(probe)
        print(f"  [write]   document {filename} ...", flush=True)
        _write(
            probe,
            partial(client.add_document, rfc, filename=filename, content=content),
        )

    # 5. read back and classify.
    print("  [read]    resolving comment / actions / documents ...", flush=True)
    _read_back_and_classify(client, rfc, probes)
    return rfc, probes


def _safe_resolve(client: EasyvistaClient, path: str) -> str | None:
    """resolve_memo that returns None on any transport error (403/404/etc.)."""
    from easyvista_python_client import EasyvistaError

    try:
        return client.resolve_memo(path)
    except EasyvistaError:
        return None


def _find_action_note(
    client: EasyvistaClient, actions: Sequence[Action], probe: Probe
) -> str | None:
    """Return the note text of the action this comment probe created.

    The note lives at ``actions/{id}/description`` (verified live) — the inline
    ``COMMENT`` column is null. Try the id captured at write time first (fast path),
    then fall back to scanning every action's memo, since the create response's id
    is not always the note-bearing action. Returns the first memo containing the
    probe marker.
    """
    marker = probe.marker or ""
    ids: list[str] = []
    if probe.ref:
        ids.append(probe.ref)
    ids.extend(str(a.action_id) for a in actions if a.action_id is not None)
    seen: set[str] = set()
    for aid in ids:
        if aid in seen:
            continue
        seen.add(aid)
        for sub in ("description", "comment"):
            memo = _safe_resolve(client, f"actions/{aid}/{sub}")
            if memo and marker in memo:
                return memo
    return None


def _read_back_and_classify(
    client: EasyvistaClient, rfc: str, probes: list[Probe]
) -> None:
    """Fill each pending probe's verdict from the read-back.

    The ``description`` write surfaces at the ``/comment`` memo (verified live);
    ``/description`` is a separate, here-empty memo — read both and use whichever
    carries content. Comment notes are read from ``actions/{id}/description``.
    A blocked/errored list marks its channel UNVERIFIABLE rather than losing the
    whole report.
    """
    from easyvista_python_client import EasyvistaError

    comment_memo = _safe_resolve(client, f"requests/{rfc}/comment")
    description_memo = _safe_resolve(client, f"requests/{rfc}/description")

    try:
        actions = client.list_actions(rfc)
        actions_blocked, actions_note = False, ""
    except EasyvistaError as exc:
        actions, actions_blocked = [], True
        actions_note = f"list_actions unavailable ({type(exc).__name__})"
    try:
        documents = client.list_documents(rfc)
        docs_blocked, docs_note = False, ""
    except EasyvistaError as exc:
        documents, docs_blocked = [], True
        docs_note = f"list_documents unavailable ({type(exc).__name__})"

    for probe in probes:
        if probe.verdict is not None:  # already REJECTED / ERROR at write time
            continue

        if probe.channel == "description":
            if comment_memo:
                probe.returned, endpoint = comment_memo, "/comment"
            else:
                probe.returned, endpoint = description_memo, "/description"
            probe.verdict = classify_fidelity(
                probe.sent, probe.returned, html=probe.html
            )
            probe.note = f"read at requests/<rfc>{endpoint}"

        elif probe.channel == "comment":
            if actions_blocked:
                probe.verdict, probe.note = UNVERIFIABLE, actions_note
                continue
            returned = _find_action_note(client, actions, probe)
            probe.returned = returned
            if returned is None:
                probe.verdict = MISSING
                probe.note = "action note not found (create rejected or memo empty)"
            else:
                probe.verdict = classify_fidelity(probe.sent, returned, html=probe.html)
                probe.note = "read at actions/{id}/description"

        elif probe.channel == "document":
            if docs_blocked:
                probe.verdict, probe.note = UNVERIFIABLE, docs_note
                continue
            returned = _find_marked(
                documents, probe.marker or "", ("filename", "name", "document")
            )
            probe.returned = returned
            if returned is None:
                probe.verdict = MISSING
                probe.note = "attachment not found in list_documents"
            else:
                probe.verdict = classify_fidelity(probe.sent, returned, html=False)
                probe.note = "filename compared; content UNVERIFIABLE (no download)"


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def _trunc(value: str | None, limit: int = 180) -> str:
    if value is None:
        return "<none>"
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…'"


def _print_verdict_table(probes: list[Probe], title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    width_ch = max((len(p.channel) for p in probes), default=9)
    width_lb = max((len(p.label) for p in probes), default=5)
    header = f"{'CHANNEL':<{width_ch}}  {'PROBE':<{width_lb}}  {'VERDICT':<12}  NOTE"
    print(header)
    print("-" * len(header))
    counts: dict[str, int] = {}
    for p in probes:
        verdict = p.verdict or "?"
        counts[verdict] = counts.get(verdict, 0) + 1
        print(
            f"{p.channel:<{width_ch}}  {p.label:<{width_lb}}  {verdict:<12}  {p.note}"
        )
    print("\nSummary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    # Detail for anything not byte-perfect, so markup/encoding changes are visible.
    interesting = [p for p in probes if p.verdict not in (EXACT, None)]
    if interesting:
        print("\n" + "-" * 78)
        print("DETAIL (sent -> returned) for non-EXACT probes")
        print("-" * 78)
        for p in interesting:
            print(f"\n[{p.channel}/{p.label}] {p.verdict}")
            print(f"  sent    : {_trunc(p.sent)}")
            print(f"  returned: {_trunc(p.returned)}")


def print_report(rfc: str, probes: list[Probe], client: EasyvistaClient) -> None:
    _print_verdict_table(probes, "CONTENT FIDELITY REPORT")

    # The API's own rendered view of the ticket.
    print("\n" + "-" * 78)
    print("API MARKDOWN VIEW  (client.get_ticket_context(rfc).to_markdown())")
    print("-" * 78)
    try:
        print(client.get_ticket_context(rfc).to_markdown())
    except Exception as exc:  # report, don't crash the run
        print(f"  (could not render markdown: {type(exc).__name__}: {exc})")

    # Where to look.
    api_root = getattr(client.config, "api_root", "")
    server = getattr(client.config, "server", "")
    print("-" * 78)
    print(f"Ticket RFC : {rfc}   (LEFT OPEN -- inspect, then --close {rfc})")
    if api_root:
        print(f"API JSON   : {api_root}/requests/{rfc}")
    if server:
        print(f"Web UI     : {server}  (log in and search RFC {rfc})")
    print("=" * 78)


# --------------------------------------------------------------------------- #
# opt-in content-tolerance sweep (one throwaway ticket per adversarial probe)
# --------------------------------------------------------------------------- #
def run_tolerance(
    client: EasyvistaClient,
    opts: RunOptions,
    status_guid: str,
    *,
    close_each: bool = True,
) -> list[Probe]:
    """Map per-content acceptance/fidelity through the description memo.

    ``create_action`` cannot add many notes to one ticket (parent-action
    ambiguity), so each adversarial probe gets its own ticket: create (safe body)
    -> ``update_ticket(description=probe)`` -> read back at ``/comment`` -> classify.
    Each probe ticket is closed right after unless ``close_each`` is False.
    """
    from easyvista_python_client import EasyvistaError, PostRequest, RequestUpdate

    results: list[Probe] = []
    for index, (label, payload) in enumerate(COMMENT_PROBES, start=1):
        probe = Probe("tolerance", label, payload, html=True)
        results.append(probe)
        print(f"  [tol {index:02d}] {label}: create+update ...", flush=True)
        try:
            created = client.create_ticket(
                PostRequest(
                    catalog_code=opts.catalog_code,
                    title=opts.title,
                    description=opts.create_description,
                    origin=opts.origin,
                    department_id=opts.department_id,
                    urgency_id=opts.urgency_id,
                    impact_id=opts.impact_id,
                )
            )
            rfc = _ident_from(created)
        except EasyvistaError as exc:
            probe.verdict = "ERROR"
            probe.note = f"ticket create failed ({type(exc).__name__})"
            continue
        probe.ref = rfc
        if rfc is None:
            probe.verdict = "ERROR"
            probe.note = "create returned neither an RFC nor a usable HREF"
            continue

        _write(
            probe,
            partial(client.update_ticket, rfc, RequestUpdate(description=payload)),
        )
        if probe.verdict is None:  # write succeeded -> classify what came back
            returned = _safe_resolve(
                client, f"requests/{rfc}/comment"
            ) or _safe_resolve(client, f"requests/{rfc}/description")
            probe.returned = returned
            probe.verdict = (
                MISSING if returned is None else classify_fidelity(payload, returned)
            )

        if close_each and rfc:
            try:
                client.close_ticket(
                    rfc,
                    status_guid=status_guid,
                    delete_actions=1,
                    comment="tolerance probe cleanup",
                )
                probe.note = f"ticket {rfc} closed"
            except EasyvistaError as exc:
                probe.note = (
                    f"ticket {rfc} left OPEN (close failed: {type(exc).__name__})"
                )
        elif rfc:
            probe.note = f"ticket {rfc} left OPEN"
        print(f"           -> {probe.verdict}", flush=True)
    return results


# --------------------------------------------------------------------------- #
# cleanup
# --------------------------------------------------------------------------- #
def do_close(client: EasyvistaClient, rfc: str, status_guid: str) -> None:
    client.close_ticket(
        rfc,
        status_guid=status_guid,
        delete_actions=1,
        comment="Cloture apres validation de fidelite du contenu",
    )
    print(f"Closed ticket {rfc}.")


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--close",
        metavar="RFC",
        help="close the named ticket (cleanup) and exit; creates nothing",
    )
    parser.add_argument(
        "--tolerance",
        action="store_true",
        help=(
            "opt-in: map per-content acceptance via the description memo, one "
            "throwaway ticket per adversarial probe (closed after unless "
            "--tolerance-keep-open). Does NOT run the main single-ticket flow."
        ),
    )
    parser.add_argument(
        "--tolerance-keep-open",
        action="store_true",
        help="with --tolerance, leave the probe tickets open instead of closing them",
    )
    parser.add_argument(
        "--catalog-code",
        default=_resolve(
            ("EASYVISTA_TEST_CATALOG_CODE",), "easyvista_test_catalog_code"
        ),
        help="catalog_code for the probe ticket (env EASYVISTA_TEST_CATALOG_CODE,"
        " or secrets/easyvista_test_catalog_code)",
    )
    parser.add_argument(
        "--origin",
        type=int,
        default=_resolve_int(("EASYVISTA_TEST_ORIGIN",), "easyvista_test_origin"),
        help="origin id for the probe ticket (env EASYVISTA_TEST_ORIGIN,"
        " or secrets/easyvista_test_origin)",
    )
    parser.add_argument(
        "--department",
        type=int,
        default=_resolve_int(
            ("EASYVISTA_TEST_DEPARTMENT_ID",), "easyvista_test_department_id"
        ),
        help="department id for the probe ticket (env EASYVISTA_TEST_DEPARTMENT_ID,"
        " or secrets/easyvista_test_department_id)",
    )
    parser.add_argument(
        "--urgency",
        type=int,
        default=_resolve_int(
            ("EASYVISTA_TEST_URGENCY_ID",), "easyvista_test_urgency_id"
        ),
        help="urgency id for the probe ticket (env EASYVISTA_TEST_URGENCY_ID,"
        " or secrets/easyvista_test_urgency_id)",
    )
    parser.add_argument(
        "--impact",
        type=int,
        default=_resolve_int(("EASYVISTA_TEST_IMPACT_ID",), "easyvista_test_impact_id"),
        help="impact id for the probe ticket (env EASYVISTA_TEST_IMPACT_ID,"
        " or secrets/easyvista_test_impact_id)",
    )
    parser.add_argument(
        "--action-type-id",
        type=int,
        default=_resolve_int(
            ("EASYVISTA_TEST_ACTION_TYPE_ID",), "easyvista_test_action_type_id"
        ),
        help="action_type_id for comment probes (env EASYVISTA_TEST_ACTION_TYPE_ID,"
        " or secrets/easyvista_test_action_type_id)",
    )
    parser.add_argument(
        "--group-id",
        type=int,
        default=_resolve_int(("EASYVISTA_TEST_GROUP_ID",), "easyvista_test_group_id"),
        help="group_id for comment probes (env EASYVISTA_TEST_GROUP_ID,"
        " or secrets/easyvista_test_group_id)",
    )
    parser.add_argument(
        "--status-guid",
        default=_resolve(("EASYVISTA_TEST_STATUS_GUID",), "easyvista_test_status_guid"),
        help="closed-status GUID for --close (env EASYVISTA_TEST_STATUS_GUID,"
        " or secrets/easyvista_test_status_guid)",
    )
    args = parser.parse_args()

    # Force UTF-8 on stdout so unicode probe content (emoji, CJK, arrows) never
    # crashes the console print on a legacy code page (e.g. Windows cp1252).
    # `reconfigure` exists on TextIOWrapper but not on the TextIO protocol that
    # sys.stdout is typed as, and stdout may be replaced by a stream without it.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Best-effort .env load so EASYVISTA_TEST_* in a .env are picked up.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except Exception:
        pass

    config = resolve_test_config()
    if config is None:
        print("No TEST credentials. Set EASYVISTA_TEST_URL + EASYVISTA_TEST_TOKEN")
        print("or add secrets/easyvista_test_url and secrets/easyvista_test_token.")
        return 2

    # These are per-instance and must not be hardcoded (see
    # integration_tests/conftest.py's live_write_config): fail clearly instead of
    # silently falling back to a baked-in value.
    if args.close:
        if not args.status_guid:
            print(
                "Missing closed-status GUID. Set EASYVISTA_TEST_STATUS_GUID"
                " (or secrets/easyvista_test_status_guid)."
            )
            return 2
    else:
        missing = []
        if not args.catalog_code:
            missing.append(
                "EASYVISTA_TEST_CATALOG_CODE (or secrets/easyvista_test_catalog_code)"
            )
        if args.origin is None:
            missing.append("EASYVISTA_TEST_ORIGIN (or secrets/easyvista_test_origin)")
        if args.department is None:
            missing.append(
                "EASYVISTA_TEST_DEPARTMENT_ID (or secrets/easyvista_test_department_id)"
            )
        if args.urgency is None:
            missing.append(
                "EASYVISTA_TEST_URGENCY_ID (or secrets/easyvista_test_urgency_id)"
            )
        if args.impact is None:
            missing.append(
                "EASYVISTA_TEST_IMPACT_ID (or secrets/easyvista_test_impact_id)"
            )
        if args.action_type_id is None:
            missing.append(
                "EASYVISTA_TEST_ACTION_TYPE_ID"
                " (or secrets/easyvista_test_action_type_id)"
            )
        if args.group_id is None:
            missing.append(
                "EASYVISTA_TEST_GROUP_ID (or secrets/easyvista_test_group_id)"
            )
        if args.tolerance and not args.tolerance_keep_open and not args.status_guid:
            missing.append(
                "EASYVISTA_TEST_STATUS_GUID (or secrets/easyvista_test_status_guid)"
            )
        if missing:
            print("Missing required instance config:")
            for item in missing:
                print(f"  - {item}")
            return 2

    from easyvista_python_client import EasyvistaClient

    print(f"Instance: {config.api_root}")
    with EasyvistaClient(config) as client:
        if args.close:
            do_close(client, args.close, args.status_guid)
            return 0

        opts = RunOptions(
            catalog_code=args.catalog_code,
            origin=args.origin,
            department_id=args.department,
            urgency_id=args.urgency,
            impact_id=args.impact,
            action_type_id=args.action_type_id,
            group_id=args.group_id,
        )

        if args.tolerance:
            try:
                results = run_tolerance(
                    client,
                    opts,
                    args.status_guid,
                    close_each=not args.tolerance_keep_open,
                )
            except Exception as exc:  # surface the failure clearly
                print(f"\nTOLERANCE RUN FAILED: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                return 1
            _print_verdict_table(
                results,
                "CONTENT TOLERANCE MAP (description memo; one ticket per probe)",
            )
            return 0

        try:
            rfc, probes = run_fidelity(client, opts)
        except Exception as exc:  # surface the failure clearly
            print(f"\nRUN FAILED before completion: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            return 1
        print_report(rfc, probes, client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
