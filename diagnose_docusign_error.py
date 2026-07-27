"""
Diagnose: Angie Nicolletta (anicolletta@tyrsportoffice.onmicrosoft.com) gets
  "Failed to retrieve Docusign URL for this environment" (error code 0x0)
when trying to send a document for signature from an Opportunity/Quote record.

This error comes from the DocuSign for Dynamics 365 managed solution, not
from any TYR custom code. It almost always means one of:
  1. The DocuSign connector's stored "environment" record (org URL/ID) no
     longer matches this org's real URL/ID (common after a sandbox copy,
     org rename, or region move).
  2. No DocuSign account is linked to this environment at all, or the
     linked account's OAuth token expired/was revoked.
  3. Angie is missing the DocuSign security role, so she can't read the
     connector's configuration record even though the account IS linked.

This script inspects the org and reports which of those is happening.
Run: python diagnose_docusign_error.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
USER_EMAIL = "anicolletta@tyrsportoffice.onmicrosoft.com"

def get_headers():
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "odata.include-annotations=*",
    }

def get(path, params=None):
    r = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                      headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:500]}")
    return r.json()

print("=" * 70)
print("1. Confirm the real org URL / org ID this token is authenticating to")
print("=" * 70)
try:
    who = get("WhoAmI")
    org = get("organizations", {"$select": "name,organizationid"})
    org_row = (org.get("value") or [{}])[0]
    print(f"  Configured DYNAMICS_URL : {DYNAMICS_URL}")
    print(f"  Org name (from API)     : {org_row.get('name')}")
    print(f"  OrganizationId          : {org_row.get('organizationid')}")
    print(f"  Calling UserId          : {who.get('UserId')}")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("=" * 70)
print("2. Find Angie Nicolletta's user record + roles")
print("=" * 70)
angie = None
try:
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,accessmode",
        "$filter": f"internalemailaddress eq '{USER_EMAIL}'",
    })
    users = data.get("value", [])
    if not users:
        print(f"  ERROR: no systemuser found with email {USER_EMAIL}")
    else:
        angie = users[0]
        print(f"  {angie['fullname']}  ({angie['systemuserid']})")
        print(f"  disabled={angie.get('isdisabled')}  accessmode={angie.get('accessmode')}")
        roles = get(f"systemusers({angie['systemuserid']})/systemuserroles_association",
                     {"$select": "name,roleid"})
        role_names = [r["name"] for r in roles.get("value", [])]
        print(f"  Security roles ({len(role_names)}):")
        for n in sorted(role_names):
            print(f"    - {n}")
        docusign_roles = [n for n in role_names if "docusign" in n.lower()]
        if not docusign_roles:
            print("  ⚠ No role with 'DocuSign' in the name found on this user.")
        else:
            print(f"  DocuSign-related roles found: {docusign_roles}")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("=" * 70)
print("3. Is the DocuSign for Dynamics 365 solution installed, and what version")
print("=" * 70)
try:
    sol = get("solutions", {
        "$select": "friendlyname,uniquename,version,ismanaged",
        "$filter": "contains(uniquename,'docusign') or contains(friendlyname,'DocuSign')",
    })
    sols = sol.get("value", [])
    if not sols:
        print("  ⚠ No solution with 'DocuSign' in its name is installed in this org.")
    for s in sols:
        print(f"  {s['friendlyname']}  (uniquename={s['uniquename']}, "
              f"version={s['version']}, managed={s['ismanaged']})")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("=" * 70)
print("4. Discover DocuSign entities and look for a stored environment/org URL")
print("=" * 70)
try:
    ent_data = get("EntityDefinitions", {
        "$select": "LogicalName,DisplayName",
        "$filter": "IsCustomEntity eq true",
    })
    custom = ent_data.get("value", [])
    keywords = ["docusign", "dsfs", "dsign"]
    ds_entities = []
    for e in custom:
        name = e.get("LogicalName", "").lower()
        if any(k in name for k in keywords):
            ds_entities.append(e["LogicalName"])
    print(f"  DocuSign-related entities found ({len(ds_entities)}):")
    for name in sorted(ds_entities):
        print(f"    - {name}")

    # Look specifically for a configuration-type entity to inspect its
    # stored environment URL / org id vs. the real one.
    config_candidates = [n for n in ds_entities
                          if any(k in n for k in ["config", "account", "environment", "org"])]
    for entity in config_candidates:
        try:
            plural = entity if entity.endswith("s") else entity + "s"
            rows = get(plural, {"$top": 5})
            print(f"\n  Sample records from '{plural}':")
            for row in rows.get("value", []):
                interesting = {k: v for k, v in row.items()
                                if not k.startswith("@") and
                                any(x in k.lower() for x in
                                    ["url", "environment", "org", "instance", "account", "token", "auth"])}
                print(f"    {interesting}")
        except RuntimeError as e:
            print(f"    Could not read '{entity}': {e}")

    if not ds_entities:
        print("  No DocuSign custom entities visible — either the solution isn't")
        print("  installed, or this Application User lacks a security role that")
        print("  grants read privileges on DocuSign entities (check Step 2/3 above).")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("=" * 70)
print("SUMMARY / next steps")
print("=" * 70)
print("""
If Step 3 shows no DocuSign solution, or Step 4 shows no entities/records:
  -> DocuSign for Dynamics 365 was never (re)configured for THIS environment.
     Someone with System Admin needs to open the DocuSign for Dynamics 365
     app, go to Admin/Setup, and re-link the DocuSign account for this org
     (this is the standard fix after a sandbox copy, environment restore,
     or org URL/domain change).

If Step 4 shows a config/account record whose stored URL does not match
the "Configured DYNAMICS_URL" from Step 1:
  -> That's the exact cause of "Failed to retrieve Docusign URL for this
     environment": the connector is still pointed at a stale environment.
     Update/re-save that record (or re-run the DocuSign admin setup wizard)
     so it points at the current org URL.

If Step 2 shows Angie has no DocuSign-related security role while other
users who don't get this error do:
  -> Compare her role assignments to a working user's and add the missing
     DocuSign role (Settings > Security > Users > Manage Roles).
""")
