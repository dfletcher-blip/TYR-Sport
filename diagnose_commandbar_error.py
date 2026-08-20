#!/usr/bin/env python3
"""
diagnose_commandbar_error.py — diagnose "Error loading CommandBar" on a grid view.

Usage:
    python diagnose_commandbar_error.py
    python diagnose_commandbar_error.py import
    python diagnose_commandbar_error.py contact

Defaults to the "import" entity, since "Error loading CommandBar" was seen
on the "My Imports" grid (Data Management > Imports).

"Error loading CommandBar" is thrown by the Dynamics 365 web client when it
fails to build the ribbon/command bar for a grid. The most common causes are:
  1. A custom ribbon button (Command/CommandDefinition) points at a JS web
     resource (Library) that no longer exists, or a function that isn't
     defined in it.
  2. An EnableRule/DisplayRule CustomRule points at a missing JS function.
  3. A JS web resource referenced by the ribbon exists but is empty/corrupt.

This script pulls the raw ribbon customization XML for the entity (and the
global Application Ribbon, which also drives grid command bars) directly
from the "ribboncustomizations" table, extracts every JavaScriptFunction
reference, and checks whether the referenced web resource actually exists.

Run it, copy the full output, and share it so we can see exactly what's
broken.
"""

import sys
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from config.crm_connection import crm_get

SEPARATOR = "─" * 70


def fetch_ribbon_layers(entity: str | None):
    """Fetch all ribboncustomizations rows for an entity (None = Application Ribbon)."""
    if entity:
        filter_str = f"entity eq '{entity}'"
    else:
        filter_str = "entity eq null"

    params = {
        "$select": "ribboncustomizationid,entity,ribbondiffxml,solutionid",
        "$filter": filter_str,
    }
    result = crm_get("ribboncustomizations", params)
    return result.get("value", [])


def extract_js_references(ribbondiffxml: str):
    """
    Walk the RibbonDiffXml and pull out every JavaScriptFunction reference
    (from CommandDefinitions and from EnableRules/DisplayRules CustomRules).
    Returns a list of dicts: {"context": str, "library": str, "function": str}
    """
    refs = []
    if not ribbondiffxml or not ribbondiffxml.strip():
        return refs

    try:
        root = ET.fromstring(ribbondiffxml)
    except ET.ParseError as e:
        print(f"    !! XML parse error in this layer: {e}")
        return refs

    for js in root.iter("JavaScriptFunction"):
        library = js.get("Library", "")
        function = js.get("FunctionName", "")
        # Walk up-ish by re-scanning ancestry isn't native to ElementTree,
        # so just tag it generically — good enough to spot broken refs.
        refs.append({"library": library, "function": function})

    return refs


def check_web_resource_exists(name: str) -> tuple[bool, int]:
    """Return (exists, content_length_chars) for a web resource by name."""
    if not name:
        return False, 0
    escaped = name.replace("'", "''")
    params = {
        "$select": "name,content",
        "$filter": f"name eq '{escaped}'",
    }
    result = crm_get("webresourceset", params)
    rows = result.get("value", [])
    if not rows:
        return False, 0
    content = rows[0].get("content") or ""
    return True, len(content)


def report_layer(label: str, rows: list):
    print(f"\n{SEPARATOR}")
    print(f"  {label}")
    print(SEPARATOR)

    if not rows:
        print("  (no ribboncustomizations rows found for this scope)")
        return []

    all_refs = []
    for row in rows:
        rid = row.get("ribboncustomizationid")
        solution_id = row.get("solutionid")
        xml = row.get("ribbondiffxml", "") or ""
        print(f"\n  Layer: {rid}")
        print(f"    solutionid:    {solution_id}")
        print(f"    ribbondiffxml: {len(xml)} chars")

        refs = extract_js_references(xml)
        if not refs:
            print("    (no JavaScriptFunction references in this layer)")
        else:
            for r in refs:
                print(f"    -> Library={r['library']!r}  Function={r['function']!r}")
                all_refs.append(r)

    return all_refs


def main():
    entity = sys.argv[1] if len(sys.argv) > 1 else "import"

    print(f"\n{SEPARATOR}")
    print(f"  COMMAND BAR DIAGNOSTIC: entity='{entity}'")
    print(SEPARATOR)

    # ── Step 1: entity-specific ribbon layers ──────────────────────────────
    entity_rows = fetch_ribbon_layers(entity)
    entity_refs = report_layer(f"[1] ENTITY RIBBON LAYERS ('{entity}')", entity_rows)

    # ── Step 2: application (global) ribbon layers ─────────────────────────
    app_rows = fetch_ribbon_layers(None)
    app_refs = report_layer("[2] APPLICATION RIBBON LAYERS (global, affects all grids)", app_rows)

    # ── Step 3: verify every referenced web resource actually exists ───────
    print(f"\n{SEPARATOR}")
    print("[3] VERIFYING REFERENCED WEB RESOURCES")
    print(SEPARATOR)

    all_refs = entity_refs + app_refs
    seen_libraries = {}
    for r in all_refs:
        lib = r["library"]
        if not lib or lib in seen_libraries:
            continue
        seen_libraries[lib] = True

    if not seen_libraries:
        print("  No JavaScriptFunction Library references found in either scope.")
        print("  The CommandBar error is likely NOT caused by a missing web")
        print("  resource on this entity — check EnableRules that call other")
        print("  entities' ribbons, or the browser console for the exact JS error.")
    else:
        broken = []
        for lib in sorted(seen_libraries):
            exists, content_len = check_web_resource_exists(lib)
            if not exists:
                print(f"  ✗ MISSING   {lib}")
                broken.append((lib, "missing"))
            elif content_len == 0:
                print(f"  ✗ EMPTY     {lib}  (0 chars of content)")
                broken.append((lib, "empty"))
            else:
                print(f"  ✓ OK        {lib}  ({content_len} chars, base64)")

        if broken:
            print(f"\n  !! Found {len(broken)} broken web resource reference(s) — this is")
            print("     almost certainly why the CommandBar fails to load:")
            for lib, why in broken:
                print(f"       - {lib} ({why})")
        else:
            print("\n  All referenced web resources exist and have content.")
            print("  The failure may be inside one of those scripts throwing at")
            print("  runtime (bad function name, JS error) rather than a missing")
            print("  resource — check the browser console (F12) on the failing")
            print("  page for the exact stack trace and function name.")

    print(f"\n{SEPARATOR}")
    print("  DIAGNOSTIC COMPLETE — copy ALL of the above and share it.")
    print(SEPARATOR + "\n")


if __name__ == "__main__":
    main()
