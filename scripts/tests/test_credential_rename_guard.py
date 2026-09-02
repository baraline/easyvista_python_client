"""CI-visible regression guards for the 2026-08-25 account-credential rename.

``EASYVISTA_TEST_USER`` / ``secrets/easyvista_test_user`` held the EasyVista
*account* -- the instance id forming the ``{account}`` path segment of
``https://host/api/{version}/{account}`` -- and never a login. They are now
``EASYVISTA_TEST_ACCOUNT`` / ``secrets/easyvista_test_account``, and the old name
is **refused** rather than honoured as a fallback: silently accepting it would
preserve exactly the misreading the rename removes.

**Why this file exists at all.** The equivalent guards for
``integration_tests/conftest.py`` live in
``integration_tests/test_fixture_helpers.py``, which is the right home for them
-- but that directory's collection hook stamps ``pytest.mark.integration`` on
every item **by location**, and CI runs ``pytest -m "not integration"``. Measured:
``pytest integration_tests/test_fixture_helpers.py -m "not integration"`` collects
0 and deselects 32. Those guards therefore only fire on a bare ``pytest``, which
this project's own docs warn against running while ``secrets/`` exists. On top of
that, ``integration_tests/`` is excluded from mypy by *both* gates (pyproject's
``[tool.mypy] exclude`` and the mirrored ``^integration_tests/`` in
``.pre-commit-config.yaml``). Without this module the rename would be enforced by
nothing but ruff's F821.

``scripts/`` is in ``testpaths``, carries no such marker, and is type-checked, so
the guards here do run in CI. They cover the two validators' own copies of the
tripwire, plus a source-level contract over ``integration_tests/conftest.py`` --
which is how the un-runnable half gets covered from a runnable place.

The scripts are loaded by path because ``scripts/`` is not an importable package.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]
_REPO = _SCRIPTS.parent
_CONFTEST = _REPO / "integration_tests" / "conftest.py"

_VALIDATORS = ("validate_docs_examples", "validate_live_content_fidelity")

# The retired spellings, quoted here rather than imported: a test that reads its
# expectations out of the module under test cannot fail when that module changes.
_LEGACY_ENV = "EASYVISTA_TEST_USER"
_LEGACY_FILE = "easyvista_test_user"
_CURRENT_ENV = "EASYVISTA_TEST_ACCOUNT"
_CURRENT_FILE = "easyvista_test_account"

_SECRET_VALUE = "50004"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses in the module can resolve their own
    # __module__ under ``from __future__ import annotations``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=_VALIDATORS)
def validator(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Any:
    """One validator module, with every credential source isolated.

    ``SECRETS_DIR`` is redirected at an empty tmp dir and the four environment
    variables the resolvers read are cleared, so a developer's real ``secrets/``
    cannot decide the outcome of these tests.
    """
    module = _load(request.param)
    monkeypatch.setattr(module, "SECRETS_DIR", tmp_path)
    for name in (
        "EASYVISTA_TEST_URL",
        "EASYVISTA_TEST_TOKEN",
        _CURRENT_ENV,
        _LEGACY_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    return module


# --- the tripwire itself ------------------------------------------------------


def test_the_retired_env_var_aborts_and_names_its_replacement(
    validator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Honouring the old name is the bug; aborting is the feature."""
    monkeypatch.setenv(_LEGACY_ENV, _SECRET_VALUE)

    with pytest.raises(SystemExit) as info:
        validator._reject_legacy_account_name()

    message = str(info.value)
    assert _LEGACY_ENV in message
    assert _CURRENT_ENV in message
    assert "never a login" in message
    # Name the variable, never print what is in it.
    assert _SECRET_VALUE not in message


def test_the_retired_secrets_file_aborts(validator: Any, tmp_path: Path) -> None:
    """The likely real case: the env var was never set, the file was left behind."""
    (tmp_path / _LEGACY_FILE).write_text(_SECRET_VALUE, encoding="utf-8")

    with pytest.raises(SystemExit) as info:
        validator._reject_legacy_account_name()

    message = str(info.value)
    assert f"secrets/{_LEGACY_FILE}" in message
    assert f"secrets/{_CURRENT_FILE}" in message
    assert _SECRET_VALUE not in message


