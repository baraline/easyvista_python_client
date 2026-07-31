---
name: easyvista-directory
description: "Look up and provision EasyVista departments and employees with easyvista_python_client — get_department, search_departments, iter_departments, find_departments, get_department_comment, create_department, update_department and the matching employee methods, plus Reference and FieldClassification for reading instance-specific columns. Use to resolve a department by name or code, list a department's people, read a directory memo, or create/update directory records."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and a profile authorized for the departments and employees resources (writes are additionally profile-gated)."
metadata:
  package: easyvista-python-client
  version: "0.1.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Departments and employees are two resources with parallel surfaces.
Departments: `get_department`, `search_departments`, `iter_departments`,
`find_departments`, `get_department_comment`, `create_department`,
`update_department`. Employees: `get_employee`, `search_employees`,
`iter_employees`, `create_employee`, `update_employee`. Reads are the
well-trodden path; writes are provisional (see Gotchas). Filtering any
`search=` argument follows the grammar in `easyvista-search-syntax` — see that
skill for the rules; they are not repeated here.

## Resolving a department by name

The main reason this skill exists. `find_departments(name, limit=None)` does
the right thing in one call:

- **Fast path:** an all-digit `name` matches `DEPARTMENT_ID` exactly;
  otherwise `DEPARTMENT_CODE` exactly. A hit returns immediately.
- **Fuzzy fallback:** scans every department client-side and matches `name`
  as a substring of any string field, normalized so
  `"Acme Corp" == "ACME-CORP" == "acmecorp"`.
- A name that cannot be expressed in the search grammar (it contains a `"`)
  skips the server fast path entirely and goes straight to the local scan,
  so it returns correct results rather than raising.

## Reading labels and instance columns

`Department.name` is a property returning the best localized label
(`DEPARTMENT_EN` → `_FR` → `_GE` → `_IT` → `_PO` → `_SP`), skipping
`[BRACKETED]` placeholders, falling back to `department_code` then
`department_path`. For anything else, use `record.reference(name)` and
`record.classify_fields()`.

`reference(name)` resolves a reference attribute — nested object or bare id —
to a `Reference` with `.id`, `.label` and `.display`. `classify_fields()`
partitions the record into a `FieldClassification` with `.official`, `.custom`
(the instance's `e_*` columns), `.available` and `.links` buckets. Both are
available on every record type this client returns;
`easyvista-ticket-workflow` covers them in full.

## Procedure

1. Resolve the department with `find_departments(name)` when you have a
   human name or code; `get_department(id)` when you have an id.
2. List its people with
   `iter_employees(search=ev_equals_filter("DEPARTMENT_ID", dept.department_id))`.
3. Read the department note with `get_department_comment(id)`.
4. For any other memo/link column, take the href from
   `classify_fields().links` and pass it to `resolve_memo`.
5. Only attempt `create_*` / `update_*` with a profile authorized for
   directory writes.

## Examples

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    matches = client.find_departments("acme corp", limit=5)
    for department in matches:
        print(department.department_id, department.department_code, department.name)
```

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    department = client.get_department(42)
    print(department.name, department.department_path, department.manager_id)

    search = ev_equals_filter("DEPARTMENT_ID", department.department_id)
    for employee in client.iter_employees(search=search, max_records=200):
        print(employee.employee_id, employee.last_name, employee.e_mail)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    note = client.get_department_comment(42)
    if note is None:
        print("no note, or the profile cannot read it")
    else:
        print(repr(note))  # "" means the memo exists and is empty
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    employee = client.get_employee(1001)

    buckets = employee.classify_fields()
    print("official:", sorted(buckets.official))
    print("custom:", sorted(buckets.custom))

    for name, href in buckets.links.items():
        print(name, "->", client.resolve_memo(href))
```

```python
from easyvista_python_client import EasyvistaClient, EmployeeUpdate, PostEmployee

with EasyvistaClient.from_env() as client:
    created = client.create_employee(
        PostEmployee(
            last_name="Doe",
            e_mail="jdoe@example.com",
            department_id=42,
            login="jdoe",
        )
    )
    client.update_employee(created.employee_id, EmployeeUpdate(phone_number="+33100000000"))
```

## Gotchas

- **Directory writes are provisional.** `PostDepartment`, `DepartmentUpdate`,
  `PostEmployee` and `EmployeeUpdate` field sets are a best guess: no profile
  authorized for directory writes was available to verify them. Expect 403,
  and treat a successful create as instance-specific until you have
  confirmed it.
- `get_department_comment` returns `""` for an empty memo and `None` only
  when the memo is absent — but it propagates transport errors, so a
  403/404 raises rather than returning `None`. That distinction is
  deliberate.
- `find_departments`' fuzzy fallback scans **every** department. On a large
  instance it pages the whole table; pass `limit=` and prefer an exact code
  when you have one.
- `DEPARTMENT_PATH` is returned but **not searchable** — filter
  `DEPARTMENT_ID` or `DEPARTMENT_CODE` instead. What EasyVista does with a
  condition it will not honour, and which other directory columns are
  affected, is `easyvista-search-syntax`'s subject.
- `E_MAIL` is a **declared official** field on `Employee`, not a custom
  `e_*` column; `classify_fields()` knows this and will not misfile it.
- Numeric directory columns come back as `""` when unset; the models
  coerce that to `None`, so never test for `""`.
- `Department.name` is a property, not a serialized field — it never
  appears in `model_dump()` or in `classify_fields()`.
