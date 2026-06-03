#!/usr/bin/env python3
"""
Find JavaScript web resources on the Contact form that may be blocking
duplicate contact creation via an on-save email uniqueness check.
"""

import traceback
from config.crm_connection import crm_get

try:
    # 1. Find the main Contact forms
    print("Finding Contact forms...")
    forms = crm_get("systemforms", {
        "$select": "formid,name,type,formxml",
        "$filter": "objecttypecode eq 'contact' and type eq 2",  # type 2 = Main form
        "$top": 10,
    }).get("value", [])

    print(f"Found {len(forms)} main Contact form(s)\n")

    # 2. Extract JavaScript libraries from each form's XML
    import re
    all_libraries = set()

    for form in forms:
        name = form.get("name", "?")
        xml = form.get("formxml", "") or ""

        # Extract library references from formxml
        libs = re.findall(r'library name="([^"]+)"', xml)
        events = re.findall(r'<handler[^>]+functionname="([^"]+)"[^>]*libraryname="([^"]+)"', xml)

        print(f"Form: {name} ({form.get('formid')})")
        if libs:
            print(f"  Libraries: {libs}")
        if events:
            print(f"  Event handlers:")
            for fn, lib in events:
                print(f"    {fn}  →  {lib}")
        if not libs and not events:
            print("  No JavaScript libraries found on this form")
        print()
        all_libraries.update(libs)

    # 3. Fetch the content of suspicious web resources
    if all_libraries:
        print("=" * 60)
        print("Checking web resource content for duplicate/email checks")
        print("=" * 60)
        for lib in all_libraries:
            try:
                results = crm_get("webresourceset", {
                    "$select": "webresourceid,name,displayname,content",
                    "$filter": f"name eq '{lib}'",
                }).get("value", [])

                if not results:
                    # Try without publisher prefix
                    short = lib.split("/")[-1]
                    results = crm_get("webresourceset", {
                        "$select": "webresourceid,name,displayname,content",
                        "$filter": f"contains(name,'{short}')",
                        "$top": 3,
                    }).get("value", [])

                for wr in results:
                    import base64
                    content_b64 = wr.get("content", "") or ""
                    try:
                        content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                    except Exception:
                        content = content_b64

                    has_dup = any(k in content.lower() for k in
                                  ["duplicate", "already exists", "emailaddress", "prevent"])

                    print(f"\n  [{wr['name']}]")
                    print(f"  Contains duplicate/email logic: {'YES — SUSPICIOUS' if has_dup else 'no'}")

                    if has_dup:
                        # Print the relevant lines
                        lines = content.splitlines()
                        for i, line in enumerate(lines):
                            if any(k in line.lower() for k in
                                   ["duplicate", "already exists", "emailaddress1", "prevent"]):
                                start = max(0, i - 1)
                                end = min(len(lines), i + 4)
                                for l in lines[start:end]:
                                    print(f"    {l[:120]}")
                                print("    ---")

            except Exception as e:
                print(f"  Error fetching {lib}: {e}")

    # 4. Also search all web resources for duplicate-contact logic
    print()
    print("=" * 60)
    print("Searching all web resources for duplicate contact prevention")
    print("=" * 60)
    try:
        suspicious = crm_get("webresourceset", {
            "$select": "webresourceid,name,webresourcetype",
            "$filter": "webresourcetype eq 3",  # type 3 = JavaScript
            "$top": 500,
        }).get("value", [])

        print(f"Checking {len(suspicious)} JavaScript web resource(s)...\n")

        for wr in suspicious:
            try:
                full = crm_get(f"webresourceset({wr['webresourceid']})", {
                    "$select": "name,content",
                })
                content_b64 = full.get("content", "") or ""
                try:
                    import base64
                    content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                except Exception:
                    content = content_b64

                if ("already exists" in content.lower() or
                        ("duplicate" in content.lower() and "contact" in content.lower())):
                    print(f"  FOUND: {wr['name']}")
                    lines = content.splitlines()
                    for i, line in enumerate(lines):
                        if "already exists" in line.lower() or (
                                "duplicate" in line.lower() and "contact" in line.lower()):
                            start = max(0, i - 2)
                            end = min(len(lines), i + 5)
                            for l in lines[start:end]:
                                print(f"    {l[:120]}")
                            print("    ---")
            except Exception:
                pass

    except Exception as e:
        print(f"Error searching web resources: {e}")

except Exception:
    traceback.print_exc()
