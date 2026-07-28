from easyvista_python_client._fields import _label, _text


def test_text_strips_strings_and_ignores_non_strings():
    assert _text("  hi  ") == "hi"
    assert _text(None) == ""
    assert _text(123) == ""


def test_label_prefers_first_non_empty_key_and_drops_href():
    obj = {"STATUS_EN": "", "STATUS_FR": "En cours", "HREF": "http://x/api/v1"}
    assert _label(obj, ("STATUS_EN", "STATUS_FR")) == "En cours"


def test_label_returns_empty_for_non_dict_or_missing_keys():
    assert _label(None, ("A",)) == ""
    assert _label({"B": "x"}, ("A",)) == ""
