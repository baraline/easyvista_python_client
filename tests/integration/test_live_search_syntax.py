"""Characterization of EasyVista's server-side ``search`` syntax.

These tests do NOT assert fixed record counts: this instance has hundreds of
departments and another user's will not. They assert *relationships* — chiefly
"count == unfiltered baseline", which proves EasyVista silently ignored the
filter and returned the whole table. That holds on any instance.

What the live probes established (full tables in ``task-1-report.md``):

* **Silent-ignore is real, and it is per-condition.** EasyVista drops any
  condition it cannot honour and applies whatever is left — no error. A search
  with nothing left to apply returns **every** row. This happens for
  structurally unparseable input (bare SQL-ish ``DEPARTMENT_FR LIKE "%TECH%"``,
  an unknown field, bare garbage) *and* for a well-formed condition on a field
  that is returned but not searchable — the ``*_PATH`` display columns
  (``SD_CATALOG_PATH``, ``DEPARTMENT_PATH``) and the sub-keys of a nested
  reference object (``STATUS_FR``, ``STATUS_GUID``).
  ``CATALOG_GUID`` is **not** an example of this: it is not returned at all and
  is merely an unknown field.
* **A type mismatch is a hard error, not an ignore.** A non-int value on an int
  column raises ``EasyvistaValidationError`` (HTTP 590). So a condition has
  three possible fates: honoured, silently dropped, or rejected outright.
* **A broken quote does NOT return the table.** ``DEPARTMENT_CODE:"X""`` still
  parses as a field expression; the value just swallows the junk and matches
  nothing, so it returns 0. The danger is real but it is *not* this shape.
* **``,`` is a genuine combinator:** AND across different fields, OR (an
  IN-list) among conditions on the *same* field — on ``departments`` and
  ``requests`` alike. This is the actual injection vector: an injected ``,``
  silently *widens* a same-field query. A ``,`` **inside** the quotes is a
  literal, so escaping the quote is what blocks it.
* **``;`` is not a combinator** — it is swallowed into the quoted value.
* **``~`` is exact-match, not "contains"** — identical to ``:``, on code-like
  fields (``DEPARTMENT_CODE``, ``ASSET_TAG``) and free-text label fields
  (``DEPARTMENT_FR``) alike. The published docs claiming otherwise are wrong.
* **No escape for an embedded ``"`` was found.** Raw, backslash-escaped, and
  doubled-quote renderings of a title containing a literal ``"`` all fail to
  match a ticket verifiably created with that exact title (full table in
  ``task-2-report.md``). ``escape_ev_value`` therefore rejects a value
  containing ``"`` rather than emit a query that silently cannot match.

Most tests here are read-only. ``test_embedded_quote_cannot_be_escaped`` is the
exception: it depends on the ``probe_tickets`` fixture, which creates two
tickets on the live instance and unconditionally closes both in teardown (see
``live_write_config`` / ``probe_tickets`` in ``conftest.py``). That fixture
additionally skips unless the instance-specific write config is present.

Opt in with ``--run-integration``; skipped without credentials.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import EasyvistaClient, EasyvistaError

pytestmark = pytest.mark.integration


def _count(client: EasyvistaClient, search: str | None = None) -> int:
    """Total matches for ``search`` on ``departments``, fetching no records."""
    result = client.search_departments(search=search, max_rows=1)
    return result.total_record_count or 0


def _count_tickets(client: EasyvistaClient, search: str | None = None) -> int:
    """Total matches for ``search`` on ``requests``, fetching no records."""
    result = client.search_tickets(search=search, max_rows=1)
    return result.total_record_count or 0


def _count_assets(client: EasyvistaClient, search: str | None = None) -> int:
    """Total matches for ``search`` on ``assets``, fetching no records."""
    result = client.search_assets(search=search, max_rows=1)
    return result.total_record_count or 0


@pytest.fixture(scope="session")
def baseline(live_client: EasyvistaClient) -> int:
    """Unfiltered department count — the "filter was ignored" tell."""
    total = _count(live_client)
    if total < 2:
        pytest.skip("need at least 2 departments to characterize search syntax")
    return total


@pytest.fixture(scope="session")
def sample_department_row(
    live_client: EasyvistaClient, sample_department_code: str
) -> tuple[str, int]:
    """The sample code paired with its real ``DEPARTMENT_ID``."""
    result = live_client.search_departments(
        search=f'DEPARTMENT_CODE:"{sample_department_code}"'
    )
    if not result.records or result.records[0].department_id is None:
        pytest.skip("sample department code did not resolve to a DEPARTMENT_ID")
    return sample_department_code, result.records[0].department_id


@pytest.fixture(scope="session")
def department_label(live_client: EasyvistaClient) -> str:
    """A populated free-text ``DEPARTMENT_FR`` label, long enough to have an infix.

    Free text rather than a code, so ``~`` can be probed on the field *type*
    the docs claim "contains" applies to.
    """
    for offset in (0, 25, 50):
        page = live_client.search_departments(max_rows=25, offset=offset)
        for dept in page.records:
            label = (dept.model_dump(by_alias=True).get("DEPARTMENT_FR") or "").strip()
            if len(label) >= 6:
                return label
    pytest.skip("no DEPARTMENT_FR label of 6+ chars on this instance")


@pytest.fixture(scope="session")
def requests_baseline(live_client: EasyvistaClient) -> int:
    """Unfiltered ticket count — the ``requests`` "filter was ignored" tell."""
    total = _count_tickets(live_client)
    if total < 2:
        pytest.skip("need at least 2 tickets to characterize search syntax")
    return total


@pytest.fixture(scope="session")
def ticket_with_catalog(live_client: EasyvistaClient) -> dict:
    """A live ticket row carrying both SD_CATALOG_PATH and SD_CATALOG_ID.

    The single-ticket GET is required: the default list projection returns
    neither field.
    """
    listed = live_client.search_tickets(max_rows=5)
    for row in listed.records:
        rfc = row.rfc_number
        if not rfc:
            continue
        full = live_client.get_ticket(rfc).model_dump(by_alias=True)
        if full.get("SD_CATALOG_PATH") and full.get("SD_CATALOG_ID"):
            return full
    pytest.skip("no sampled ticket carries both SD_CATALOG_PATH and SD_CATALOG_ID")


@pytest.fixture(scope="session")
def two_tickets(live_client: EasyvistaClient) -> tuple[dict, dict]:
    """Two distinct ticket rows, for generalizing the ``,`` semantics."""
    result = live_client.search_tickets(max_rows=2)
    if len(result.records) < 2:
        pytest.skip("need 2 tickets to characterize search syntax on requests")
    rows = [r.model_dump(by_alias=True) for r in result.records[:2]]
    if not all(r.get("RFC_NUMBER") and r.get("REQUEST_ID") for r in rows):
        pytest.skip("sample tickets lack RFC_NUMBER/REQUEST_ID")
    return rows[0], rows[1]


@pytest.fixture(scope="session")
def other_department_code(
    live_client: EasyvistaClient, sample_department_code: str
) -> str:
    """A second, distinct DEPARTMENT_CODE longer than 3 characters.

    Length > 3 matters: the ``~`` probe needs a code with a strict infix.
    """
    for offset in (0, 25, 50, 75):
        page = live_client.search_departments(max_rows=25, offset=offset)
        for dept in page.records:
            code = (dept.department_code or "").strip()
            if len(code) > 3 and code != sample_department_code:
                return code
    pytest.skip("no second DEPARTMENT_CODE longer than 3 chars on this instance")


# --- the filter is applied -------------------------------------------------


def test_exact_match_filter_is_honoured(live_client, sample_department_code, baseline):
    got = _count(live_client, f'DEPARTMENT_CODE:"{sample_department_code}"')
    assert 0 < got < baseline


# --- silent-ignore: real, for structurally unparseable search --------------


def test_bare_sql_like_is_silently_ignored(live_client, baseline):
    """The "an ignored filter returns the whole table" finding, reproduced.

    ``DEPARTMENT_FR LIKE "%TECH%"`` has no ``FIELD:"value"`` structure at all,
    so EasyVista drops the whole ``search`` and returns every row — without any
    error. This is the trap the filter builders exist to prevent.
    """
    assert _count(live_client, 'DEPARTMENT_FR LIKE "%TECH%"') == baseline


def test_unknown_field_is_silently_ignored(live_client, baseline):
    assert _count(live_client, 'NOT_A_FIELD:"x"') == baseline


def test_bare_garbage_is_silently_ignored(live_client, baseline):
    assert _count(live_client, "zzz") == baseline


# --- but a broken quote does NOT return the table --------------------------


def test_broken_quote_structure_matches_nothing_rather_than_everything(
    live_client, sample_department_code, baseline
):
    """A trailing/embedded ``"`` yields an honest 0, **not** the whole table.

    This refutes the intuition that the unescaped-quote injection shape
    (``find_departments('X"')`` → ``DEPARTMENT_CODE:"X""``) trips the
    silent-ignore path: the expression still parses as a field expression, the
    junk lands inside the value, and nothing matches. See instead
    ``test_comma_injection_silently_widens_a_same_field_query`` for the
    injection that does bite.
    """
    for search in (
        f'DEPARTMENT_CODE:"{sample_department_code}""',
        f'DEPARTMENT_CODE:"{sample_department_code}"y"',
        'DEPARTMENT_CODE:"X""',
    ):
        got = _count(live_client, search)
        assert got == 0
        assert got != baseline


def test_percent_is_a_literal_character_not_a_wildcard(
    live_client, sample_department_code, baseline
):
    """``%`` inside a quoted value is compared literally, not expanded as LIKE.

    A real SQL-``LIKE`` expansion would match at least the exact code itself
    (``got == exact``), so only a strict ``got == 0`` refutes it — a department
    code containing a literal ``%`` is not a realistic possibility.
    """
    exact = _count(live_client, f'DEPARTMENT_CODE:"{sample_department_code}"')
    assert exact > 0
    got = _count(live_client, f'DEPARTMENT_CODE:"{sample_department_code[:3]}%"')
    assert got != baseline
    assert got == 0


# --- combinators -----------------------------------------------------------


def test_comma_is_or_within_a_single_field(
    live_client, sample_department_code, other_department_code, baseline
):
    """Two conditions on the same field union together (an IN-list)."""
    a, b = sample_department_code, other_department_code
    count_a = _count(live_client, f'DEPARTMENT_CODE:"{a}"')
    count_b = _count(live_client, f'DEPARTMENT_CODE:"{b}"')
    both = _count(live_client, f'DEPARTMENT_CODE:"{a}",DEPARTMENT_CODE:"{b}"')
    # a != b and DEPARTMENT_CODE is exact-match, so the two sets are disjoint:
    # a union is their sum on any instance.
    assert both == count_a + count_b
    assert both < baseline


def test_comma_is_and_across_different_fields(
    live_client, sample_department_row, other_department_code, baseline
):
    """Conditions on different fields intersect."""
    code, real_id = sample_department_row
    exact = _count(live_client, f'DEPARTMENT_CODE:"{code}"')
    # Jointly true -> the intersection is the exact match itself.
    together = _count(
        live_client, f'DEPARTMENT_CODE:"{code}",DEPARTMENT_ID:"{real_id}"'
    )
    assert together == exact

    # Both sides individually true, jointly false -> empty. An OR would instead
    # return the (non-zero) union, so this also proves `,` is not OR here.
    other = other_department_code
    count_other = _count(live_client, f'DEPARTMENT_CODE:"{other}"')
    count_id = _count(live_client, f'DEPARTMENT_ID:"{real_id}"')
    assert count_other > 0 and count_id > 0
    disjoint = _count(
        live_client, f'DEPARTMENT_CODE:"{other}",DEPARTMENT_ID:"{real_id}"'
    )
    assert disjoint == 0
    assert disjoint < count_other + count_id


def test_comma_injection_silently_widens_a_same_field_query(
    live_client, sample_department_code, other_department_code, baseline
):
    """The real search-injection vector, reproduced end to end.

    ``find_departments`` builds ``DEPARTMENT_CODE:"{name}"`` by interpolation.
    A ``name`` carrying a quote plus a comma closes the value and appends a
    second condition, so the caller gets back a department they never asked
    for — silently, with no error. Not the whole table, but wrong results.
    """
    payload = f'{sample_department_code}",DEPARTMENT_CODE:"{other_department_code}'
    injected = f'DEPARTMENT_CODE:"{payload}"'  # what the call site emits today

    honest = _count(live_client, f'DEPARTMENT_CODE:"{sample_department_code}"')
    got = _count(live_client, injected)
    assert got > honest  # extra records smuggled in
    assert got < baseline  # but not the whole table


def test_semicolon_is_not_a_combinator(live_client, sample_department_row, baseline):
    """``;`` is swallowed into the quoted value rather than joining conditions.

    Both conditions are individually true and jointly true, so a real AND would
    return the exact match. It returns nothing instead — the value became the
    literal ``<code>";DEPARTMENT_ID:"<id>``. It is also not silently ignored.
    """
    code, real_id = sample_department_row
    assert _count(live_client, f'DEPARTMENT_CODE:"{code}"') > 0
    got = _count(live_client, f'DEPARTMENT_CODE:"{code}";DEPARTMENT_ID:"{real_id}"')
    assert got == 0
    assert got != baseline


# --- the tilde operator ----------------------------------------------------


def test_tilde_is_exact_match_not_contains(
    live_client, other_department_code, baseline
):
    """``FIELD~value`` behaves identically to ``FIELD:"value"``.

    Decisive probe: a strict infix of a code that verifiably exists. A real
    "contains" operator must match that code; exact-match cannot.
    """
    code = other_department_code
    infix = code[1:]
    if _count(live_client, f'DEPARTMENT_CODE:"{infix}"') != 0:
        pytest.skip(f"a department code equals {infix!r}; not a clean infix probe")

    # The full code is found by both operators, identically.
    assert 0 < _count(live_client, f"DEPARTMENT_CODE~{code}") < baseline
    assert _count(live_client, f"DEPARTMENT_CODE~{code}") == _count(
        live_client, f'DEPARTMENT_CODE:"{code}"'
    )
    # ...but the infix is found by neither: `~` is not "contains".
    assert _count(live_client, f"DEPARTMENT_CODE~{infix}") == 0


def test_tilde_is_exact_match_on_free_text_fields_too(
    live_client, department_label, baseline
):
    """``~`` is not "contains" on free text either — it is exact everywhere.

    ``DEPARTMENT_FR`` is a human label, not a code, so this rules out the
    "``~`` is contains, but only on free-text fields" hypothesis. The published
    docs (``user_guide.rst`` calls ``~`` "contains"; the README advertises
    ``ASSET_TAG~LAPTOP``) are wrong: ``~LAPTOP`` matches only a tag that *is*
    exactly ``LAPTOP``.
    """
    label = department_label
    infix = label[1:-1]
    if _count(live_client, f'DEPARTMENT_FR:"{infix}"') != 0:
        pytest.skip("a department label equals the infix; not a clean probe")

    exact = _count(live_client, f'DEPARTMENT_FR:"{label}"')
    assert 0 < exact < baseline
    # `~` on the full label agrees with `:` exactly...
    assert _count(live_client, f"DEPARTMENT_FR~{label}") == exact
    # ...and a strict infix of a label that verifiably exists matches nothing.
    # A real "contains" operator would have to return >= 1 here.
    assert _count(live_client, f"DEPARTMENT_FR~{infix}") == 0


def test_comma_inside_a_quoted_value_is_a_literal(
    live_client, sample_department_code, other_department_code, baseline
):
    """A ``,`` within the quotes does not combine — it is part of the value.

    This is what makes the injection fixable by escaping alone: an attacker
    cannot reach the combinator without first breaking out of the quotes.
    """
    a, b = sample_department_code, other_department_code
    combined = _count(live_client, f'DEPARTMENT_CODE:"{a}",DEPARTMENT_CODE:"{b}"')
    inside = _count(live_client, f'DEPARTMENT_CODE:"{a},{b}"')
    assert combined > 1  # outside the quotes the comma unions the two codes
    assert inside == 0  # inside them it is just a character no code contains
    assert inside != baseline  # and it is not silently ignored either


def test_tilde_on_asset_tag_is_exact_match(live_client):
    """The README's advertised ``ASSET_TAG~LAPTOP`` does not do what it implies.

    Probed on the very endpoint and field the README documents. ``~`` is exact
    there too, so ``ASSET_TAG~LAPTOP`` finds only an asset tagged exactly
    ``LAPTOP`` — not the laptops.
    """
    try:
        result = live_client.search_assets(max_rows=25)
    except EasyvistaError:
        pytest.skip("assets endpoint not reachable for this profile")
    asset_baseline = result.total_record_count or 0
    tag = ""
    for asset in result.records:
        candidate = (asset.asset_tag or "").strip()
        if len(candidate) >= 6:
            tag = candidate
            break
    if not tag:
        pytest.skip("no ASSET_TAG of 6+ chars to probe")

    infix = tag[1:-1]
    if _count_assets(live_client, f'ASSET_TAG:"{infix}"') != 0:
        pytest.skip("an asset tag equals the infix; not a clean probe")
    exact = _count_assets(live_client, f'ASSET_TAG:"{tag}"')
    assert 0 < exact < asset_baseline
    assert _count_assets(live_client, f"ASSET_TAG~{tag}") == exact
    # a real "contains" would match
    assert _count_assets(live_client, f"ASSET_TAG~{infix}") == 0


# --- generalization beyond `departments` -----------------------------------


def test_comma_semantics_hold_on_requests(live_client, two_tickets):
    """Same-field OR / cross-field AND is not a departments-only quirk."""
    first, second = two_tickets
    rfc, own_id = first["RFC_NUMBER"], first["REQUEST_ID"]
    other_rfc, other_id = second["RFC_NUMBER"], second["REQUEST_ID"]

    one = _count_tickets(live_client, f'RFC_NUMBER:"{rfc}"')
    assert one > 0

    # Same field -> OR (union of two distinct, individually-present tickets).
    both = _count_tickets(live_client, f'RFC_NUMBER:"{rfc}",RFC_NUMBER:"{other_rfc}"')
    assert both == one + _count_tickets(live_client, f'RFC_NUMBER:"{other_rfc}"')

    # Different fields -> AND. Jointly true keeps the ticket...
    together = _count_tickets(live_client, f'RFC_NUMBER:"{rfc}",REQUEST_ID:"{own_id}"')
    assert together == one
    # ...and jointly false drops it, though both sides are individually true.
    assert _count_tickets(live_client, f'REQUEST_ID:"{other_id}"') > 0
    disjoint = _count_tickets(
        live_client, f'RFC_NUMBER:"{rfc}",REQUEST_ID:"{other_id}"'
    )
    assert disjoint == 0


def test_semicolon_is_not_a_combinator_on_requests(live_client, two_tickets):
    first, second = two_tickets
    got = _count_tickets(
        live_client,
        f'RFC_NUMBER:"{first["RFC_NUMBER"]}";RFC_NUMBER:"{second["RFC_NUMBER"]}"',
    )
    assert got == 0


def test_a_returned_field_is_not_necessarily_searchable(
    live_client, ticket_with_catalog, requests_baseline
):
    """``SD_CATALOG_PATH`` is returned and populated, but searching it is ignored.

    The nastiest shape of the silent-ignore trap, and one no amount of escaping
    can fix: the filter is well-formed, the field is real and comes back on every
    ticket, and the server still drops the condition and returns everything.

    Three assertions are needed, and each kills a different rival explanation:

    1. the field is **returned** on this very ticket -> it is not an unknown field;
    2. the searched value is **read off that ticket**, so it demonstrably exists
       -> ``== baseline`` cannot mean "matches nothing";
    3. the ``*_ID`` sibling from the same ticket **filters** -> ``== baseline``
       cannot mean "this ticket set is unfilterable".

    The version of this test that used ``CATALOG_GUID`` had only a bogus value on
    a field that does not exist, so its single assertion had two causes and it
    proved nothing. Do not weaken this back into that shape.
    """
    baseline = requests_baseline
    path_value = ticket_with_catalog["SD_CATALOG_PATH"]
    id_value = ticket_with_catalog["SD_CATALOG_ID"]

    # 1. returned on this ticket (the fixture guarantees it; assert it anyway --
    #    it is the premise the whole test rests on).
    assert path_value

    # 2. a real, existing value on the path column -> whole table.
    assert _count_tickets(live_client, f'SD_CATALOG_PATH:"{path_value}"') == baseline

    # 3. the sibling id, same ticket, really filters.
    by_id = _count_tickets(live_client, f'SD_CATALOG_ID:"{id_value}"')
    assert 0 < by_id < baseline


def test_a_nested_reference_subkey_is_not_searchable(
    live_client, ticket_with_catalog, requests_baseline
):
    """``STATUS_FR``/``STATUS_EN`` live *inside* the nested STATUS object, so they
    are not top-level columns and a filter naming one is silently ignored.

    This is the test that would have caught the ``STATUS_EN`` example shipped in
    the README. It reads whichever language sub-key the instance populates rather
    than hardcoding one, so it is reproducible on an English instance too.
    """
    status = ticket_with_catalog.get("STATUS")
    if not isinstance(status, dict):
        pytest.skip("sampled ticket has no nested STATUS object")

    # Capture the sub-key and its value together: picking the key afterwards by
    # matching on the value would pair the wrong key when two sub-keys share a
    # value. `key` is whatever this instance populates (STATUS_FR here).
    pair = next(
        (
            (k, v)
            for k, v in status.items()
            if k.upper().startswith("STATUS_")
            and k.upper() not in {"STATUS_ID", "STATUS_GUID"}
            and isinstance(v, str)
            and v.strip()
        ),
        None,
    )
    status_id = ticket_with_catalog.get("STATUS_ID") or status.get("STATUS_ID")
    if pair is None or not status_id:
        pytest.skip("sampled ticket has no populated STATUS label + STATUS_ID pair")
    key, label = pair

    # A real label, off this very ticket, on the nested sub-key -> whole table.
    assert _count_tickets(live_client, f'{key}:"{label}"') == requests_baseline
    # ...while the top-level id from the same ticket filters.
    by_id = _count_tickets(live_client, f'STATUS_ID:"{status_id}"')
    assert 0 < by_id < requests_baseline


def test_catalog_guid_is_indistinguishable_from_an_unknown_field(
    live_client, requests_baseline
):
    """Pins the corrected belief so it cannot be re-derived wrongly.

    ``CATALOG_GUID`` was long documented as "returned but unsearchable". It is
    not returned at all (0/25 live single-ticket GETs) -- it is simply not a field
    on ``requests``, and behaves exactly like a typo. Asserting the *equality*
    with an unknown field is what distinguishes the two hypotheses.
    """
    bogus_guid = "{00000000-0000-0000-0000-000000000000}"
    as_guid = _count_tickets(live_client, f'CATALOG_GUID:"{bogus_guid}"')
    as_unknown = _count_tickets(live_client, 'NO_SUCH_FIELD_XYZ:"x"')
    assert as_guid == as_unknown == requests_baseline


def test_an_ignored_condition_is_dropped_per_condition(
    live_client, two_tickets, ticket_with_catalog, requests_baseline
):
    """An ignored condition is dropped; the surviving conditions still apply.

    ``RFC_NUMBER:"<real>",SD_CATALOG_PATH:"<real>"`` returns the one ticket: the
    unsearchable half evaporates rather than poisoning the whole query. Without
    this, "silently ignored" could have meant the *entire* search was discarded.

    Uses ``SD_CATALOG_PATH`` -- a field proven returned-but-ignored with a real
    value -- rather than the old ``CATALOG_GUID``, which was merely unknown.
    """
    rfc = two_tickets[0]["RFC_NUMBER"]
    path_value = ticket_with_catalog["SD_CATALOG_PATH"]

    one = _count_tickets(live_client, f'RFC_NUMBER:"{rfc}"')
    assert one == 1  # RFC_NUMBER is unique; a weaker `> 0` would hide a widened query

    combined = _count_tickets(
        live_client, f'RFC_NUMBER:"{rfc}",SD_CATALOG_PATH:"{path_value}"'
    )
    assert combined == one
    assert combined < requests_baseline  # the surviving condition really applied


# --- Phase B: no escape for an embedded `"` exists --------------------------


def test_embedded_quote_cannot_be_escaped(live_client, probe_tickets):
    """No rendering makes a literal ``"`` searchable, so ``escape_ev_value``
    rejects it rather than emitting a value that silently fails to match.

    Two self-closing probe tickets establish this live, guarded by two
    preconditions that must hold before the verdict means anything:

    1. A quote-free control (``TITLE:"EVCLI{nonce}A"``) proves ``TITLE`` is
       searchable and populated on create at all -- without it, a failure to
       match the quoted ticket would be meaningless.
    2. Probe B's *stored* title still contains a literal ``"``. If the instance
       silently stripped the quote on create, all three candidates would return
       0 and this test would pass for entirely the wrong reason: the true
       conclusion would be "there was never a quote in the data to match", not
       "no escape exists". ``escape_ev_value`` rejects ``"`` on the strength of
       this verdict, so the premise underneath it is asserted, not assumed.

    With both holding, each of the three candidate renderings of the quoted
    title (raw, backslash-escaped, doubled-quote) for ``EVCLI{nonce}B 22"
    monitor`` is asserted to return exactly 0, not merely ``!= 1``: a
    silently-ignored filter also returns something other than 1 (the whole,
    unfiltered table), so ``!= 1`` cannot tell "no escape exists" apart from
    "the filter was dropped". Only ``== 0`` -- an honest, targeted no-match --
    actually refutes "an escape exists".

    ``TITLE`` is not a declared field on :class:`Request`, so it is read via
    ``model_dump(by_alias=True)`` (``extra="allow"`` preserves it), matching how
    the other tests here reach undeclared fields.
    """
    nonce, _rfc_control, rfc_quoted = probe_tickets
    assert _count_tickets(live_client, f'TITLE:"EVCLI{nonce}A"') == 1  # control

    probe_b = live_client.get_ticket(rfc_quoted)
    stored_title = probe_b.model_dump(by_alias=True).get("TITLE")
    assert stored_title, f"probe B returned no TITLE to check (got {stored_title!r})"
    assert '"' in stored_title, (
        "probe B's stored title lost its literal quote "
        f'({stored_title!r}) -- this instance strips `"` on create, so the '
        "escape question is unanswerable here and a 0 from every candidate "
        "below would prove nothing about escaping"
    )

    for search in (
        f'TITLE:"EVCLI{nonce}B 22" monitor"',
        f'TITLE:"EVCLI{nonce}B 22\\" monitor"',
        f'TITLE:"EVCLI{nonce}B 22"" monitor"',
    ):
        assert _count_tickets(live_client, search) == 0


# --- a third fate: a hard type-mismatch error -------------------------------


def test_type_mismatch_on_an_int_column_raises_rather_than_being_ignored(
    live_client, requests_baseline
):
    """The search grammar's **third** outcome: a hard error.

    A non-int value on an int column fails the server-side SQL conversion and
    surfaces as EasyvistaValidationError (HTTP 590) -- it is neither matched nor
    silently ignored. The int-valued half of the pair is what makes this
    meaningful: it proves the column is fine and the *type* is what was rejected.
    """
    with pytest.raises(EasyvistaError):
        _count_tickets(live_client, 'STATUS_ID:"ZZ-NOT-AN-INT"')

    # Same column, type-correct bogus value -> honest 0, no error. This is the
    # half that makes the raise meaningful: it proves the column works and the
    # *type* was what got rejected. `== 0` also rules out a silent ignore, since
    # requests_baseline is >= 2 by that fixture's own guard.
    assert _count_tickets(live_client, 'STATUS_ID:"999999999"') == 0
