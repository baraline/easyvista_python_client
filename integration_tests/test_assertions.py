"""Unit tests for the P2 assertion helpers. No credentials, no network.

Marked ``integration`` by this directory's collection hook (so CI deselects
them), but they run anywhere a plain ``pytest`` runs.

Note what the message-only tests below do **not** cover, and why the rendered-
output tests at the bottom of this file exist: a failure message is not the
whole of what pytest prints. It also renders each traceback frame's arguments,
which is a live record for a helper call and a live *fixture* for the test
itself. Every assertion here could pass while the suite still printed a whole
ticket payload -- and did, until those tests were added.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from integration_tests._assertions import (
    assert_populated,
    assert_shape,
    require_field,
)
from integration_tests.conftest import pytest_collection_modifyitems

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _Falsy:
    """A falsy value whose repr would be recognisable if it leaked.

    Stands in for live data (a name, an e-mail address): the tests below check
    that the failure message is built from the label alone, so this repr never
    appears in it.
    """

    def __init__(self, text: str) -> None:
        self.text = text

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return self.text


def test_assert_populated_accepts_a_truthy_value():
    assert_populated("EVCLI0123456789", "TITLE")


def test_assert_populated_message_names_only_the_label():
    with pytest.raises(AssertionError) as info:
        assert_populated("", "REQUESTOR")
    assert str(info.value) == "REQUESTOR is empty"


def test_assert_populated_message_excludes_the_value():
    with pytest.raises(AssertionError) as info:
        assert_populated(_Falsy("A Real Person"), "REQUESTOR")
    assert "A Real Person" not in str(info.value)


def test_assert_shape_accepts_a_matching_type():
    assert_shape("text", str, "DESCRIPTION")
    assert_shape(3, (int, str), "SLA_ID")


def test_assert_shape_message_excludes_the_value():
    with pytest.raises(AssertionError) as info:
        assert_shape(_Falsy("someone@example.test"), int, "REQUESTOR_ID")
    message = str(info.value)
    assert "REQUESTOR_ID" in message
    assert "someone@example.test" not in message


def test_require_field_returns_the_value_case_insensitively():
    assert require_field({"TITLE": "EVCLI0123"}, "title") == "EVCLI0123"


def test_require_field_reads_an_easyvista_model():
    from easyvista_python_client import Request

    ticket = Request.model_validate({"RFC_NUMBER": "I1", "E_GTR_STATUS": "OK"})
    assert require_field(ticket, "E_GTR_STATUS") == "OK"


def test_require_field_treats_zero_as_present():
    # `require_field` gates on `value is None or value == ""`, NOT on
    # truthiness. Simplifying it to `if not value` would pass every other test
    # in this file, but a field that is legitimately 0 -- a duration, a count --
    # would start silently SKIPPING its test: the suite stays green while the
    # coverage disappears, in the very helper that enforces P1.
    #
    # The skip has to be caught and converted, not allowed to propagate: a test
    # that merely calls the helper would itself be reported SKIPPED under the
    # regression, which is exactly the quiet false-pass being guarded against.
    try:
        returned = require_field({"E_GTI_UT": 0}, "E_GTI_UT")
    except pytest.skip.Exception:
        pytest.fail("require_field skipped a value of 0 instead of returning it")
    assert returned == 0


def test_require_field_treats_false_as_present():
    # The boolean twin of the case above, and the same skip-to-failure
    # conversion for the same reason.
    try:
        returned = require_field({"E_GTR_STATUS": False}, "E_GTR_STATUS")
    except pytest.skip.Exception:
        pytest.fail("require_field skipped a value of False instead of returning it")
    assert returned is False


def test_require_field_skips_when_the_field_is_absent():
    with pytest.raises(pytest.skip.Exception) as info:
        require_field({"TITLE": "x"}, "E_GTR_STATUS")
    assert "E_GTR_STATUS" in str(info.value)


def test_require_field_skips_when_the_field_is_empty():
    with pytest.raises(pytest.skip.Exception) as info:
        require_field({"E_GTR_STATUS": ""}, "E_GTR_STATUS")
    assert "E_GTR_STATUS" in str(info.value)


def test_require_field_skip_message_is_exactly_the_field_name():
    # Pinned to the exact string: a future edit that helpfully appends the value
    # to the reason ("... is empty, got 'Jane Doe'") would leak it into every
    # test report, and this is what stops that landing unnoticed.
    with pytest.raises(pytest.skip.Exception) as info:
        require_field({"REQUESTOR_NAME": ""}, "REQUESTOR_NAME")
    assert str(info.value) == (
        "the field REQUESTOR_NAME is present but empty on this instance"
    )


def test_helper_messages_name_only_the_label():
    # The real guarantee: a failure message is assembled from the label and
    # nothing else, so no caller can leak a live name or e-mail through one.
    secret = "someone@example.test"
    with pytest.raises(AssertionError) as populated:
        assert_populated(_Falsy(secret), "REQUESTOR")
    with pytest.raises(AssertionError) as shape:
        assert_shape(_Falsy(secret), int, "REQUESTOR_ID")
    with pytest.raises(pytest.skip.Exception) as skipped:
        require_field({"REQUESTOR_NAME": ""}, "REQUESTOR_NAME")
    for outcome in (populated, shape, skipped):
        assert secret not in str(outcome.value)


# --- what pytest RENDERS, not just what the message says --------------------
#
# The tests above all read `str(info.value)`. That is the message alone, and the
# message was never the whole leak: pytest also prints every traceback frame's
# arguments. Two independent mechanisms suppress that, and each is pinned below
# on the rendered output of a real nested pytest run -- the only place the
# property is actually observable.

_LEAKY_CONFTEST = """
import pytest

