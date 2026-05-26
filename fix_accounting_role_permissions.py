#!/usr/bin/env python3
"""
Grants the '0 - TYR - Accounting' security role permission to view and
download attached images and files in Dynamics 365.
"""

import traceback
from config.crm_connection import crm_get, crm_action

ROLE_NAME = "0 - TYR - Accounting"

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
    print(f"Found role: {ROLE_NAME}  ({role_id})")

    # 2. Search broadly for annotation-related privileges to find exact names
    all_privs = crm_get("privileges", {
        "$select": "privilegeid,name",
        "$filter": "contains(name,'nnotation')",
    }).get("value", [])

    if not all_privs:
        all_privs = crm_get("privileges", {
            "$select": "privilegeid,name",
            "$filter": "contains(name,'ttach')",
        }).get("value", [])

    print(f"\nAnnotation/attachment privileges found in this org:")
    for p in all_privs:
        print(f"  {p['name']}  ({p['privilegeid']})")

    # 3. Grant Read and AppendTo on Annotation matched by partial name
    target_keywords = ["readannotation", "appendtoannotation"]
    privileges_to_grant = []
    for priv in all_privs:
        if any(kw in priv["name"].lower() for kw in target_keywords):
            privileges_to_grant.append({
                "Depth": "Global",
                "PrivilegeId": priv["privilegeid"],
            })
            print(f"\nGranting: {priv['name']}")

    if not privileges_to_grant:
        print("\nCould not match target privileges — see list above to identify correct names.")
        exit(1)

    crm_action(
        f"roles({role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
        {"Privileges": privileges_to_grant},
    )

    print(f"\nDone. Users in '{ROLE_NAME}' can now view and download attached images.")

except Exception:
    traceback.print_exc()
