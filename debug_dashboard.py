#!/usr/bin/env python3
"""
debug_dashboard.py — diagnose why dashboard reordering isn't working.

Usage:
    python debug_dashboard.py "D2C/Crossfit"

This script:
  1. Fetches the dashboard and dumps its XML structure
  2. Sends the exact same PATCH that reorder_dashboard_components sends
  3. Re-fetches the dashboard to verify whether the formxml actually changed
  4. Reports on PublishXml

Run it, copy the full output, and share it so we can see exactly what's failing.
"""

import sys
import json
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from config.crm_connection import crm_get, crm_patch, crm_action
from tools.views_dashboards import get_dashboard_details

SEPARATOR = "─" * 70


def fetch_raw(name_or_id: str):
    """Fetch dashboard and return raw row from the API."""
    import re
    guid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE,
    )
    escaped = name_or_id.replace("'", "''")

    if guid_pattern.match(name_or_id):
        params = {
            "$select": "systemformid,name,description,formxml,formactivationstate,ismanaged,iscustomizable",
            "$filter": f"systemformid eq {name_or_id} and type eq 0",
        }
    else:
        params = {
            "$select": "systemformid,name,description,formxml,formactivationstate,ismanaged,iscustomizable",
            "$filter": f"type eq 0 and contains(name,'{escaped}')",
        }

    result = crm_get("systemforms", params)
    rows = result.get("value", [])
    if rows:
        return rows[0], "system"

    # Try userforms
    if guid_pattern.match(name_or_id):
        params2 = {
            "$select": "userformid,name,description,formxml",
            "$filter": f"userformid eq {name_or_id}",
        }
    else:
        params2 = {
            "$select": "userformid,name,description,formxml",
            "$filter": f"contains(name,'{escaped}')",
        }
    result2 = crm_get("userforms", params2)
    rows2 = result2.get("value", [])
    if rows2:
        return rows2[0], "user"

    return None, None


def dump_xml_structure(formxml: str):
    """Print a human-readable tree of the XML."""
    try:
        root = ET.fromstring(formxml)
    except ET.ParseError as e:
        print(f"  !! XML parse error: {e}")
        print(f"  Raw XML (first 500 chars):\n  {formxml[:500]}")
        return

    def walk(el, indent=0):
        tag = el.tag
        attrs = {}
        for k in ("id", "name", "description", "rowspan", "colspan", "classid"):
            v = el.get(k)
            if v:
                attrs[k] = v
        labels = [lb.get("description", "") for lb in el if lb.tag == "label" and lb.get("description")]
        attr_str = "  " + "  ".join(f'{k}="{v}"' for k, v in attrs.items()) if attrs else ""
        lbl_str = f"  → labels: {labels}" if labels else ""
        print("  " + "  " * indent + f"<{tag}>{attr_str}{lbl_str}")
        if tag not in ("label", "control", "parameters"):
            for child in el:
                walk(child, indent + 1)

    walk(root)


def list_component_labels(formxml: str):
    """Return all cell labels as a flat list."""
    try:
        root = ET.fromstring(formxml)
    except ET.ParseError:
        return []
    labels = []
    for rows_el in root.iter("rows"):
        for row in rows_el:
            for cell in row:
                if cell.tag == "cell":
                    for lb in cell.iter("label"):
                        desc = lb.get("description", "")
                        if desc:
                            labels.append(desc)
    return labels


def compare_formxml(before: str, after: str) -> bool:
    """Return True if the formxml actually changed."""
    # Normalise whitespace before comparing
    def norm(s):
        try:
            root = ET.fromstring(s)
            return ET.tostring(root, encoding="unicode")
        except ET.ParseError:
            return s.strip()
    return norm(before) != norm(after)


