"""Models for the EasyVista ``employees`` resource.

``Employee`` declares the fields the richer single-record GET returns
(``GET employees/{id}``). ``E_MAIL`` is a **declared official** field, so the generic
field model never misclassifies it as a custom ``e_*`` column. ``extra="allow"``
preserves the ``COMMENT_EMPLOYEE`` Memo link and any other columns. Aliases are
grounded in the live inventory (``docs/easyvista-field-inventory.md``). Writes are
**provisional** pending an authorised profile (spec open item O-DIR-2).
"""

from __future__ import annotations

from pydantic import Field

from .common import EasyvistaModel, EasyvistaWriteModel, OptionalDateTime, OptionalInt


class Employee(EasyvistaModel):
    """An employee (person) as returned by the single-record GET."""

    employee_id: OptionalInt = Field(default=None, alias="EMPLOYEE_ID")
    last_name: str | None = Field(default=None, alias="LAST_NAME")
    e_mail: str | None = Field(default=None, alias="E_MAIL")
    department_id: OptionalInt = Field(default=None, alias="DEPARTMENT_ID")
    department_path: str | None = Field(default=None, alias="DEPARTMENT_PATH")
    location_id: OptionalInt = Field(default=None, alias="LOCATION_ID")
    phone_number: str | None = Field(default=None, alias="PHONE_NUMBER")
    cellular_number: str | None = Field(default=None, alias="CELLULAR_NUMBER")
    profil_id: OptionalInt = Field(default=None, alias="PROFIL_ID")
    manager_id: OptionalInt = Field(default=None, alias="MANAGER_ID")
    employee_guid: str | None = Field(default=None, alias="EMPLOYEE_GUID")
    identification: str | None = Field(default=None, alias="IDENTIFICATION")
    login: str | None = Field(default=None, alias="LOGIN")
    function_id: OptionalInt = Field(default=None, alias="FUNCTION_ID")
    language_id: OptionalInt = Field(default=None, alias="LANGUAGE_ID")
    last_update: OptionalDateTime = Field(default=None, alias="LAST_UPDATE")
    href: str | None = Field(default=None, alias="HREF")


class PostEmployee(EasyvistaWriteModel):
    """Provisional payload for creating an employee (envelope ``{"employees": [...]}``).

    Field set is a best guess pending an authorised profile (spec open item O-DIR-2);
    ``custom_fields`` serialize with an ``e_`` prefix (see ``EasyvistaWriteModel``).
    """

    last_name: str | None = None
    e_mail: str | None = None
    department_id: int | None = None
    location_id: int | None = None
    phone_number: str | None = None
    cellular_number: str | None = None
    manager_id: int | None = None
    login: str | None = None
    function_id: int | None = None


class EmployeeUpdate(EasyvistaWriteModel):
    """Provisional payload for updating an employee via PUT (spec open item O-DIR-2)."""

    last_name: str | None = None
    e_mail: str | None = None
    department_id: int | None = None
    location_id: int | None = None
    phone_number: str | None = None
    cellular_number: str | None = None
    manager_id: int | None = None
