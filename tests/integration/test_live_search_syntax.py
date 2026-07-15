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
  that simply is not searchable (``CATALOG_GUID`` on ``requests``).
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

Read-only. Opt in with ``--run-integration``; skipped without credentials.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import EasyvistaClient, EasyvistaError

pytestmark = pytest.mark.integration

# A syntactically valid GUID that matches no record — the spec's synthetic
# convention. On a searchable field it yields 0; on an ignored one, everything.
_BOGUS_GUID = "00000000-0000-0000-0000-000000000000"


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
def catalog_guid_is_unsearchable(
    live_client: EasyvistaClient, requests_baseline: int
) -> None:
    """Skip unless ``CATALOG_GUID`` is still a silently-ignored field here.

    A precondition, not an assertion: it lets the per-condition test below stay
    meaningful on an instance where this particular field became searchable.
    """
    got = _count_tickets(live_client, f'CATALOG_GUID:"{_BOGUS_GUID}"')
    if got != requests_baseline:
        pytest.skip("CATALOG_GUID is searchable here; no ignored field to compose with")


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


def test_a_returned_field_is_not_necessarily_searchable(live_client, requests_baseline):
    """``CATALOG_GUID`` is modelled and returned, but searching it is ignored.

    The nastiest shape of the silent-ignore trap, and one no amount of escaping
    can fix: the filter is perfectly well-formed, the field is real and comes
    back on every record, yet the condition is dropped and the caller gets the
    whole table.

    Deliberately **not** guarded by a skip: this asserts a property of the API,
    not of this instance's data, so if an EasyVista version or configuration
    makes ``CATALOG_GUID`` searchable, this test *should* fail and tell us the
    fact changed. Skipping on "the assertion no longer holds" would make the
    test vacuous. The contrast against ``RFC_NUMBER`` is what pins it down: a
    bogus value on a *searchable* field returns 0, on an ignored field the
    whole table.
    """
    baseline = requests_baseline
    bogus_on_ignored = _count_tickets(live_client, f'CATALOG_GUID:"{_BOGUS_GUID}"')
    bogus_on_searchable = _count_tickets(live_client, 'RFC_NUMBER:"EVCLI-NO-SUCH"')

    assert bogus_on_searchable == 0  # RFC_NUMBER really is searchable
    assert bogus_on_ignored == baseline  # CATALOG_GUID really is not
    assert bogus_on_ignored > bogus_on_searchable


def test_silent_ignore_is_per_condition_not_all_or_nothing(
    live_client, two_tickets, catalog_guid_is_unsearchable
):
    """An ignored condition is dropped; the surviving conditions still apply.

    ``RFC_NUMBER:"<real>",CATALOG_GUID:"<bogus>"`` returns the one ticket: the
    unsearchable half evaporates rather than poisoning the whole query. Without
    this, "silently ignored" could have meant the *entire* search was discarded.

    The fixture guard is meaningful here (unlike on the test above): the
    precondition "CATALOG_GUID is unsearchable" is a *different* proposition
    from the assertion "the ignore is per-condition", so skipping when the
    precondition fails leaves a real assertion behind.
    """
    rfc = two_tickets[0]["RFC_NUMBER"]
    one = _count_tickets(live_client, f'RFC_NUMBER:"{rfc}"')
    assert one > 0
    combined = _count_tickets(
        live_client, f'RFC_NUMBER:"{rfc}",CATALOG_GUID:"{_BOGUS_GUID}"'
    )
    assert combined == one
