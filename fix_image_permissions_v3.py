#!/usr/bin/env python3
"""
Find annotation/image privileges via FetchXML and check field-level security
for the Accounting role.
"""

import traceback
from config.crm_connection import crm_get, crm_action

ACCOUNTING_ROLE_NAME = "0 - TYR - Accounting"

try:
    # 1. Find Accounting role
    roles = crm_get("roles", {
        "$select": "roleid,name",
        "$filter": f"name eq '{ACCOUNTING_ROLE_NAME}'",
    }).get("value", [])

    if not roles:
        print(f"ERROR: Role '{ACCOUNTING_ROLE_NAME}' not found.")
        exit(1)

    acct_role_id = roles[0]["roleid"]
    print(f"Found role: {ACCOUNTING_ROLE_NAME} ({acct_role_id})\n")

    # 2. Use FetchXML to find annotation/note privileges
    # (OData filter on `privileges` doesn't return system entity privileges)
    print("=" * 60)
    print("1. Searching for annotation privileges via FetchXML")
    print("=" * 60)

    fetchxml = (
        "<fetch>"
        "<entity name='privilege'>"
        "<attribute name='privilegeid'/>"
        "<attribute name='name'/>"
        "<filter type='or'>"
        "<condition attribute='name' operator='like' value='%nnotation%'/>"
        "<condition attribute='name' operator='like' value='%ttachment%'/>"
        "</filter>"
        "</entity>"
        "</fetch>"
    )

    found_privs = []
    try:
        result = crm_get("privileges", {"fetchXml": fetchxml})
        found_privs = result.get("value", [])
        print(f"FetchXML found {len(found_privs)} privilege(s):")
        for p in found_privs:
            print(f"  {p.get('name')}  ({p.get('privilegeid')})")
    except Exception as e:
        print(f"FetchXML query failed: {e}")

    if found_privs:
        privileges_to_grant = [
            {"Depth": "Global", "PrivilegeId": p["privilegeid"]}
            for p in found_privs
        ]
        print(f"\nGranting {len(privileges_to_grant)} privilege(s) to '{ACCOUNTING_ROLE_NAME}'...")
        crm_action(
            f"roles({acct_role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole",
            {"Privileges": privileges_to_grant},
        )
        print("Done — ask accounting users to sign out and back in to Dynamics 365.")
    else:
        print("\nCould not retrieve annotation privileges via API.")

    # 3. Check field-level security profiles assigned to the Accounting role
    print()
    print("=" * 60)
    print("2. Field-level security profiles on Accounting role users")
    print("=" * 60)
    try:
        # Get users with this security role
        role_users = crm_get(f"roles({acct_role_id})/systemuserroles_association", {
            "$select": "systemuserid,fullname",
            "$top": 10,
        }).get("value", [])

        print(f"Checking {len(role_users)} user(s) with this role...")

        for user in role_users[:3]:  # check first 3 users
            uid = user.get("systemuserid")
            uname = user.get("fullname", "?")
            try:
                profiles = crm_get(f"systemusers({uid})/fieldlevelsecurityprofile_systemuser", {
                    "$select": "fieldsecurityprofileid,name",
                }).get("value", [])
                if profiles:
                    print(f"\n  {uname} has {len(profiles)} field-level security profile(s):")
                    for pr in profiles:
                        print(f"    - {pr.get('name')}")
                else:
                    print(f"  {uname}: no field-level security profiles")
            except Exception as e:
                print(f"  {uname}: could not check profiles ({e})")
    except Exception as e:
        print(f"  Error fetching role users: {e}")

    # 4. Check if annotation entity has document management disabled
    print()
    print("=" * 60)
    print("3. Annotation entity settings")
    print("=" * 60)
    try:
        ann_meta = crm_get("EntityDefinitions(LogicalName='annotation')", {
            "$select": "LogicalName,IsDocumentManagementEnabled,IsAuditEnabled,CanBeInManyToMany",
        })
        print(f"  IsDocumentManagementEnabled: {ann_meta.get('IsDocumentManagementEnabled')}")
        print(f"  LogicalName: {ann_meta.get('LogicalName')}")
    except Exception as e:
        print(f"  Could not fetch annotation metadata: {e}")

    # 5. Spot-check: can we read any annotation records at all?
    print()
    print("=" * 60)
    print("4. Sample annotation records (confirms entity is accessible)")
    print("=" * 60)
    try:
        annotations = crm_get("annotations", {
            "$select": "annotationid,subject,filename,mimetype,isdocument",
            "$filter": "isdocument eq true",
            "$top": 3,
            "$orderby": "createdon desc",
        }).get("value", [])
        print(f"  Found {len(annotations)} recent document annotation(s) in the org:")
        for a in annotations:
            print(f"  - {a.get('filename', 'no filename')}  ({a.get('mimetype', '?')})")
            print(f"    annotationid: {a.get('annotationid')}")
    except Exception as e:
        print(f"  Could not read annotations: {e}")

except Exception:
    traceback.print_exc()
