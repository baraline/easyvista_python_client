"""Generate a field inventory of the EasyVista instance. Read-only.

For every reachable entity it samples several records, unions their fields, and
classifies each (official / custom e_* / available / link) with the field-model
rules, then writes docs/easyvista-field-inventory.md — a reference for using the
generic library against this instance. READS ONLY.

Run:  .\.venv\Scripts\python.exe scripts/generate_field_inventory.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from easyvista_python_client import (
    Action,
    Asset,
    Document,
    EasyvistaClient,
    EasyvistaConfig,
    EasyvistaError,
    Request,
)
from easyvista_python_client._transport import RequestSpec
from easyvista_python_client.pagination import extract_records

_ROOT = Path(__file__).resolve().parents[1]
_SECRETS = _ROOT / "secrets"
_OUT = _ROOT / "docs" / "easyvista-field-inventory.md"
_AVAILABLE = re.compile(r"AVAILABLE_FIELD_\d+$")

SAMPLE = 5  # records per entity to union


def _read(n: str) -> str | None:
    p = _SECRETS / n
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def _config() -> EasyvistaConfig:
    url = (_read("easyvista_test_url") or "").rstrip("/")
    server, _, rest = url.partition("/api/")
    version, _, tail = rest.partition("/")
    return EasyvistaConfig(
        server=server,
        account=tail.split("/")[0],
        token=_read("easyvista_test_token") or "",
        api_version=version,
    )


def _declared(model_cls: type) -> set[str]:
    return {(f.alias or n).upper() for n, f in model_cls.model_fields.items()}


def _merge(records: list[dict]) -> dict[str, Any]:
    """One representative value per field across records.

    Prefers a dict value, then a non-empty one.
    """
    merged: dict[str, Any] = {}
    for rec in records:
        for k, v in rec.items():
            cur = merged.get(k)
            if isinstance(v, dict) and not isinstance(cur, dict):
                merged[k] = v
            elif k not in merged or (cur in ("", None) and v not in ("", None)):
                merged[k] = v
    return merged


def _classify(merged: dict, declared: set[str]) -> dict[str, list[str]]:
    custom, available, links, ref_objs, scalars = [], [], [], [], []
    for k, v in merged.items():
        ku = k.upper()
        if ku == "HREF":
            continue
        if isinstance(v, dict) and set(v.keys()) == {"HREF"}:
            links.append(k)
        elif _AVAILABLE.match(ku):
            available.append(k)
        elif ku.startswith("E_") and ku not in declared:
            custom.append(k)
        elif isinstance(v, dict):
            ref_objs.append(k)
        else:
            scalars.append(k)
    return {
        "custom": sorted(custom),
        "available": sorted(available),
        "links": sorted(links),
        "ref_objs": sorted(ref_objs),
        "scalars": sorted(scalars),
    }


def _section(label: str, path: str, n: int, total: int, g: dict[str, list[str]]) -> str:
    def fmt(items: list[str]) -> str:
        return ", ".join(f"`{i}`" for i in items) if items else "_(none)_"

    return "\n".join(
        [
            f"## {label} — `{path}`",
            f"\nSampled {n} record(s); **{total} distinct fields**.\n",
            f"- **Custom `e_*` (instance-specific) — {len(g['custom'])}:**"
            f" {fmt(g['custom'])}",
            f"- **Available slots — {len(g['available'])}:** {fmt(g['available'])}",
            f"- **Links (href sub-resources) — {len(g['links'])}:** {fmt(g['links'])}",
            f"- **Official · nested reference objects — {len(g['ref_objs'])}:**"
            f" {fmt(g['ref_objs'])}",
            f"- **Official · scalar fields — {len(g['scalars'])}:**"
            f" {fmt(g['scalars'])}",
            "",
        ]
    )


def main() -> None:
    cfg = _config()
    out: list[str] = []
    summary: list[tuple[str, int, dict[str, list[str]]]] = []

    with EasyvistaClient(cfg) as client:

        def get(path: str, **p: Any) -> list[dict]:
            return extract_records(
                client._transport.send(RequestSpec("GET", path, params=p or None))
            )

        # --- requests (full single-GET) ---
        rfcs = [
            r.get("RFC_NUMBER")
            for r in get("requests", max_rows=SAMPLE)
            if r.get("RFC_NUMBER")
        ]
        recs = [get(f"requests/{rfc}")[0] for rfc in rfcs]
        entities = [("Requests (tickets)", "requests", recs, _declared(Request))]

        # --- assets (full single-GET) ---
        aids = [
            a.get("ASSET_ID")
            for a in get("assets", max_rows=SAMPLE)
            if a.get("ASSET_ID")
        ]
        arecs = []
        for aid in aids:
            try:
                arecs.append(get(f"assets/{aid}")[0])
            except EasyvistaError:
                pass
        entities.append(
            (
                "Assets",
                "assets",
                arecs or get("assets", max_rows=SAMPLE),
                _declared(Asset),
            )
        )

        # --- actions (from the sampled tickets) ---
        actions: list[dict] = []
        for rfc in rfcs:
            try:
                actions += get(
                    "actions", search=f'REQUEST.RFC_NUMBER:"{rfc}"', max_rows=SAMPLE
                )
            except EasyvistaError:
                pass
        entities.append(
            ("Actions", "requests/{rfc}/actions", actions, _declared(Action))
        )

        # --- documents: scan more tickets via the typed method until some
        # have attachments ---
        docs: list[dict] = []
        for rfc in [
            r.get("RFC_NUMBER")
            for r in get("requests", max_rows=40)
            if r.get("RFC_NUMBER")
        ]:
            try:
                docs += [
                    d.model_dump(by_alias=True) for d in client.list_documents(rfc)
                ]
            except EasyvistaError:
                pass
            if len(docs) >= SAMPLE:
                break
        entities.append(
            ("Documents", "requests/{rfc}/documents", docs, _declared(Document))
        )

        # --- departments (full single-GET) ---
        dids = [
            d.get("DEPARTMENT_ID")
            for d in get("departments", max_rows=SAMPLE)
            if d.get("DEPARTMENT_ID")
        ]
        drecs = [get(f"departments/{d}")[0] for d in dids]
        dept_declared = {
            "DEPARTMENT_ID",
            "DEPARTMENT_CODE",
            "DEPARTMENT_PATH",
            "MANAGER_ID",
            "LEVEL",
            "HREF",
            "COMMENT_DEPARTMENT",
        } | {f"DEPARTMENT_{s}" for s in ("EN", "FR", "GE", "IT", "PO", "SP")}
        entities.append(("Departments", "departments", drecs, dept_declared))

        # --- employees (full single-GET; E_MAIL declared official) ---
        eids = [
            e.get("EMPLOYEE_ID")
            for e in get("employees", max_rows=SAMPLE)
            if e.get("EMPLOYEE_ID")
        ]
        erecs = [get(f"employees/{e}")[0] for e in eids]
        emp_declared = {
            "EMPLOYEE_ID",
            "LAST_NAME",
            "E_MAIL",
            "DEPARTMENT_ID",
            "LOCATION_ID",
            "PROFIL_ID",
            "MANAGER_ID",
            "IDENTIFICATION",
            "LOGIN",
            "FUNCTION_ID",
            "LANGUAGE_ID",
            "HREF",
            "COMMENT_EMPLOYEE",
        }
        entities.append(("Employees", "employees", erecs, emp_declared))

        for label, path, records, declared in entities:
            records = [r for r in records if isinstance(r, dict)]
            merged = _merge(records)
            g = _classify(merged, declared)
            summary.append((label, len(merged), g))
            out.append(_section(label, path, len(records), len(merged), g))

    header = [
        # Deliberately host/account-free: the output is a local reference, and
        # naming the instance here is what previously leaked it into the repo.
        "# EasyVista Field Inventory",
        "",
        "Read-only inventory of every field the **reachable** endpoints return"
        " on this instance, classified",
        "with the generic field model (official / custom `e_*` / available /"
        " link). Regenerate with",
        "`.\\.venv\\Scripts\\python.exe scripts/generate_field_inventory.py`."
        " Blocked endpoints (`locations`, `catalog-requests`, …) are omitted —"
        " see `easyvista-test-profile-blocked-operations.md`.",
        "",
        "> **Classification note:** *custom* means the documented EasyVista `e_`"
        " prefix **only**. Instance- or integration-specific columns without that"
        " prefix (e.g. `JENKINS_FIELD_x`, `*_IDENTIFIER` on assets) are reported"
        " as **official**, by design — the `e_` prefix is the API's sole"
        " custom-field marker. Single-record GETs are used where available, so"
        " counts exceed the leaner list-endpoint projections.",
        "",
        "| Entity | Total | Official (scalar) | Ref objects | Custom `e_*` |"
        " Available | Links |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, total, g in summary:
        header.append(
            f"| {label} | {total} | {len(g['scalars'])} | {len(g['ref_objs'])} | "
            f"{len(g['custom'])} | {len(g['available'])} | {len(g['links'])} |"
        )
    header.append("")

    _OUT.write_text("\n".join(header) + "\n" + "\n".join(out), encoding="utf-8")
    print(f"Wrote {_OUT}")
    for label, total, g in summary:
        print(
            f"  {label:24} total={total:3}  custom={len(g['custom'])}  "
            f"links={len(g['links'])}  available={len(g['available'])}"
        )


if __name__ == "__main__":
    main()
