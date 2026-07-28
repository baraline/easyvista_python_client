"""Unit tests for the pure content-fidelity classifier in the live validator.

The live script ``scripts/validate_live_content_fidelity.py`` creates a ticket on
a real instance and diffs what it sent against what the API returns. The *diffing*
is pure and lives in that script as ``classify_fidelity``; these tests pin its
verdicts without any network. The script is loaded by path because ``scripts/``
is not an importable package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "validate_live_content_fidelity.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "validate_live_content_fidelity", _SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses in the module can resolve their own
    # __module__ under ``from __future__ import annotations``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fid = _load_script()


class TestClassifyFidelity:
    def test_identical_text_is_exact(self) -> None:
        assert fid.classify_fidelity("Hello world", "Hello world") == fid.EXACT

    def test_none_returned_is_missing(self) -> None:
        assert fid.classify_fidelity("Hello", None) == fid.MISSING

    def test_server_wrapped_plaintext_in_html_is_equivalent(self) -> None:
        # The server stored plain text wrapped in a block element; the readable
        # text is preserved, only inert markup was added.
        assert (
            fid.classify_fidelity("Hello world", "<div>Hello world</div>")
            == fid.EQUIVALENT
        )

    def test_entity_encoded_accents_are_equivalent(self) -> None:
        # HTML-entity encoding of an accent is a lossless representation change.
        assert fid.classify_fidelity("café", "caf&eacute;") == fid.EQUIVALENT

    def test_whitespace_reflow_is_equivalent(self) -> None:
        assert (
            fid.classify_fidelity("line one\nline two", "line one line two")
            == fid.EQUIVALENT
        )

    def test_dropped_readable_text_is_mangled(self) -> None:
        # The server silently dropped meaningful characters from the body.
        assert (
            fid.classify_fidelity("total cost is 100 dollars", "total cost is dollars")
            == fid.MANGLED
        )

    def test_filename_identical_is_exact(self) -> None:
        assert (
            fid.classify_fidelity("report final.txt", "report final.txt", html=False)
            == fid.EXACT
        )

    def test_filename_compared_literally_not_as_html(self) -> None:
        # For a filename, an escaped angle bracket is a real change, not an inert
        # entity encoding — html=False must NOT HTML-decode before comparing.
        assert (
            fid.classify_fidelity("a<b>.txt", "a&lt;b&gt;.txt", html=False)
            == fid.MANGLED
        )
