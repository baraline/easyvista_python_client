API Reference
=============

Clients
-------

.. autoclass:: easyvista_python_client.EasyvistaClient

.. autoclass:: easyvista_python_client.AsyncEasyvistaClient

Configuration
-------------

.. autoclass:: easyvista_python_client.config.EasyvistaConfig

.. autodata:: easyvista_python_client.DEFAULT_USER_AGENT

Models
------

.. autoclass:: easyvista_python_client.models.request.Request

.. autoclass:: easyvista_python_client.models.request.PostRequest

.. autoclass:: easyvista_python_client.models.request.RequestUpdate

.. autoclass:: easyvista_python_client.models.action.Action

.. autoclass:: easyvista_python_client.models.action.PostAction

.. autoclass:: easyvista_python_client.models.action.PostTask

.. autoclass:: easyvista_python_client.models.action.ActionUpdate

.. autoclass:: easyvista_python_client.models.asset.Asset

.. autoclass:: easyvista_python_client.models.asset.PostAsset

.. autoclass:: easyvista_python_client.models.document.Document

.. autoclass:: easyvista_python_client.models.department.Department

.. autoclass:: easyvista_python_client.models.department.PostDepartment

.. autoclass:: easyvista_python_client.models.department.DepartmentUpdate

.. autoclass:: easyvista_python_client.models.employee.Employee

.. autoclass:: easyvista_python_client.models.employee.PostEmployee

.. autoclass:: easyvista_python_client.models.employee.EmployeeUpdate

.. autoclass:: easyvista_python_client.pagination.SearchResult

.. autoclass:: easyvista_python_client.context.TicketContext

.. autodata:: easyvista_python_client.DEFAULT_MARKDOWN_FIELDS

.. autoclass:: easyvista_python_client.directory.DepartmentContext

Reporting
---------

.. autoclass:: easyvista_python_client.reporting.TicketStatistics

.. autofunction:: easyvista_python_client.reporting.aggregate_tickets

Filters
-------

Build ``search`` expressions with these rather than f-strings: EasyVista ignores a filter it cannot
parse and returns every record, ``,`` combines conditions so an unescaped value can silently widen
the result, and there is no comparison operator — a range must be expressed as an interval.

.. autofunction:: easyvista_python_client.filters.ev_equals_filter

.. autofunction:: easyvista_python_client.filters.ev_in_filter

.. autofunction:: easyvista_python_client.filters.ev_contains_filter

.. autofunction:: easyvista_python_client.filters.ev_starts_with_filter

.. autofunction:: easyvista_python_client.filters.ev_since_filter

.. autofunction:: easyvista_python_client.filters.ev_between_filter

.. autofunction:: easyvista_python_client.filters.escape_ev_value

.. autofunction:: easyvista_python_client.filters.is_safe_ev_value

Timestamps
----------

EasyVista's timestamp format, parsed and rendered in one place — see
:ref:`timestamps` for how the read models use these.

.. autofunction:: easyvista_python_client.timestamps.parse_ev_datetime

.. autofunction:: easyvista_python_client.timestamps.format_ev_datetime

References
----------

.. autoclass:: easyvista_python_client.references.Reference

.. autodata:: easyvista_python_client.DEFAULT_LANGUAGE_ORDER

.. autofunction:: easyvista_python_client.localized_label

.. autofunction:: easyvista_python_client.references.label_from_record

Instance discovery
------------------

.. autoclass:: easyvista_python_client.DiscoveredReference

.. autoclass:: easyvista_python_client.InstanceProfile

.. autoclass:: easyvista_python_client.ReferenceSource

.. autoclass:: easyvista_python_client.GenericRecord

.. autodata:: easyvista_python_client.DEFAULT_DISCOVERY_NAMES

Every read model exposes ``.reference(name)`` returning a :class:`~easyvista_python_client.references.Reference`
for any field, including custom ``e_*`` fields.

Field model
-----------

.. autoclass:: easyvista_python_client.field_model.FieldClassification

Every read model exposes ``.classify_fields()`` returning a
:class:`~easyvista_python_client.field_model.FieldClassification` that splits the
record into official / custom (``e_*``) / available / link fields. ``e_`` marks a
custom field (per EasyVista); official ``E_``-columns like ``E_MAIL`` stay official
because they are declared model fields. Resolve a link's text with
``client.resolve_memo(href)``.

Exceptions
----------

.. autoexception:: easyvista_python_client.exceptions.EasyvistaError

.. autoexception:: easyvista_python_client.exceptions.EasyvistaAuthError

.. autoexception:: easyvista_python_client.exceptions.EasyvistaNotFound

.. autoexception:: easyvista_python_client.exceptions.EasyvistaValidationError

.. autoexception:: easyvista_python_client.exceptions.EasyvistaRateLimitError

.. autoexception:: easyvista_python_client.exceptions.EasyvistaServerError

.. autoexception:: easyvista_python_client.exceptions.EasyvistaConnectionError

Resource engine
---------------

Every flat-CRUD resource is declared as a
:class:`~easyvista_python_client.resources.descriptor.ResourceDescriptor` (path,
create/list envelope key, read model) and driven by the generic
``build_get`` / ``build_search`` / ``build_create`` / ``build_update`` builders, so
adding a documented endpoint is a descriptor + a model, not a new module.

.. autoclass:: easyvista_python_client.resources.descriptor.ResourceDescriptor
