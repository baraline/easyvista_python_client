from easyvista_python_client.models.document import Document


def test_document_id_accepts_a_json_number():
    """``DOCUMENT_ID``'s type was observed on one instance, never documented.

    Declared ``str`` alone, an instance returning it as a JSON number failed
    the record -- and because ``_all_documents`` validates the whole list in one
    comprehension, every attachment on the ticket with it. The union coerces
    neither direction, so a number stays a number.
    """
    assert Document.model_validate({"DOCUMENT_ID": 42}).document_id == 42


def test_document_id_keeps_a_string_as_a_string():
    """``union_mode="left_to_right"`` tries ``str`` first; pydantic's ``str``
    does not absorb an int, so both forms survive as sent."""
    assert Document.model_validate({"DOCUMENT_ID": "42"}).document_id == "42"


def test_filename_falls_back_across_the_list_and_item_shapes():
    """The live list exposes the name as ``DOCUMENT``; other shapes use
    ``FILE_NAME`` or ``NAME``."""
    assert Document.model_validate({"DOCUMENT": "report.pdf"}).filename == "report.pdf"
    assert Document.model_validate({"NAME": "report.pdf"}).filename == "report.pdf"
    assert Document.model_validate({"FILE_NAME": "kept.pdf"}).filename == "kept.pdf"
