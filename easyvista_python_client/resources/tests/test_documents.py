import base64

from easyvista_python_client.resources import documents as d


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
