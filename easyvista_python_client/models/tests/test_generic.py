from easyvista_python_client.models.generic import GenericRecord


def test_generic_record_keeps_every_unknown_column():
    """It declares nothing, so nothing can be dropped for being unrecognised.

    That is the point: a reference table's response schema in an instance's
    OpenAPI is tier 3, and the verified instance's own ``/status`` schema is
    visibly wrong (it describes an SLA-shaped object with no status id at all).
    A column list written from those schemas would be a guess frozen into the
    public API.
    """
    row = {"STATUS_ID": 8, "STATUS_FR": "Cloture", "E_WHATEVER": "x", "HREF": "h"}
    record = GenericRecord.model_validate(row)
    assert record.model_dump(by_alias=True) == row


def test_generic_record_resolves_a_nested_reference():
    record = GenericRecord.model_validate(
        {"STATUS": {"STATUS_ID": 8, "STATUS_EN": "Closed"}}
    )
    assert record.reference("STATUS").label == "Closed"
    assert record.reference("STATUS").id == "8"


def test_classify_fields_puts_every_e_column_in_custom():
    """A documented consequence of declaring nothing, not an oversight.

    ``classify_fields`` partitions against the model's DECLARED aliases, and
    this model declares none -- so an official ``E_MAIL`` lands in ``custom``
    beside a genuinely custom column. That is the right trade for a model that
    knows nothing about its table, and it is pinned here so nobody "fixes" it
    by declaring a tier-3 column list.
    """
    record = GenericRecord.model_validate({"E_MAIL": "a@example.com", "NAME": "n"})
    assert "E_MAIL" in record.classify_fields().custom
