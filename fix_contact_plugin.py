#!/usr/bin/env python3
"""
Find and deactivate ALL active plugin steps from the Tyr_PreventContactDuplicate
assembly across any message (Create, Update, etc.) and any entity.
Also checks if duplicate detection rules crept back on.
"""

import traceback
from config.crm_connection import crm_get, crm_patch

try:
    # 1. Find all active steps from the duplicate-prevention assembly
    print("Searching for all active Tyr_PreventContactDuplicate plugin steps...\n")

    steps = crm_get("sdkmessageprocessingsteps", {
        "$select": "sdkmessageprocessingstepid,name,statecode,stage",
        "$expand": "plugintypeid($select=typename,assemblyname)",
        "$filter": "statecode eq 0",
        "$top": 500,
    }).get("value", [])

    target_steps = [
        s for s in steps
        if "preventcontactduplicate" in (
            (s.get("plugintypeid") or {}).get("typename", "")
        ).lower()
        or "preventcontactduplicate" in (
            (s.get("plugintypeid") or {}).get("assemblyname", "")
        ).lower()
    ]

    if not target_steps:
        print("No active Tyr_PreventContactDuplicate steps found in full scan.")
        print("Checking if the previously deactivated step was re-activated...\n")

        KNOWN_STEP_ID = "c5b981ae-7411-f111-8406-7ced8d3cc447"
        step = crm_get(f"sdkmessageprocessingsteps({KNOWN_STEP_ID})", {
            "$select": "name,statecode,statuscode",
        })
        state = step.get("statecode")
        print(f"  Step: {step.get('name')}")
        print(f"  statecode: {state}  (0=Active, 1=Inactive)")
        if state == 0:
            print("  → Step is ACTIVE again — deactivating now...")
            crm_patch("sdkmessageprocessingsteps", KNOWN_STEP_ID,
                      {"statecode": 1, "statuscode": 2})
            print("  → Deactivated.")
        else:
            print("  → Still inactive — block is coming from something else.")
    else:
        print(f"Found {len(target_steps)} active step(s) — deactivating all:\n")
        for s in target_steps:
            typename = (s.get("plugintypeid") or {}).get("typename", "?")
            print(f"  [{s['stage']}] {s['name']}  ({typename})")
            crm_patch("sdkmessageprocessingsteps",
                      s["sdkmessageprocessingstepid"],
                      {"statecode": 1, "statuscode": 2})
            print(f"       → Deactivated.")

    # 2. Re-check and disable any contact duplicate detection rules
    print("\nChecking contact duplicate detection rules...")
    rules = crm_get("duplicaterules", {
        "$select": "duplicateruleid,name,statecode",
        "$filter": "baseentityname eq 'contact' and statecode eq 0",
    }).get("value", [])

    if rules:
        print(f"  Found {len(rules)} active rule(s) — disabling:")
        for rule in rules:
            crm_patch("duplicaterules", rule["duplicateruleid"],
                      {"statecode": 1, "statuscode": 2})
            print(f"  → Disabled: {rule['name']}")
    else:
        print("  No active duplicate detection rules — clean.")

    print("\nDone. Jennifer should be able to save the contact now.")
    print("If the error persists, it may be a Business Rule on the Contact form")
    print("— share the exact error text and we can check that next.")

except Exception:
    traceback.print_exc()