def main():
    name_or_id = sys.argv[1] if len(sys.argv) > 1 else "D2C/Crossfit"
    print(f"\n{SEPARATOR}")
    print(f"  DASHBOARD DIAGNOSTIC: '{name_or_id}'")
    print(SEPARATOR)

    # ── Step 1: fetch ────────────────────────────────────────────────────────
    print("\n[1] FETCHING DASHBOARD ...")
    row, form_type = fetch_raw(name_or_id)
    if row is None:
        print("  !! Dashboard not found. Check the name and try again.")
        sys.exit(1)

    id_field = "systemformid" if form_type == "system" else "userformid"
    record_id   = row[id_field]
    name        = row.get("name", "?")
    formxml     = row.get("formxml", "")
    is_managed  = row.get("ismanaged")
    is_customizable = row.get("iscustomizable")

    print(f"  Name:          {name}")
    print(f"  ID:            {record_id}")
    print(f"  Form type:     {form_type}")
    print(f"  ismanaged:     {is_managed}")
    print(f"  iscustomizable:{is_customizable}")
    print(f"  formxml len:   {len(formxml)} chars")

    if not formxml:
        print("  !! formxml is EMPTY — nothing to reorder.")
        sys.exit(1)

    # ── Step 2: XML structure ────────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("[2] XML STRUCTURE")
    print(SEPARATOR)
    dump_xml_structure(formxml)

    # ── Step 3: component labels ─────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("[3] COMPONENT LABELS (cell labels only)")
    print(SEPARATOR)
    labels = list_component_labels(formxml)
    if labels:
        for i, lb in enumerate(labels):
            print(f"  [{i}] {lb!r}")
    else:
        print("  !! No cell labels found — the XML may not have <label> elements inside <cell> elements.")
        print("  Check the structure above; the dashboard might use a different layout format.")

    # ── Step 4: test PATCH ───────────────────────────────────────────────────
    print(f"\n{SEPARATOR}")
    print("[4] TESTING PATCH (re-sending unchanged formxml to confirm PATCH works)")
    print(SEPARATOR)
    endpoint = "systemforms" if form_type == "system" else "userforms"
    try:
        crm_patch(endpoint, record_id, {"formxml": formxml})
        print("  ✓ PATCH returned OK (no HTTP error)")
    except Exception as e:
        print(f"  ✗ PATCH FAILED: {e}")
        print("  → This is why the dashboard never changes!")
        sys.exit(1)

    # Re-fetch to verify formxml was actually stored
    print("\n  Re-fetching to verify formxml was saved ...")
    row2, _ = fetch_raw(name_or_id)
    formxml2 = row2.get("formxml", "") if row2 else ""
    if not formxml2:
        print("  !! Re-fetch returned empty formxml — something is wrong with fetch.")
    elif compare_formxml(formxml, formxml2):
        print("  ✓ formxml CHANGED after PATCH — writes are working.")
    else:
        print("  ✗ formxml DID NOT CHANGE after PATCH.")
        print("    Possible causes:")
        print("    - Dashboard is managed (ismanaged=True) and locked")
        print("    - The account lacks Customize Forms privilege")
        print("    - Dynamics is silently ignoring the write")

    # ── Step 5: PublishXml ───────────────────────────────────────────────────
    if form_type == "system":
        print(f"\n{SEPARATOR}")
        print("[5] TESTING PublishXml")
        print(SEPARATOR)
        publish_xml = (
            f"<importexportxml><dashboards>"
            f"<dashboard>{record_id}</dashboard>"
            f"</dashboards></importexportxml>"
        )
        print(f"  Payload: {publish_xml}")
        try:
            result = crm_action("PublishXml", {"ParameterXml": publish_xml})
            print(f"  ✓ PublishXml succeeded: {result}")
        except Exception as e:
            print(f"  ✗ PublishXml FAILED: {e}")

    print(f"\n{SEPARATOR}")
    print("  DIAGNOSTIC COMPLETE — copy ALL of the above and share it.")
    print(SEPARATOR + "\n")


if __name__ == "__main__":
    main()
