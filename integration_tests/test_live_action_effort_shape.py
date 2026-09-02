"""Pin the task-vs-action facts in ``docs/vendor-api-reference.md``.

**READ-ONLY.** Like ``test_live_baseline_version.py`` this module creates,
updates and closes nothing: it issues ``GET actions`` with an explicit
projection and reads the instance's own OpenAPI ``paths``. It is safe to run on
its own against a live instance.

Two claims are pinned, both of which the package's types and docstrings now
depend on:

1. The effort columns parse off real records, and the ``""`` sentinel stays
   distinguishable from a real zero.
2. There is no task read route, so a task can only be read back as an action.

Credential-gated like the rest of ``integration_tests/`` and never run in CI.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from easyvista_python_client import Action, EasyvistaClient

pytestmark = pytest.mark.integration

# Wide enough to see the shape; the default list projection returns none of it.
_PROJECTION = [
    "ACTION_ID",
    "ACTION_TYPE_ID",
    "WORKFLOW_ID",
    "ELAPSED_TIME",
    "TIME_COST",
    "CONTRACTUAL_COST",
    "START_DATE_UT",
    "END_DATE_UT",
]


@pytest.fixture(scope="module")
def action_rows(live_client: EasyvistaClient) -> list[dict]:
    """One page of raw ``GET actions`` rows, projected. Read-only."""
    data = live_client.send(
        "GET",
        "actions",
        params={"fields": ",".join(_PROJECTION), "max_rows": 500},
    )
    rows = data.get("records") or []
    if not rows:
        pytest.skip("instance has no action records to sample")
    return rows


def test_the_effort_columns_parse_off_every_sampled_row(
    action_rows: list[dict],
) -> None:
    """``Action`` validates real rows rather than raising on their formats.

    This is the guard for ``_parse_ev_decimal``'s deliberate strictness: it
    refuses a grouping separator and three-or-more fraction digits, and the
    descriptor validates a page in a list comprehension, so one such amount
    would fail a whole ``list_actions`` call. Magnitude is not a trigger --
    ``'1000,00'`` parses. If a refused format ever appears on this instance, it
    fails here first with the literal in hand.
    """
    for row in action_rows:
        action = Action.model_validate(row)
        assert action.elapsed_time is None or isinstance(action.elapsed_time, int)
        for cost in (action.time_cost, action.contractual_cost):
            assert cost is None or isinstance(cost, Decimal)
        for stamp in (action.start_date_ut, action.end_date_ut):
            assert stamp is None or (
                isinstance(stamp, datetime) and stamp.tzinfo is not None
            )


def test_the_empty_sentinel_and_a_real_zero_stay_distinguishable(
    action_rows: list[dict],
) -> None:
    """The distinction the connector depends on, asserted on live data.

    ``""`` means the column does not apply; ``"0"`` that it applies and is
    zero. Skips rather than fails if this instance happens to carry only one of
    the two -- absence of a mixed sample is not evidence against the rule.
    """
    absent = [r for r in action_rows if r.get("ELAPSED_TIME") == ""]
    zero = [r for r in action_rows if r.get("ELAPSED_TIME") == "0"]
    if not absent or not zero:
        pytest.skip(
            "no mixed sample on this page "
            f"({len(absent)} empty, {len(zero)} zero ELAPSED_TIME)"
        )
    assert Action.model_validate(absent[0]).elapsed_time is None
    assert Action.model_validate(zero[0]).elapsed_time == 0


def test_effort_recorded_does_not_imply_a_workflow_row(
    action_rows: list[dict],
) -> None:
    """Refutes the heuristic ``is_workflow_generated``'s docstring warns about.

    Measured 2026-09-02 on two deployments: rows with no ``WORKFLOW_ID`` carry a
    non-empty ``ELAPSED_TIME`` (public comments among them), and rows with one
    carry an empty ``ELAPSED_TIME``. Either direction existing is enough to
    show the columns do not classify the record; this asserts the direction that
    would silently drop comments from a timeline sync.
    """
    actions = [Action.model_validate(row) for row in action_rows]
    counter_examples = [
        a for a in actions if a.elapsed_time is not None and not a.is_workflow_generated
    ]
    if not counter_examples:
        pytest.skip("no non-workflow row on this page records effort")

    # The refutation itself: a row the heuristic would call a time-tracking or
    # workflow entry, which carries no WORKFLOW_ID at all.
    sample = counter_examples[0]
    assert sample.elapsed_time is not None
    assert sample.workflow_id is None
    assert sample.is_workflow_generated is False, (
        f"action {sample.action_id} (type {sample.action_type_id}) records "
        f"elapsed_time={sample.elapsed_time} with no WORKFLOW_ID, so 'effort "
        "set => workflow or time-tracking row' cannot classify a timeline entry"
    )


def test_there_is_no_task_read_route(live_client: EasyvistaClient) -> None:
    """``tasks`` is POST-only, which is why ``create_task`` returns an ``Action``.

    Tier 2 -- the instance's own ``paths``, authoritative for this deployment.
    Deliberately not asserted from a 403 on a GET: this API answers 403 for an
    absent route as readily as for a denied one.
    """
    paths = live_client.get_api_spec().get("paths") or {}
    task_paths = {
        path: verbs for path, verbs in paths.items() if "task" in path.lower()
    }
    assert task_paths, "no tasks route declared at all; create_task cannot work"
    for path, verbs in task_paths.items():
        declared = {
            verb.upper()
            for verb in verbs or {}
            if verb.lower() in {"get", "post", "put", "patch", "delete"}
        }
        assert declared == {"POST"}, (
            f"{path} declares {sorted(declared)}; this package documents the "
            "tasks route as create-only and has no list_tasks because of it"
        )

    # The corollary: the action routes are the only way to read one back.
    assert "GET" in {v.upper() for v in paths.get("/actions", {})}