def test_both_retired_sources_are_reported_in_one_abort(
    validator: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Naming only one source would send someone round the loop twice."""
    monkeypatch.setenv(_LEGACY_ENV, _SECRET_VALUE)
    (tmp_path / _LEGACY_FILE).write_text(_SECRET_VALUE, encoding="utf-8")

    with pytest.raises(SystemExit) as info:
        validator._reject_legacy_account_name()

    message = str(info.value)
    assert _LEGACY_ENV in message
    assert f"secrets/{_LEGACY_FILE}" in message
    assert " are still set" in message  # plural agreement, not "is"


def test_a_clean_environment_is_silent(validator: Any) -> None:
    """The tripwire must cost nothing when nothing is stale."""
    assert validator._reject_legacy_account_name() is None


def test_a_blank_retired_env_var_does_not_trip_the_wire(
    validator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty string is not configuration -- ``_resolve`` ignores it too.

    Tripping on it would turn an exported-but-empty variable into an abort with
    no obvious cause.
    """
    monkeypatch.setenv(_LEGACY_ENV, "   ")

    assert validator._reject_legacy_account_name() is None


def test_the_tripwire_never_fires_at_import_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing a validator with the retired name set must not abort.

    ``scripts/tests/test_validate_live_content_fidelity.py`` exec-loads
    ``validate_live_content_fidelity.py`` at MODULE IMPORT during CI's unit run.
    That is safe only because the tripwire is a function the resolvers call, not
    module-level code. Hoisting it to import time would make CI's own unit suite
    ``SystemExit`` on any machine with the stale variable exported -- this pins
    that it stays a ``def``.
    """
    monkeypatch.setenv(_LEGACY_ENV, _SECRET_VALUE)

    for name in _VALIDATORS:
        _load(name)  # must not raise


# --- the source contract, covering what CI cannot run -------------------------


@pytest.mark.parametrize(
    "path",
    [_CONFTEST, *(_SCRIPTS / f"{n}.py" for n in _VALIDATORS)],
    ids=["conftest", *_VALIDATORS],
)
def test_the_retired_name_is_never_resolved_as_a_credential(path: Path) -> None:
    """No resolver call may still read the retired name.

    The user chose a hard rename over a deprecated fallback, so the old spelling
    is allowed to survive only as the tripwire's constants and as prose
    explaining the change. Any line that both calls a resolver and mentions it is
    a fallback creeping back in.

    This is the only automated check on ``integration_tests/conftest.py``'s half
    of the rename that CI actually executes -- see this module's docstring.
    """
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if ("_resolve(" in line or "_r(" in line) and _LEGACY_FILE in line.lower()
    ]

    assert not offenders, "retired credential name is being resolved:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    "path",
    [_CONFTEST, *(_SCRIPTS / f"{n}.py" for n in _VALIDATORS)],
    ids=["conftest", *_VALIDATORS],
)
def test_every_resolver_knows_the_current_name(path: Path) -> None:
    """A half-applied rename -- old name gone, new one never added -- must fail.

    Deleting the retired name without wiring up its replacement would leave a
    bare-host setup with no way to supply an account at all, and the previous
    test would happily pass.
    """
    source = path.read_text(encoding="utf-8")

    assert _CURRENT_ENV in source, f"{path.name} never mentions {_CURRENT_ENV}"
    assert _CURRENT_FILE in source, f"{path.name} never mentions {_CURRENT_FILE}"


def test_every_credential_conftest_reads_is_named_in_its_docstring() -> None:
    """The live suite's credential contract must not drift out of its own docs.

    ``integration_tests/conftest.py``'s module docstring is the canonical
    statement of which environment variables and ``secrets/`` files the live
    suite consults -- it is what a contributor reads, and it is what sent someone
    hunting for a login that never existed. It had already drifted: it announced
    "Two further per-instance ids" while the module resolved eight, so six secret
    files were undocumented.

    Prose cannot be kept honest by review alone, so pin it. Every
    ``EASYVISTA_TEST_*`` name the source mentions has to appear in the docstring.
    """
    source = _CONFTEST.read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(source)) or ""

    referenced = set(re.findall(r"EASYVISTA_TEST_[A-Z_]+", source))
    # The wildcard the docstring uses for the "no credentials" skip message is a
    # glob, not a variable.
    referenced.discard("EASYVISTA_TEST_")

    undocumented = sorted(name for name in referenced if name not in docstring)

    assert not undocumented, (
        "conftest.py resolves these but its module docstring never names them: "
        + ", ".join(undocumented)
    )
