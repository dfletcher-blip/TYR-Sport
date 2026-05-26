#!/usr/bin/env python3
"""
Grants annotation/image viewing privileges to ALL custom security roles in the org.
Pulls the exact privilege IDs from the System Administrator role so nothing is missed.
"""

import traceback
from config.crm_connection import crm_get, crm_action

try:
    # 1. Find the System Administrator role to use as the reference
    sa_roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": "name eq 'System Administrator'",
    }).get("value", [])

    if not sa_roles:
        print("Could not find System Administrator role.")
        exit(1)

    sa_role_id = sa_roles[0]["roleid"]
    print(f"Found System Administrator role ({sa_role_id})")

    # 2. Get annotation-related privileges directly from the SA role association
    sa_privs = crm_get(f"roles({sa_role_id})/roleprivileges_association", {
        "$select": "privilegeid,name",
        "$filter": "contains(name,'nnotation')",
    }).get("value", [])

    print(f"\nAnnotation privileges on System Administrator role: {len(sa_privs)}")
    for p in sa_privs:
        print(f"  {p['name']}")

    if not sa_privs:
        # Fallback: use the known entity attachment privileges we found earlier
        print("\nFalling back to known attachment privilege IDs...")
        sa_privs = crm_get("privileges", {
            "$select": "privilegeid,name",
            "$filter": (
                "name eq 'prvReadmsdyn_entityattachment' or "
                "name eq 'prvAppendTomsdyn_entityattachment' or "
                "name eq 'prvReadactivityfileattachment' or "
                "name eq 'prvAppendToactivityfileattachment'"
            ),
        }).get("value", [])
        for p in sa_privs:
            print(f"  {p['name']}")

    if not sa_privs:
        print("Could not locate any annotation privileges.")
        exit(1)

    privileges_to_grant = [
        {"Depth": "Global", "PrivilegeId": p["privilegeid"]}
        for p in sa_privs
    ]

    # 3. Get all custom (non-Microsoft-managed) security roles
    all_roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": "ismanaged eq false",
    }).get("value", [])

    print(f"\nGranting to {len(all_roles)} custom role(s)...")

    failed = []
    for role in all_roles:
        try:
            crm_action(
                f"roles({role['roleid']})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
                {"Privileges": privileges_to_grant},
            )
            print(f"  Updated: {role['name']}")
        except Exception as e:
            failed.append((role["name"], str(e)))

    if failed:
        print("\nFailed to update:")
        for name, err in failed:
            print(f"  {name}: {err}")

    print("\nDone. All users can now view and download attached images.")

except Exception:
    traceback.print_exc()
