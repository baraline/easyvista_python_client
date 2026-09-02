"""Live, READ-ONLY profile of the instance's discovery surface.

Every call here is a GET: nothing is created, closed, updated or uploaded, so
unlike ``scripts/validate_docs_examples.py`` this cannot leak a ticket. Bounded
deliberately -- ``sample_size=20`` and ``action_sample_tickets=1`` -- because
the ``offset``/``@next`` contract is unverified on the actions endpoint (see
``iter_actions``), so an instance that ignores ``offset`` would otherwise
repeat page one forever.

Credential-gated like the rest of ``integration_tests/`` and never run in CI.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import EasyvistaClient, InstanceProfile

pytestmark = pytest.mark.integration

BASELINE = "2025.3"

#: The four names the instance's OpenAPI declares no list route for. This is a
#: topology fact read from the spec's ``paths`` (tier 2), not a 403 anyone
#: measured -- so discovery reports them as ``no-route`` rather than as denied.
ROUTELESS = ("IMPACT", "SEVERITY", "ORIGIN", "ACTION_TYPE")


def test_describe_instance_profiles_the_live_deployment(
    live_client: EasyvistaClient,
) -> None:
    profile = live_client.describe_instance(
        include_spec=True, sample_size=20, action_sample_tickets=1
    )
    assert isinstance(profile, InstanceProfile)

    assert profile.version is not None
    assert BASELINE in profile.version, (
        f"instance reports {profile.version!r}, but this package is written "
        f"against {BASELINE}"
    )
    assert "/requests" in profile.spec_paths or "requests" in profile.spec_paths

    # Read the gaps before believing any of them. A total outage looks exactly
    # like a bare instance EXCEPT that every gap is named here.
    for name in ROUTELESS:
        reason = profile.unavailable.get(name, "")
        assert reason.startswith("no-route"), (
            f"{name} should be reported as routeless, got {reason!r}"
        )

    statuses = profile.references.get("STATUS", [])
    assert statuses, (
        "no statuses discovered; check profile.unavailable['STATUS'] -- a "
        "denial and an empty table are different things"
    )
    # The GUID is the value set_status and close_ticket actually address a
    # status by, and it is only ever readable off a sampled ticket.
    assert any(s.guid for s in statuses), (
        "no discovered status carried a STATUS_GUID; the sample reached no "
        "ticket, or the nested STATUS object stopped carrying one"
    )


def test_get_api_spec_survives_the_201_that_a_status_check_would_skip(
    live_client: EasyvistaClient,
) -> None:
    """The client's transport gates on ``is_success``, so a 201 is fine.

    ``test_live_baseline_version`` pins the raw 201 with a bare httpx call --
    it has to, because this method hides the status code. This one proves the
    document still arrives through the client.
    """
    document = live_client.get_api_spec()
    assert BASELINE in document["info"]["description"]
    assert document["paths"]
