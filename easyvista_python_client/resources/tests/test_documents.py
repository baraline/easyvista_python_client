import base64

import pytest

from easyvista_python_client.models.document import Document
from easyvista_python_client.resources import documents as d
from easyvista_python_client.resources.documents import (
    build_delete_document,
    download_href,
)


def test_build_add_document_base64_envelope_and_path():
    spec, parser = d.build_add_document(
        "I1", filename="hello.txt", content=b"Je suis un document"
    )
    assert spec.method == "POST"
    assert spec.path == "requests/I1/documents"
    assert spec.json is not None
    entry = spec.json["documents"][0]
    assert entry["filename"] == "hello.txt"
    assert base64.b64decode(entry["filedata"]) == b"Je suis un document"
    parsed = parser({"HREF": "https://ev.test/api/v1/acme/requests/I1"})
    assert parsed.href.endswith("/requests/I1")


def test_build_list_documents():
    spec, parser = d.build_list_documents("I1")
    assert spec.method == "GET"
    assert spec.path == "requests/I1/documents"
    docs = parser({"records": [{"HREF": "u1"}, {"HREF": "u2"}]})
    assert [doc.href for doc in docs] == ["u1", "u2"]


def test_document_model_live_list_item_shape():
    """A live list item exposes DOCUMENT / DOCUMENT_ID / DDL_HREF (verified live)."""
    from easyvista_python_client.models.document import Document

    item = {
        "HREF": "https://host/autoconnect_mail.php?field9=pvfdoc1_validation.txt",
        "DOCUMENT_ID": "12345_537cabc",
        "DOCUMENT": "pvfdoc1_validation.txt",
        "DDL_HREF": "https://host/api/v1/12345/requests/I1/documents/12345_537cabc",
    }
    doc = Document.model_validate(item)
    assert doc.filename == "pvfdoc1_validation.txt"
    assert doc.document_id == "12345_537cabc"
    assert doc.download_href.endswith("/documents/12345_537cabc")


def test_build_list_documents_capital_documents_envelope():
    """The live list wraps items under a capital-D ``Documents`` key (verified live)."""
    _spec, parser = d.build_list_documents("I1")
    payload = {
        "HREF": "https://host/api/v1/12345/requests/I1/documents",
        "Documents": [
            {"DOCUMENT": "a.txt", "DOCUMENT_ID": "x1", "DDL_HREF": "d1", "HREF": "h1"},
            {"DOCUMENT": "b.png", "DOCUMENT_ID": "x2", "DDL_HREF": "d2", "HREF": "h2"},
        ],
    }
    docs = parser(payload)
    assert [doc.filename for doc in docs] == ["a.txt", "b.png"]
    assert [doc.download_href for doc in docs] == ["d1", "d2"]


def test_download_href_prefers_the_ddl_href():
    doc = Document.model_validate(
        {
            "HREF": "https://ev.test/api/v1/acme/documents/7",
            "DDL_HREF": "https://ev.test/dl/7",
        }
    )
    assert download_href(doc) == "https://ev.test/dl/7"


def test_download_href_falls_back_to_the_plain_href():
    doc = Document.model_validate({"HREF": "https://ev.test/api/v1/acme/documents/7"})
    assert download_href(doc) == "https://ev.test/api/v1/acme/documents/7"


def test_download_href_accepts_a_raw_string():
    assert download_href("documents/7/content") == "documents/7/content"


def test_download_href_raises_when_no_url_is_available():
    with pytest.raises(ValueError, match="no download URL"):
        download_href(Document.model_validate({"DOCUMENT": "report.pdf"}))


def test_delete_document_uses_the_nested_per_ticket_path():
    """The top-level documents/{id} form returns 403 (verified live)."""
    spec = build_delete_document("I240101_0001", "12345_abcdef")
    assert spec.method == "DELETE"
    assert spec.path == "requests/I240101_0001/documents/12345_abcdef"
    assert spec.json is None


def test_delete_document_requires_both_identifiers():
    with pytest.raises(ValueError, match="rfc_number"):
        build_delete_document("", "12345_abcdef")
    with pytest.raises(ValueError, match="document_id"):
        build_delete_document("I240101_0001", "")


# --- two routes exist for the delete; a 403 never said which ----------------
#
# The instance OpenAPI document read 2026-08-27 declares DELETE on BOTH
# `requests/{rfc}/documents/{id}` and `documents/{id}`, marking only the
# latter `deprecated`. So the 403 measured against the top-level form was a
# profile denial, not a missing route -- this API answers 403 for an unknown
# path as well as a denied one.


def test_build_delete_document_top_level_style():
    spec = build_delete_document("I240101_0001", "12345_abcdef", path_style="top_level")
    assert spec.method == "DELETE"
    assert spec.path == "documents/12345_abcdef"


def test_build_delete_document_top_level_ignores_a_missing_rfc_number():
    """The top-level route has no slot for an RFC, so refusing a missing one
    would be surprising and requiring one would defeat the point."""
    spec = build_delete_document(None, "d1", path_style="top_level")
    assert spec.path == "documents/d1"


def test_build_delete_document_rejects_a_blank_document_id_in_either_style():
    """``DELETE documents/`` addresses the collection just as
    ``DELETE requests/{rfc}/documents/`` does."""
    for style in ("nested", "top_level"):
        with pytest.raises(ValueError, match="document_id"):
            build_delete_document("I240101_0001", "  ", path_style=style)


def test_build_delete_document_rejects_an_unknown_path_style():
    with pytest.raises(ValueError, match="path_style"):
        build_delete_document("I240101_0001", "d1", path_style="nested_v2")


def test_build_add_document_unwraps_a_capital_d_documents_envelope():
    """The create parser read the response by a different rule than the list.

    ``_first_document`` used the case-SENSITIVE ``extract_records`` while
    ``_document_records`` fifteen lines below was already case-insensitive --
    for the same resource on the same instance, the one known to answer a
    capital-D ``Documents``. A create echoed that way yielded an all-``None``
    ``Document`` built from the wrapper.
    """
    _, parser = d.build_add_document("I1", filename="a.txt", content=b"x")
    parsed = parser({"Documents": [{"DOCUMENT": "a.txt", "DOCUMENT_ID": "x1"}]})
    assert parsed.filename == "a.txt"
    assert parsed.document_id == "x1"
