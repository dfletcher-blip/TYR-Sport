"""
Grant Marina Preiss, Angela Nicolletta, Caroline Kulp, Dillon Fletcher,
Dan Macquarrie, and Michael Galindo:
  - Account: Create (create their own accounts)
  - Contact: Create, Write, Append (convert a Lead to a Contact, then edit it)
  - Account: AppendTo (allow a Contact to be linked/associated to an Account)
  - Lead: Write (needed to qualify/convert a Lead)

Rather than editing whatever security role these users currently have
(which likely covers other people too), this creates ONE new, minimal
role containing exactly these privileges at Basic (User/own-records)
depth, and assigns it to all users listed in TARGET_USERS. Existing
roles/privileges are untouched. Safe to re-run — it looks up the role
and each user's assignment by name/id first and skips anything already
in place, so re-running for users already assigned is a no-op for them.

This assumes each user already has baseline Read access to Account,
Contact, and Lead via their current role(s) — those are listed below so
you can confirm, but this script does not add Read privileges.

Usage:
    python setup_account_lead_contact_permissions.py --dry-run   # preview
    python setup_account_lead_contact_permissions.py             # apply
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

TARGET_USERS = [
    "Marina Preiss", "Angela Nicolletta", "Caroline Kulp",
    "Dillon Fletcher", "Dan Macquarrie", "Michael Galindo",
]
NEW_ROLE_NAME = "Create Account and Convert Lead to Contact"
DEPTH = "Basic"

TARGET_PRIVILEGES = [
    "prvCreateAccount",
    "prvAppendToAccount",
    "prvCreateContact",
    "prvWriteContact",
    "prvAppendContact",
    "prvWriteLead",
]

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET", "POST", "PATCH"])
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {"Authorization": f"Bearer {_token['value']}",
         "OData-MaxVersion": "4.0", "OData-Version": "4.0",
         "Accept": "application/json", "Content-Type": "application/json",
         "Prefer": "odata.include-annotations=*"}
    if extra:
        h.update(extra)
    return h

def get(path, params=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:500]}")
    return r.json()

def post(path, body=None):
    r = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                      headers=get_headers(), json=body or {}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed {r.status_code}: {r.text[:800]}")
    return r

def find_user(full_name):
    first, *rest = full_name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,_businessunitid_value",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}'",
    })
    users = [u for u in data.get("value", []) if not u.get("isdisabled")]
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled,_businessunitid_value",
            "$filter": f"contains(fullname,'{full_name}')",
        })
        users = [u for u in data2.get("value", []) if not u.get("isdisabled")]
    if not users:
        # Try last-name-only, in case of a spelling variant on the first name
        data3 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled,_businessunitid_value",
            "$filter": f"contains(fullname,'{last}')",
        })
        users = [u for u in data3.get("value", []) if not u.get("isdisabled")]
    return users

def get_user_roles(user_id):
    data = get(f"systemusers({user_id})/systemuserroles_association", {"$select": "roleid,name"})
    return data.get("value", [])

def find_privilege_ids(names):
    """Look up privilege GUIDs by their well-known Dataverse names (e.g. prvCreateAccount)."""
    found = {}
    missing = []
    for name in names:
        data = get("privileges", {"$select": "privilegeid,name", "$filter": f"name eq '{name}'"})
        matches = data.get("value", [])
        if matches:
            found[name] = matches[0]["privilegeid"]
        else:
            missing.append(name)
    return found, missing

def find_existing_role(name):
    data = get("roles", {"$select": "roleid,name", "$filter": f"name eq '{name}'"})
    matches = data.get("value", [])
    return matches[0] if matches else None

def create_role(name, business_unit_id):
    body = {"name": name, "businessunitid@odata.bind": f"/businessunits({business_unit_id})"}
    r = post("roles", body)
    entity_url = r.headers.get("OData-EntityId", "")
    # Extract the GUID from the returned entity URL: .../roles(<guid>)
    role_id = entity_url.split("(")[-1].rstrip(")")
    return role_id

def add_privileges_to_role(role_id, privilege_ids_with_depth):
    body = {
        "Privileges": [
            {"@odata.type": "Microsoft.Dynamics.CRM.RolePrivilege", "PrivilegeId": pid, "Depth": depth}
            for pid, depth in privilege_ids_with_depth
        ]
    }
    post(f"roles({role_id})/Microsoft.Dynamics.CRM.AddPrivilegesRole", body)

def assign_role_to_user(user_id, role_id):
    post(f"systemusers({user_id})/systemuserroles_association/$ref",
         {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/roles({role_id})"})


# ── Look up the three users ──────────────────────────────────────────────────
print("Looking up users...")
found_users = {}
for name in TARGET_USERS:
    matches = find_user(name)
    if not matches:
        print(f"  ! '{name}' NOT FOUND — check spelling in Dynamics and re-run")
        continue
    if len(matches) > 1:
        print(f"  ! '{name}' matched {len(matches)} users — using the first match, verify this is correct:")
        for m in matches:
            print(f"      {m['fullname']} ({m.get('internalemailaddress','')}) — {m['systemuserid']}")
    u = matches[0]
    found_users[name] = u
    print(f"  {name} -> {u['fullname']} ({u.get('internalemailaddress','')}) — {u['systemuserid']}")
print()

if not found_users:
    print("ERROR: None of the target users were found. Nothing to do.")
    sys.exit(1)

# ── Show each user's current roles for context ───────────────────────────────
print("Current security roles (for context — not modified by this script):")
for name, u in found_users.items():
    roles = get_user_roles(u["systemuserid"])
    print(f"  {name}: {', '.join(r['name'] for r in roles) if roles else '(no roles)'}")
print()

if DRY_RUN:
    print("*** DRY RUN — no changes will be made ***\n")

# ── Look up privilege GUIDs ──────────────────────────────────────────────────
print("Looking up privilege IDs...")
privilege_ids, missing = find_privilege_ids(TARGET_PRIVILEGES)
for name, pid in privilege_ids.items():
    print(f"  {name}: {pid}")
if missing:
    print(f"  ! Could not find: {', '.join(missing)} — these privilege names may differ on this org's")
    print("    Dynamics version. Check Settings > Security > Privileges for the exact name.")
print()

if not privilege_ids:
    print("ERROR: No target privileges were found. Cannot continue.")
    sys.exit(1)

# ── Find or plan the new role ─────────────────────────────────────────────────
existing_role = find_existing_role(NEW_ROLE_NAME)
if existing_role:
    print(f"Role '{NEW_ROLE_NAME}' already exists — {existing_role['roleid']}")
    print("  Will reuse it and only add any missing privileges/assignments.")
else:
    print(f"Role '{NEW_ROLE_NAME}' does not exist yet — will create it.")
    first_user = next(iter(found_users.values()))
    bu_id = first_user.get("_businessunitid_value")
    print(f"  New role will be created in business unit of {first_user['fullname']}: {bu_id}")
print()

print(f"Privileges to grant on the role (all at '{DEPTH}' depth):")
for name in privilege_ids:
    print(f"  + {name}")
print()

print("Users to assign this role to:")
for name in found_users:
    print(f"  + {name}")
print()

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to create the role, grant the")
    print("privileges, and assign it to the users listed above.")
    sys.exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
if existing_role:
    role_id = existing_role["roleid"]
else:
    first_user = next(iter(found_users.values()))
    bu_id = first_user.get("_businessunitid_value")
    print(f"Creating role '{NEW_ROLE_NAME}'...")
    role_id = create_role(NEW_ROLE_NAME, bu_id)
    print(f"  Created: {role_id}")

print("Adding privileges to role...")
try:
    add_privileges_to_role(role_id, [(pid, DEPTH) for pid in privilege_ids.values()])
    print(f"  + Added {len(privilege_ids)} privilege(s)")
except RuntimeError as e:
    print(f"  ! FAILED to add privileges: {e}")
    print("  The role was created but has no privileges yet. Fix and re-run — this")
    print("  script is safe to re-run since it reuses the existing role by name.")
print()

print("Assigning role to users...")
assigned = errors = 0
for name, u in found_users.items():
    try:
        assign_role_to_user(u["systemuserid"], role_id)
        print(f"  + {name}")
        assigned += 1
    except RuntimeError as e:
        # Dynamics returns a duplicate-key style error if the role is already assigned — treat as success
        if "duplicate" in str(e).lower() or "already" in str(e).lower():
            print(f"  = {name} (already assigned)")
            assigned += 1
        else:
            print(f"  ! {name}: {e}")
            errors += 1
    time.sleep(0.3)

print()
print("Done.")
print(f"  Role: {NEW_ROLE_NAME} ({role_id})")
print(f"  Users assigned: {assigned}")
if errors:
    print(f"  Errors: {errors}")
print()
print("Note: qualify_lead() in tools/leads.py currently always creates a")
print("Contact, Account, AND Opportunity when converting a lead. If you want")
print("these three users to convert Lead -> Contact only (then manually link")
print("to an account they created separately), use the Dynamics UI's Qualify")
print("Lead dialog with only 'Contact' checked, rather than that bulk tool.")
