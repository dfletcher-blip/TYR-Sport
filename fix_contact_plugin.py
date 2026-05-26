#!/usr/bin/env python3
"""
Finds and deactivates the custom plugin step that blocks contact creation
when a contact with the same email already exists.
"""

import traceback
from config.crm_connection import crm_get, crm_patch

try:
    # 1. Find the SDK message ID for "Create"
    msgs = crm_get("sdkmessages", {
        "$select": "sdkmessageid,name",
        "$filter": "name eq 'Create'",
    }).get("value", [])

    if not msgs:
        print("Could not find 'Create' SDK message.")
        exit(1)

    create_msg_id = msgs[0]["sdkmessageid"]

    # 2. Find the message filter for the Contact entity + Create
    filters = crm_get("sdkmessagefilters", {
        "$select": "sdkmessagefilterid,primaryobjecttypecode",
        "$filter": f"primaryobjecttypecode eq 'contact' and _sdkmessageid_value eq {create_msg_id}",
    }).get("value", [])

    if not filters:
        print("Could not find Contact+Create message filter.")
        exit(1)

    filter_id = filters[0]["sdkmessagefilterid"]

    # 3. Find all active plugin steps on Contact Create
    steps = crm_get("sdkmessageprocessingsteps", {
        "$select": "sdkmessageprocessingstepid,name,statecode,stage",
        "$expand": "plugintypeid($select=typename)",
        "$filter": f"_sdkmessagefilterid_value eq {filter_id} and statecode eq 0",
    }).get("value", [])

    if not steps:
        print("No active plugin steps found on Contact Create.")
        print("The block may be coming from a workflow or business rule instead.")
        exit(0)

    print(f"Found {len(steps)} active plugin step(s) on Contact Create:\n")
    for s in steps:
        typename = (s.get("plugintypeid") or {}).get("typename", "Unknown")
        print(f"  Name:   {s['name']}")
        print(f"  Type:   {typename}")
        print(f"  Stage:  {s['stage']}  (10=PreValidation, 20=PreOperation, 40=PostOperation)")
        print(f"  ID:     {s['sdkmessageprocessingstepid']}")
        print()

    # 4. Deactivate custom (non-Microsoft) steps that relate to duplicate/unique checks.
    # Skip anything from Microsoft.Crm or Microsoft.Dynamics — those are system plugins
    # and cannot be modified.
    keywords = ["duplicate", "unique", "email", "prevent"]
    deactivated = []
    for s in steps:
        typename = (s.get("plugintypeid") or {}).get("typename", "")
        name = s.get("name", "")
        is_microsoft = typename.lower().startswith("microsoft.")
        matches_keyword = any(k in name.lower() or k in typename.lower() for k in keywords)
        if not is_microsoft and matches_keyword:
            crm_patch(
                "sdkmessageprocessingsteps",
                s["sdkmessageprocessingstepid"],
                {"statecode": 1, "statuscode": 2},
            )
            deactivated.append(name)
            print(f"Deactivated: {name}")

    if not deactivated:
        print("No custom duplicate-related steps found to deactivate.")
        print("Review the list above and share the plugin name blocking creation.")

except Exception:
    traceback.print_exc()
