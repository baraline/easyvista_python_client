"""Typed Python client for the EasyVista Service Manager REST API."""

from easyvista_python_client._async import AsyncEasyvistaClient
from easyvista_python_client._sync import EasyvistaClient

from .config import EasyvistaConfig
from .context import TicketContext
from .directory import DepartmentContext
from .exceptions import (
    EasyvistaAuthError,
    EasyvistaConnectionError,
    EasyvistaError,
    EasyvistaNotFound,
    EasyvistaRateLimitError,
    EasyvistaServerError,
    EasyvistaValidationError,
)
from .field_model import FieldClassification
from .filters import (
    escape_ev_value,
    ev_equals_filter,
    ev_in_filter,
    is_safe_ev_value,
)
from .models.action import Action, PostAction
from .models.asset import Asset, PostAsset
from .models.department import Department, DepartmentUpdate, PostDepartment
from .models.document import Document
from .models.employee import Employee, EmployeeUpdate, PostEmployee
from .models.request import PostRequest, Request, RequestUpdate
from .pagination import SearchResult
from .references import Reference
from .reporting import TicketStatistics, aggregate_tickets

__version__ = "0.1.0"

__all__ = [
    "Action",
    "Asset",
    "AsyncEasyvistaClient",
    "Department",
    "DepartmentContext",
    "DepartmentUpdate",
    "Document",
    "EasyvistaAuthError",
    "EasyvistaClient",
    "EasyvistaConfig",
    "EasyvistaConnectionError",
    "EasyvistaError",
    "EasyvistaNotFound",
    "EasyvistaRateLimitError",
    "EasyvistaServerError",
    "EasyvistaValidationError",
    "Employee",
    "EmployeeUpdate",
    "FieldClassification",
    "PostAction",
    "PostAsset",
    "PostDepartment",
    "PostEmployee",
    "PostRequest",
    "Reference",
    "Request",
    "RequestUpdate",
    "SearchResult",
    "TicketContext",
    "TicketStatistics",
    "__version__",
    "aggregate_tickets",
    "escape_ev_value",
    "ev_equals_filter",
    "ev_in_filter",
    "is_safe_ev_value",
]
