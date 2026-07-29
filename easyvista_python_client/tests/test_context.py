from easyvista_python_client import (
    Action,
    Document,
    Request,
    TicketContext,
)


def _ticket() -> Request:
    return Request.model_validate(
        {
            "RFC_NUMBER": "I240101_0010",
            "TITLE": "Printer down",
            "STATUS": {
                "STATUS_FR": "En cours",
                "HREF": "https://h/api/v1/12345/status/12",
            },
            # Synthetic labels. These were lifted from a real ticket and named a
            # real organisation and catalog; design principle P2 keeps live
            # names, department and catalog labels out of tracked files and
            # assertion literals, and a unit test fixture has no reason to carry
            # them.
            "DEPARTMENT": {
                "DEPARTMENT_FR": "Example Department",
                "HREF": "https://h/api/v1/12345/departments/37",
            },
            "CATALOG_REQUEST": {
                "TITLE_FR": "[EXAMPLE] - ticket",
                "HREF": "https://h/api/v1/12345/catalog-requests/5791",
            },
            "CREATION_DATE_UT": "2025-11-28T11:35:22+01:00",
        }
    )


def test_to_markdown_has_title_and_header_labels():
    md = TicketContext(_ticket(), None, None, [], []).to_markdown()
    assert "# Ticket I240101_0010 — Printer down" in md
    assert "| Status | En cours |" in md
    assert "| Department | Example Department |" in md
    assert "| Catalog | [EXAMPLE] - ticket |" in md


def test_to_markdown_contains_no_api_url():
    md = TicketContext(_ticket(), "<p>desc</p>", "cmt", [], []).to_markdown()
    assert "/api/" not in md
    assert "://" not in md


def test_to_markdown_renders_description_and_comment_as_text():
    md = TicketContext(
        _ticket(), "<p>Hello <b>world</b></p>", "a note", [], []
    ).to_markdown()
    assert "## Description" in md
    assert "Hello world" in md
    assert "## Comment" in md
    assert "a note" in md
    # Both memos populated -> the distinction is real, so both survive, and
    # DESCRIPTION comes first. The `in` checks above are order-agnostic and
    # would pass on a reversed document.
    assert md.index("## Description") < md.index("## Comment")


# --- headings name the ROLE, not the source field ---------------------------
#
# Which memo carries a ticket's body is per-deployment: on the verified instance
# DESCRIPTION is unused and COMMENT holds it, and `RequestUpdate.description`
# writes COMMENT on any instance. So a lone populated memo is the body whichever
# field it arrived in, and is titled "Description". These three tests pin the
# whole rule; without them a future edit could hard-code either universal.


def test_lone_comment_is_titled_description():
    # The verified deployment's shape, and the case the rule exists for: the
    # ticket's body text arrives in COMMENT with DESCRIPTION empty. Titling it
    # "Comment" mislabels the most important block in the document for a RAG
    # chunker splitting on "## ".
    md = TicketContext(_ticket(), None, "the printer is offline", [], []).to_markdown()
    assert "## Description" in md
    assert "## Comment" not in md
    assert "the printer is offline" in md


def test_lone_description_is_titled_description():
    # The other single-memo case -- an instance that populates DESCRIPTION and
    # leaves COMMENT empty -- renders exactly as it always did.
    md = TicketContext(
        _ticket(), "<p>the printer is offline</p>", "", [], []
    ).to_markdown()
    assert "## Description" in md
    assert "## Comment" not in md
    assert "the printer is offline" in md


def test_whitespace_only_memo_counts_as_empty():
    # `html_to_text` strips, so a memo holding only markup or blanks reduces to
    # "" and must take the lone-memo branch rather than the both-populated one.
    md = TicketContext(_ticket(), "<p>  </p>", "real body", [], []).to_markdown()
    assert "## Description" in md
    assert "## Comment" not in md
    assert "real body" in md


def test_to_markdown_omits_empty_sections():
    md = TicketContext(_ticket(), "", None, [], []).to_markdown()
    assert "## Description" not in md
    assert "## Comment" not in md
    assert "## Actions" not in md
    assert "## Attachments" not in md


def test_to_markdown_renders_actions_and_attachments():
    action = Action.model_validate(
        {
            "ACTION_ID": 1,
            "COMMENT": "Investigating",
            "ACTION_TYPE": {"NAME_FR": "Prise d'appel"},
            "DONE_BY": "J. Doe",
        }
    )
    doc = Document.model_validate(
        {"FILE_NAME": "report.pdf", "HREF": "https://h/api/v1/12345/x"}
    )
    md = TicketContext(_ticket(), None, None, [action], [doc]).to_markdown()
    assert "## Actions" in md
    assert "### Prise d'appel — J. Doe" in md
    assert "Investigating" in md
    assert "## Attachments" in md
    assert "- report.pdf" in md
    assert "/api/" not in md


def test_to_markdown_action_label_fallback_and_default():
    # ACTION_TYPE absent -> falls back to ACTION_LABEL_FR
    a1 = Action.model_validate(
        {
            "ACTION_ID": 1,
            "COMMENT": "x",
            "ACTION_LABEL_FR": "Clôture",
        }
    )
    md1 = TicketContext(_ticket(), None, None, [a1], []).to_markdown()
    assert "### Clôture" in md1
    # neither ACTION_TYPE nor ACTION_LABEL_FR -> default heading "Action"
    a2 = Action.model_validate({"ACTION_ID": 2, "COMMENT": "y"})
    md2 = TicketContext(_ticket(), None, None, [a2], []).to_markdown()
    assert "### Action" in md2


def test_to_markdown_skips_nameless_document():
    # no FILE_NAME / NAME
    doc = Document.model_validate({"HREF": "https://h/api/v1/12345/x"})
    md = TicketContext(_ticket(), None, None, [], [doc]).to_markdown()
    assert "## Attachments" in md
    assert "- \n" not in md
    assert not md.rstrip().endswith("- ")
    assert "/api/" not in md
