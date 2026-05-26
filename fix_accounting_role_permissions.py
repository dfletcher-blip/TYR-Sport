#!/usr/bin/env python3
"""
Grants the '0 - TYR - Accounting' security role permission to view and
download attached images and files in Dynamics 365.

In Dynamics 365, attachments are stored as Annotation records.
The accounting role is missing Read access on that entity.
"""

import traceback
from config.crm_connection import crm_get, crm_action

ROLE_NAME = "0 - TYR - Accounting"

# Privileges required to view and download attachments/images on CRM records.
# prvReadAnnotation  — read notes and their attached files/images
# prvAppendToAnnotation — allows notes to be associated with records the user
#                         can see (needed for the attachment link to resolve)
PRIVILEGES_NEEDED = [
    "prvReadAnnotation",
    "prvAppendToAnnotation",
]

try:
    # 1. Find the role
    roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": f"name eq '{ROLE_NAME}'",
    }).get("value", [])

    if not roles:
        print(f"Role '{ROLE_NAME}' not found. Check the exact name and try again.")
        exit(1)

    role_id = roles[0]["roleid"]
    print(f"Found role: {ROLE_NAME}  ({role_id})")

    # 2. Look up each privilege by name
    privileges_to_grant = []
    for priv_name in PRIVILEGES_NEEDED:
        result = crm_get("privileges", {
            "$select": "privilegeid,name",
            "$filter": f"name eq '{priv_name}'",
        }).get("value", [])

        if result:
            privileges_to_grant.append({
                "Depth": "Global",        # Organisation-wide — matches admin access
                "PrivilegeId": result[0]["privilegeid"],
            })
            print(f"  Found privilege: {priv_name}")
        else:
            print(f"  Warning: privilege '{priv_name}' not found — skipping")

    if not privileges_to_grant:
        print("No privileges to grant.")
        exit(1)

    # 3. Add the privileges to the role
    crm_action(
        f"roles({role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
        {"Privileges": privileges_to_grant},
    )

    print(f"\nDone. Users in '{ROLE_NAME}' can now view and download attached images.")

except Exception:
    traceback.print_exc()