class Leaky:
    def __repr__(self):
        return "LEAKED_INSTANCE_DATA"

@pytest.fixture
def live_record():
    return Leaky()
"""

# Takes NO fixture, so the test's own frame has no arguments to render. The
# helper's frame is then the only thing that could print the repr, which is what
# isolates `__tracebackhide__` from the traceback-style mechanism.
_HELPER_TEST = """
from conftest import Leaky
from integration_tests._assertions import assert_shape

def test_via_helper():
    assert_shape(Leaky(), str, "the record")
"""

# Takes the fixture and never reaches an assert at all: nothing about assertion
# style can suppress this one, only the traceback style can.
_FIXTURE_TEST = """
def test_unexpected_exception(live_record):
    raise RuntimeError("something the suite did not anticipate")
"""

# Applies the REAL `_force_short_traceback` to every item, which is what this
# directory's collection hook does for the live suite.
_REDACTING_CONFTEST = (
    _LEAKY_CONFTEST
    + """
from integration_tests.conftest import _force_short_traceback

def pytest_collection_modifyitems(items):
    for item in items:
        _force_short_traceback(item)
"""
)


def _run_nested_pytest(
    tmp_path: Path, conftest: str, test_body: str, *extra_args: str
) -> str:
    """Run pytest on a throwaway package and return its combined output."""
    (tmp_path / "conftest.py").write_text(textwrap.dedent(conftest), encoding="utf-8")
    (tmp_path / "test_leaky.py").write_text(
        textwrap.dedent(test_body), encoding="utf-8"
    )
    # Inherit the environment rather than building one: on Windows a stripped
    # env leaves the interpreter unable to seed hash randomization and it dies
    # before pytest starts.
    env = dict(os.environ, PYTHONPATH=str(_REPO_ROOT))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tmp_path),
            "-p",
            "no:cacheprovider",
            "-q",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,  # outside the repo, so pyproject addopts do not apply
        env=env,
    )
    return completed.stdout + completed.stderr


def test_helper_frames_are_hidden_from_the_traceback(tmp_path):
    """``__tracebackhide__`` alone keeps a helper's argument out of the output.

    Without it pytest renders the helper's frame in long style, printing
    ``value = <the live record>`` above the label-only message -- a leak that
    assertion style cannot reach, because it comes from the traceback rather
    than from the rewriter. Run here with NO traceback override and with a test
    that takes no fixture, so the helper's frame is the only thing that could
    print the repr -- which is what isolates this mechanism from the other one.
    """
    output = _run_nested_pytest(tmp_path, _LEAKY_CONFTEST, _HELPER_TEST)
    assert "test_via_helper" in output, f"the nested run did not execute:\n{output}"
    assert "LEAKED_INSTANCE_DATA" not in output


def test_a_live_fixture_repr_never_reaches_the_failure_output(tmp_path):
    """``_force_short_traceback`` keeps a test's own fixtures out of the output.

    This is the half no helper can close: a test's traceback frame arguments are
    its fixtures, so one taking a live record spills it on ANY failure -- the
    unexpected exception here never reaches an assert at all.
    """
    output = _run_nested_pytest(tmp_path, _REDACTING_CONFTEST, _FIXTURE_TEST)
    assert "test_unexpected_exception" in output, (
        f"the nested run did not execute:\n{output}"
    )
    assert "LEAKED_INSTANCE_DATA" not in output


@pytest.mark.parametrize("flag", ["--showlocals", "--full-trace"])
def test_debug_flags_cannot_reinstate_the_leak(tmp_path, flag):
    """Neither flag puts the reprs back, though each does so on its own.

    ``--showlocals`` renders the frame's locals and ``--full-trace`` forces the
    style back to long inside ``_repr_failure_py`` -- measured: each defeats a
    short traceback by itself. A developer reaching for them on a live failure
    is debugging, not exporting, but P2 is not conditional on intent, so
    ``_force_short_traceback`` neutralizes both for the duration of the report.
    """
    output = _run_nested_pytest(tmp_path, _REDACTING_CONFTEST, _FIXTURE_TEST, flag)
    assert "test_unexpected_exception" in output, (
        f"the nested run did not execute:\n{output}"
    )
    assert "LEAKED_INSTANCE_DATA" not in output


class _StubItem:
    """Enough of a pytest item for the collection hook to act on."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.markers: list[object] = []
        self.repr_failure = "not overridden"

    def add_marker(self, marker: object) -> None:
        self.markers.append(marker)


def test_collection_hook_forces_short_tracebacks_in_this_directory(tmp_path):
    """The wiring: both effects are applied here, and neither escapes elsewhere.

    The scoping half is not incidental. pytest hands this hook every collected
    item in the session, so an unguarded version would strip the unit suite's
    tracebacks too -- and mark it ``integration``, which CI deselects.
    """
    inside = _StubItem(Path(__file__).resolve())
    outside = _StubItem(tmp_path / "test_elsewhere.py")

    pytest_collection_modifyitems([inside, outside])

    assert inside.markers, "an item in this directory was not marked integration"
    assert callable(inside.repr_failure), "repr_failure was not overridden"
    assert not outside.markers, "an item outside this directory was marked"
    assert outside.repr_failure == "not overridden", (
        "the hook overrode repr_failure for an item outside this directory"
    )
