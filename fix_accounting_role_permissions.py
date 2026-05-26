#!/usr/bin/env python3
"""
Grants the '0 - TYR - Accounting' security role permission to view and
download attached images and files in Dynamics 365.
"""

import traceback
from config.crm_connection import crm_get, crm_action

ROLE_NAME = "0 - TYR - Accounting"

# Privileges needed to view/download attachments in this org.
# Covers both entity attachments (msdyn_entityattachment) and
# activity file attachments (activityfileattachment).
TARGET_PRIVILEGES = [
    "prvReadmsdyn_entityattachment",
    "prvAppendTomsdyn_entityattachment",
    "prvReadactivityfileattachment",
    "prvAppendToactivityfileattachment",
]

try:
    # 1. Find the role
    roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": f"name eq '{ROLE_NAME}'",
    }).get("value", [])

    if not roles:
        print(f"Role '{ROLE_NAME}' not found.")
        exit(1)

    role_id = roles[0]["roleid"]
    print(f"Found role: {ROLE_NAME}  ({role_id})\n")

    # 2. Look up each privilege by exact name
    privileges_to_grant = []
    for priv_name in TARGET_PRIVILEGES:
        result = crm_get("privileges", {
            "$select": "privilegeid,name",
            "$filter": f"name eq '{priv_name}'",
        }).get("value", [])

        if result:
            privileges_to_grant.append({
                "Depth": "Global",
                "PrivilegeId": result[0]["privilegeid"],
            })
            print(f"  Found: {priv_name}")
        else:
            print(f"  Not found: {priv_name} — skipping")

    if not privileges_to_grant:
        print("\nNo privileges matched.")
        exit(1)

    # 3. Grant them to the role
    crm_action(
        f"roles({role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
        {"Privileges": privileges_to_grant},
    )

    print(f"\nDone. Users in '{ROLE_NAME}' can now view and download attached images.")

except Exception:
    traceback.print_exc()
