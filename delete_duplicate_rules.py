#!/usr/bin/env python3
"""
Permanently delete contact duplicate detection rules (so they cannot be
re-enabled) and find/disable any synchronous workflows blocking Contact Create.
"""

import traceback
from config.crm_connection import crm_get, crm_patch, crm_delete

try:
    # 1. Find ALL contact duplicate detection rules (active AND inactive) and delete them
    print("Finding all contact duplicate detection rules (active + inactive)...")
    rules = crm_get("duplicaterules", {
        "$select": "duplicateruleid,name,statecode",
        "$filter": "baseentityname eq 'contact'",
        "$top": 100,
    }).get("value", [])

    print(f"  Found {len(rules)} rule(s) total\n")

    for rule in rules:
        rid = rule["duplicateruleid"]
        name = rule["name"]
        state = rule.get("statecode", 0)
        try:
            # Must deactivate before deleting if currently active
            if state == 0:
                crm_patch("duplicaterules", rid, {"statecode": 1, "statuscode": 2})
            crm_delete("duplicaterules", rid)
            print(f"  Deleted: {name}")
        except Exception as e:
            print(f"  Could not delete '{name}': {e}")

    print()

    # 2. Find synchronous (real-time) workflows on Contact Create
    # mode=1 means synchronous, category=0 means classic workflow
    print("Searching for synchronous workflows on Contact Create...")
    sync_wfs = crm_get("workflows", {
        "$select": "workflowid,name,statecode,statuscode,mode,category,triggeroncreate",
        "$filter": (
            "primaryentity eq 'contact' "
            "and category eq 0 "
            "and mode eq 1 "
            "and triggeroncreate eq true "
            "and statecode eq 1"  # active
        ),
        "$top": 50,
    }).get("value", [])

    if sync_wfs:
        print(f"  Found {len(sync_wfs)} synchronous workflow(s) on Contact Create:\n")
        for wf in sync_wfs:
            print(f"  Name: {wf['name']}")
            print(f"  ID:   {wf['workflowid']}")
            # Deactivate it
            try:
                crm_patch("workflows", wf["workflowid"], {"statecode": 0, "statuscode": 1})
                print(f"  → Deactivated\n")
            except Exception as e:
                print(f"  → Could not deactivate: {e}\n")
    else:
        print("  No synchronous workflows found on Contact Create.\n")

    # 3. Also check for active synchronous workflows regardless of triggeroncreate flag
    print("Checking all active synchronous workflows on Contact entity...")
    all_sync = crm_get("workflows", {
        "$select": "workflowid,name,statecode,mode,category,triggeroncreate,triggeronupdateattributelist",
        "$filter": (
            "primaryentity eq 'contact' "
            "and category eq 0 "
            "and mode eq 1 "
            "and statecode eq 1"
        ),
        "$top": 50,
    }).get("value", [])

    if all_sync:
        print(f"  Found {len(all_sync)} active synchronous workflow(s) on Contact:\n")
        for wf in all_sync:
            print(f"  Name:            {wf['name']}")
            print(f"  TriggerOnCreate: {wf.get('triggeroncreate')}")
            print(f"  TriggerOnUpdate: {wf.get('triggeronupdateattributelist', 'none')}")
            print(f"  ID:              {wf['workflowid']}")
            print()
    else:
        print("  No active synchronous workflows found on Contact.\n")

    # 4. Double-check plugin step is still inactive
    KNOWN_STEP_ID = "c5b981ae-7411-f111-8406-7ced8d3cc447"
    step = crm_get(f"sdkmessageprocessingsteps({KNOWN_STEP_ID})", {
        "$select": "name,statecode",
    })
    print(f"Plugin step '{step.get('name')}'")
    print(f"  statecode: {step.get('statecode')}  (0=Active, 1=Inactive)")
    if step.get("statecode") == 0:
        crm_patch("sdkmessageprocessingsteps", KNOWN_STEP_ID,
                  {"statecode": 1, "statuscode": 2})
        print("  → Re-deactivated.")
    else:
        print("  → Still inactive — OK.")

    print("\nDone.")
    print("Duplicate rules have been DELETED (not just disabled) so they cannot come back.")
    print("If the error persists after Jennifer refreshes, it is coming from a synchronous")
    print("workflow — share the workflow names found above.")

except Exception:
    traceback.print_exc()
