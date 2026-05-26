#!/usr/bin/env python3
"""
Compare Accounting role privileges against System Administrator to find the gap
causing users to be unable to view/download images.
"""

import traceback
from config.crm_connection import crm_get, crm_action

ACCOUNTING_ROLE_NAME = "0 - TYR - Accounting"
SA_ROLE_ID = "8ff322d5-d2ca-f011-8543-000d3a34ed11"

try:
    # 1. Find the Accounting role
    roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": f"name eq '{ACCOUNTING_ROLE_NAME}'",
    }).get("value", [])

    if not roles:
        print(f"ERROR: Role '{ACCOUNTING_ROLE_NAME}' not found.")
        exit(1)

    acct_role_id = roles[0]["roleid"]
    print(f"Found role: {ACCOUNTING_ROLE_NAME} ({acct_role_id})\n")

    # 2. Pull ALL privileges from both roles via RetrieveRolePrivilegesRole
    def get_role_privs(role_id, label):
        try:
            result = crm_get(
                f"roles({role_id})/Microsoft.Dynamics.CRM.RetrieveRolePrivilegesRole()",
                {},
            )
            privs = result.get("RolePrivileges", [])
            print(f"  {label}: {len(privs)} privileges via RetrieveRolePrivilegesRole")
            return {p["PrivilegeId"]: p for p in privs}
        except Exception as e:
            print(f"  RetrieveRolePrivilegesRole failed for {label}: {e}")

        # Fallback: roleprivileges_association (no filter — get all pages)
        all_privs = []
        skip = 0
        while True:
            try:
                page = crm_get(f"roles({role_id})/roleprivileges_association", {
                    "$select": "privilegeid,name",
                    "$top": 500,
                    "$skip": skip,
                }).get("value", [])
                all_privs.extend(page)
                if len(page) < 500:
                    break
                skip += 500
            except Exception as e:
                print(f"  roleprivileges_association page {skip} failed: {e}")
                break
        print(f"  {label}: {len(all_privs)} privileges via roleprivileges_association")
        return {p["privilegeid"]: p for p in all_privs}

    print("Fetching privileges...")
    sa_privs   = get_role_privs(SA_ROLE_ID, "System Administrator")
    acct_privs = get_role_privs(acct_role_id, ACCOUNTING_ROLE_NAME)
    print()

    # 3. Find annotation/attachment privileges in SA that are missing from Accounting
    keywords = ["annotation", "attachment", "msdyn_entity", "activityfile"]

    print("=" * 60)
    print("Annotation/attachment privileges on System Administrator:")
    print("=" * 60)
    relevant_sa = {}
    for pid, p in sa_privs.items():
        name = (p.get("PrivilegeName") or p.get("name") or "").lower()
        if any(k in name for k in keywords):
            relevant_sa[pid] = p
            in_acct = "YES" if pid in acct_privs else "MISSING"
            print(f"  [{in_acct}] {p.get('PrivilegeName') or p.get('name')}")

    if not relevant_sa:
        print("  No annotation/attachment privileges found on SA role.")
        print("  Trying direct privilege name lookup instead...\n")

        # Try looking up prvReadAnnotation directly
        for pname in ["prvReadAnnotation", "prvWriteAnnotation", "prvCreateAnnotation",
                      "prvAppendAnnotation", "prvAppendToAnnotation", "prvDeleteAnnotation"]:
            result = crm_get("privileges", {
                "$select": "privilegeid,name",
                "$filter": f"name eq '{pname}'",
            }).get("value", [])
            if result:
                pid = result[0]["privilegeid"]
                in_acct = "YES" if pid in acct_privs else "MISSING"
                relevant_sa[pid] = {"PrivilegeId": pid, "PrivilegeName": pname}
                print(f"  [{in_acct}] {pname}  (id: {pid})")
            else:
                print(f"  [NOT IN ORG] {pname}")

    missing = {pid: p for pid, p in relevant_sa.items() if pid not in acct_privs}
    print(f"\nMissing from '{ACCOUNTING_ROLE_NAME}': {len(missing)}")
    for pid, p in missing.items():
        print(f"  {p.get('PrivilegeName') or p.get('name')}")

    # 4. Grant missing privileges
    if missing:
        print(f"\nGranting {len(missing)} missing privilege(s) to '{ACCOUNTING_ROLE_NAME}'...")
        privileges_to_grant = [
            {"Depth": "Global", "PrivilegeId": pid}
            for pid in missing
        ]
        crm_action(
            f"roles({acct_role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
            {"Privileges": privileges_to_grant},
        )
        print("Done. Ask accounting users to sign out and back in to Dynamics 365.")
    else:
        print("\nAccounting role already has all annotation/attachment privileges.")
        print("The issue may be something other than role permissions:")
        print("  - Field-level security profile restricting the annotation entity")
        print("  - Images stored in a location requiring different access (SharePoint, etc.)")
        print("  - Browser/client cache — try signing out and back in")

except Exception:
    traceback.print_exc()
