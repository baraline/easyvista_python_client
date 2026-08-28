"""Models for the EasyVista ``departments`` resource.

``Department`` declares the stable scalar fields; ``extra="allow"`` (from
``EasyvistaModel``) preserves the localized ``DEPARTMENT_<lang>`` label columns (used
by ``name``), the ``COMMENT_DEPARTMENT`` Memo link (surfaced by
``classify_fields().links`` and read via ``client.get_department_comment``), and any
instance-specific columns. Field aliases are grounded in the live inventory
(tier 4 -- a field inventory generated from one instance, 2026-07-07). Writes
are **provisional** pending an authorised profile (spec open item O-DIR-2).
"""

from __future__ import annotations

from pydantic import Field

from ..references import localized_label
from .common import EasyvistaModel, EasyvistaWriteModel, OptionalInt


class Department(EasyvistaModel):
    """A department (organisation node) as returned by the API."""

    department_id: OptionalInt = Field(default=None, alias="DEPARTMENT_ID")
    department_code: str | None = Field(default=None, alias="DEPARTMENT_CODE")
    department_path: str | None = Field(default=None, alias="DEPARTMENT_PATH")
    manager_id: OptionalInt = Field(default=None, alias="MANAGER_ID")
    level: OptionalInt = Field(default=None, alias="LEVEL")
    href: str | None = Field(default=None, alias="HREF")

    @property
    def name(self) -> str | None:
        """Best localized department label, falling back to code then path.

        A plain property (not a serialized field), so it never recurses through
        ``model_dump`` or appears in ``classify_fields``.
        """
        return localized_label(
            self.model_dump(by_alias=True),
            "DEPARTMENT",
            fallbacks=(self.department_code, self.department_path),
        )


class PostDepartment(EasyvistaWriteModel):
    """Provisional payload for creating a department.

    Sent inside the envelope ``{"departments": [...]}``. Field set is a best guess
    pending an authorised profile (spec open item O-DIR-2);
    ``custom_fields`` serialize with an ``e_`` prefix (see ``EasyvistaWriteModel``).
    """

    department_code: str | None = None
    department_en: str | None = None
    department_fr: str | None = None
    manager_id: int | None = None
    parent_department_id: int | None = None


class DepartmentUpdate(EasyvistaWriteModel):
    """Provisional payload for updating a department via PUT.

    Field set pending an authorised profile (spec open item O-DIR-2).
    """

    department_code: str | None = None
    department_en: str | None = None
    department_fr: str | None = None
    manager_id: int | None = None
