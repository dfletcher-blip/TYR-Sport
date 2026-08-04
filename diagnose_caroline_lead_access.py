"""
Diagnose: Caroline Kulp (systemuserid 9b982045-3308-f111-8406-6045bd0784c0)
gets "Access Is Denied ... does not have CreateAccess right(s) ... entity Lead"
when saving a new Lead.

The error body already tells us RoleAccessRights=None for CreateAccess on
Lead — this script finds out WHY: does she have zero roles with Create on
Lead, or does she have the privilege but at a business-unit depth that
doesn't cover where the record would be created?

Run: python diagnose_caroline_lead_access.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CAROLINE_ID = "9b982045-3308-f111-8406-6045bd0784c0"

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

DEPTH = {0: "None", 1: "User", 2: "Business Unit", 3: "Parent: Child BUs", 4: "Organization"}

print("=" * 70)
print("1. Caroline Kulp's user record")
print("=" * 70)
user = get(f"systemusers({CAROLINE_ID})", {
    "$select": "fullname,internalemailaddress,isdisabled,accessmode",
    "$expand": "businessunitid($select=name)",
})
print(f"  {user.get('fullname')}  <{user.get('internalemailaddress')}>")
print(f"  disabled={user.get('isdisabled')}  accessmode={user.get('accessmode')}")
bu = user.get("businessunitid") or {}
print(f"  Business unit: {bu.get('name')}")
print()

print("=" * 70)
print("2. Her security roles")
print("=" * 70)
roles = get(f"systemusers({CAROLINE_ID})/systemuserroles_association",
            {"$select": "name,roleid"})
role_list = roles.get("value", [])
caroline_role_names_preview = {r["name"] for r in role_list}
print(f"  Roles ({len(role_list)}):")
for r in role_list:
    print(f"    - {r['name']}  ({r['roleid']})")
print()

print("=" * 70)
print("3. Lead 'Create' privilege depth granted by each of her roles")
print("=" * 70)
priv_lookup = get("privileges", {"$select": "privilegeid,name", "$filter": "name eq 'prvCreateLead'"})
prv_rows = priv_lookup.get("value", [])
if not prv_rows:
    print("  Could not find the 'prvCreateLead' privilege definition in this org.")
else:
    prv_create_lead_id = prv_rows[0]["privilegeid"]
    print(f"  prvCreateLead privilege id: {prv_create_lead_id}")
    for r in role_list:
        try:
            resp = requests.get(
                f"{DYNAMICS_URL}/api/data/v9.2/roles({r['roleid']})/Microsoft.Dynamics.CRM.RetrieveRolePrivilegesRole()",
                headers=get_headers(), timeout=30)
            if not resp.ok:
                print(f"  Role '{r['name']}': could not retrieve privileges ({resp.status_code})")
                continue
            role_privs = resp.json().get("RolePrivileges", [])
            match = [p for p in role_privs if p.get("PrivilegeId", "").lower() == prv_create_lead_id.lower()]
            if match:
                depth = match[0].get("Depth")
                print(f"  Role '{r['name']}': Create-Lead depth = {DEPTH.get(depth, depth)}")
            else:
                print(f"  Role '{r['name']}': NO Create-Lead privilege at all.")
        except Exception as e:
            print(f"  Role '{r['name']}': error checking privilege — {e}")
print()

print("=" * 70)
print("4. Compare against a NON-admin user who CAN create Leads")
print("=" * 70)
sample_leads = get("leads", {"$select": "leadid,_ownerid_value,createdon", "$top": 50, "$orderby": "createdon desc"})
owner_ids = []
for l in sample_leads.get("value", []):
    oid = l.get("_ownerid_value")
    if oid and oid != CAROLINE_ID and oid not in owner_ids:
        owner_ids.append(oid)
compared = 0
for oid in owner_ids:
    owner = get(f"systemusers({oid})", {"$select": "fullname"})
    oroles = get(f"systemusers({oid})/systemuserroles_association", {"$select": "name"})
    onames = {x["name"] for x in oroles.get("value", [])}
    if "System Administrator" in onames:
        continue  # admins bypass privilege checks — not a useful comparison
    print(f"  {owner.get('fullname')} roles: {sorted(onames)}")
    diff = onames - caroline_role_names_preview
    if diff:
        print(f"    -> roles this user has that Caroline does NOT: {sorted(diff)}")
    compared += 1
    if compared >= 3:
        break
print()

print("=" * 70)
print("SUMMARY")
print("=" * 70)
caroline_role_names = {r["name"] for r in role_list}
print(f"  Caroline's roles: {sorted(caroline_role_names)}")
print("""
FIX: compare Caroline's role list above to a working Lead-creating user's
role list (Step 4). Whichever role THEY have that SHE doesn't is almost
certainly the one carrying Create privilege on Lead (commonly something
like "TYR - Sales Representative" or similar — the same family of role
that showed up for Angie Nicolletta in the earlier DocuSign diagnostic).
Assign that role to Caroline via Settings > Security > Users > Manage Roles.
""")
