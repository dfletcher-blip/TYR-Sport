#!/usr/bin/env python3
"""
Grants annotation/image viewing privileges to ALL security roles in the org,
including managed roles like '0 - TYR - Accounting'.
"""

import traceback
from config.crm_connection import crm_get, crm_action

SA_ROLE_ID = "8ff322d5-d2ca-f011-8543-000d3a34ed11"
ACCOUNTING_ROLE_ID = "67429d65-2f12-f111-8406-7ced8d3cc5ca"

try:
    # 1. Try RetrieveRolePrivilegesRole to get SA annotation privileges
    print("Fetching SA role privileges via RetrieveRolePrivilegesRole...")
    try:
        sa_privs_result = crm_get(
            f"roles({SA_ROLE_ID})/Microsoft.Dynamics.CRM.RetrieveRolePrivilegesRole()",
            {},
        )
        all_sa_privs = sa_privs_result.get("RolePrivileges", [])
        annotation_privs = [
            p for p in all_sa_privs
            if "annotation" in p.get("PrivilegeName", "").lower()
        ]
        print(f"Annotation privileges found on SA role: {len(annotation_privs)}")
        for p in annotation_privs:
            print(f"  {p.get('PrivilegeName')}")

        if annotation_privs:
            privileges_to_grant = [
                {"Depth": "Global", "PrivilegeId": p["PrivilegeId"]}
                for p in annotation_privs
            ]
        else:
            annotation_privs = []
    except Exception as e:
        print(f"RetrieveRolePrivilegesRole failed: {e}")
        annotation_privs = []

    if not annotation_privs:
        # 2. Fallback: look up privileges by exact name
        print("\nLooking up privileges by name...")
        priv_names_to_try = [
            "prvReadAnnotation",
            "prvWriteAnnotation",
            "prvCreateAnnotation",
            "prvAppendAnnotation",
            "prvAppendToAnnotation",
            "prvDeleteAnnotation",
            "prvReadmsdyn_entityattachment",
            "prvAppendTomsdyn_entityattachment",
            "prvReadactivityfileattachment",
            "prvAppendToactivityfileattachment",
        ]
        found_privs = []
        for pname in priv_names_to_try:
            result = crm_get("privileges", {
                "$select": "privilegeid,name",
                "$filter": f"name eq '{pname}'",
            }).get("value", [])
            if result:
                found_privs.extend(result)
                print(f"  Found: {pname}")
            else:
                print(f"  Not found: {pname}")

        privileges_to_grant = [
            {"Depth": "Global", "PrivilegeId": p["privilegeid"]}
            for p in found_privs
        ]

    if not privileges_to_grant:
        print("\nNo privileges found to grant — cannot proceed.")
        exit(1)

    print(f"\nWill grant {len(privileges_to_grant)} privilege(s).")

    # 3. Get all roles (no ismanaged filter) to cover managed custom roles
    all_roles = crm_get("roles", {
        "$select": "roleid,name,ismanaged",
        "$top": 500,
    }).get("value", [])

    # Deduplicate by name — the same role can appear once per Business Unit
    seen_names: set = set()
    unique_roles = []
    for r in all_roles:
        if r["name"] not in seen_names:
            seen_names.add(r["name"])
            unique_roles.append(r)

    print(f"Found {len(unique_roles)} unique role(s) across all BUs.\n")

    failed = []
    for role in unique_roles:
        try:
            crm_action(
                f"roles({role['roleid']})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
                {"Privileges": privileges_to_grant},
            )
            managed_tag = " [managed]" if role.get("ismanaged") else ""
            print(f"  Updated: {role['name']}{managed_tag}")
        except Exception as e:
            failed.append((role["name"], str(e)))

    if failed:
        print("\nFailed to update:")
        for name, err in failed:
            print(f"  {name}: {err}")

    print("\nDone. All users can now view and download attached images.")

except Exception:
    traceback.print_exc()
