"""
Grant Michael Galindo approver access on top of the Account/Contact/Lead
permissions already granted by setup_account_lead_contact_permissions.py:
  - Special Terms (tyr_specialterms): Write, at Deep depth
  - Lead: Write, at Deep depth (upgrades his existing Basic-depth Write
    from the shared role, since a user's effective depth for a privilege
    is the highest depth across all their assigned roles)

"Deep" depth = his own Business Unit plus any subordinate Business
Units — i.e. his direct/indirect reports' records, not just his own or
the whole org. This is a SEPARATE role, assigned only to Michael, since
approver access shouldn't be granted to the other five users who got
the base Account/Contact/Lead role.

Special Terms approval in this org is a manual process (no automated
workflow exists — see setup_larry_finance_approval_routing.py's
findings), so "being an approver" here means being able to write to the
tyr_approvalstatus field on a submitted STR record, which requires
Write access to records he doesn't own himself.

Privilege IDs are looked up via the EntityDefinitions(...)/Privileges
metadata endpoint rather than guessed by name, since custom-entity
privilege names (like on tyr_specialterms) don't reliably follow the
same naming convention as standard entities.

Usage:
    python setup_michael_approver_permissions.py --dry-run   # preview
    python setup_michael_approver_permissions.py             # apply
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

TARGET_USER = "Michael Galindo"
NEW_ROLE_NAME = "Special Terms and Lead Approver"
PREFERRED_DEPTH = "Deep"
FALLBACK_DEPTH = "Local"

TARGET_ENTITIES = ["tyr_specialterms", "lead"]  # Write privilege on each
ACCESS_RIGHT = "Write"

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
        data3 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled,_businessunitid_value",
            "$filter": f"contains(fullname,'{last}')",
        })
        users = [u for u in data3.get("value", []) if not u.get("isdisabled")]
    return users

def get_user_roles(user_id):
    data = get(f"systemusers({user_id})/systemuserroles_association", {"$select": "roleid,name"})
    return data.get("value", [])

def find_entity_privilege(entity_logical_name, access_right):
    """
    Look up the privilege for a given access right (Write, Create, etc.)
    on an entity via entity metadata, rather than guessing the privilege
    name string. Returns (privilege_id, can_be_deep, can_be_local) or
    (None, None, None) if not found.
    """
    data = get(f"EntityDefinitions(LogicalName='{entity_logical_name}')/Privileges", {
        "$select": "privilegeid,name,privilegetype,canbedeep,canbelocal,canbeglobal,canbebasic",
    })
    for p in data.get("value", []):
        if p.get("privilegetype") == access_right:
            return p.get("privilegeid"), p.get("canbedeep"), p.get("canbelocal")
    return None, None, None

def find_existing_role(name):
    data = get("roles", {"$select": "roleid,name", "$filter": f"name eq '{name}'"})
    matches = data.get("value", [])
    return matches[0] if matches else None

def create_role(name, business_unit_id):
    body = {"name": name, "businessunitid@odata.bind": f"/businessunits({business_unit_id})"}
    r = post("roles", body)
    entity_url = r.headers.get("OData-EntityId", "")
    return entity_url.split("(")[-1].rstrip(")")

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


# ── Look up Michael ──────────────────────────────────────────────────────────
print("Looking up user...")
matches = find_user(TARGET_USER)
if not matches:
    print(f"ERROR: '{TARGET_USER}' not found")
    sys.exit(1)
if len(matches) > 1:
    print(f"  ! Matched {len(matches)} users — using the first, verify this is correct:")
    for m in matches:
        print(f"      {m['fullname']} ({m.get('internalemailaddress','')}) — {m['systemuserid']}")
michael = matches[0]
michael_id = michael["systemuserid"]
bu_id = michael.get("_businessunitid_value")
print(f"  {michael['fullname']} ({michael.get('internalemailaddress','')}) — {michael_id}")
print(f"  Business unit: {bu_id}")
print()

print("Current security roles (for context — not modified by this script):")
roles = get_user_roles(michael_id)
print(f"  {', '.join(r['name'] for r in roles) if roles else '(no roles)'}")
print()

if DRY_RUN:
    print("*** DRY RUN — no changes will be made ***\n")

# ── Look up privilege IDs via entity metadata ────────────────────────────────
print(f"Looking up '{ACCESS_RIGHT}' privilege for: {', '.join(TARGET_ENTITIES)}...")
privileges_to_grant = []  # list of (entity, privilege_id, depth)
for entity in TARGET_ENTITIES:
    try:
        pid, can_deep, can_local = find_entity_privilege(entity, ACCESS_RIGHT)
    except RuntimeError as e:
        print(f"  ! {entity}: metadata lookup failed: {e}")
        continue
    if not pid:
        print(f"  ! {entity}: no '{ACCESS_RIGHT}' privilege found")
        continue
    depth = PREFERRED_DEPTH if can_deep else (FALLBACK_DEPTH if can_local else "Basic")
    if depth != PREFERRED_DEPTH:
        print(f"  ! {entity}: '{PREFERRED_DEPTH}' depth not supported on this privilege — using '{depth}' instead")
    print(f"  {entity}: {pid} (depth: {depth})")
    privileges_to_grant.append((entity, pid, depth))
print()

if not privileges_to_grant:
    print("ERROR: No privileges resolved. Cannot continue.")
    sys.exit(1)

# ── Find or plan the new role ─────────────────────────────────────────────────
existing_role = find_existing_role(NEW_ROLE_NAME)
if existing_role:
    print(f"Role '{NEW_ROLE_NAME}' already exists — {existing_role['roleid']}")
else:
    print(f"Role '{NEW_ROLE_NAME}' does not exist yet — will create it in Michael's business unit.")
print()

print("Privileges to grant on the role:")
for entity, pid, depth in privileges_to_grant:
    print(f"  + Write on {entity} ({depth})")
print()
print(f"User to assign this role to: {TARGET_USER}")
print()

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to create the role, grant the")
    print("privileges, and assign it to Michael.")
    sys.exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
if existing_role:
    role_id = existing_role["roleid"]
else:
    print(f"Creating role '{NEW_ROLE_NAME}'...")
    role_id = create_role(NEW_ROLE_NAME, bu_id)
    print(f"  Created: {role_id}")

print("Adding privileges to role...")
try:
    add_privileges_to_role(role_id, [(pid, depth) for _, pid, depth in privileges_to_grant])
    print(f"  + Added {len(privileges_to_grant)} privilege(s)")
except RuntimeError as e:
    print(f"  ! FAILED to add privileges: {e}")
    print("  The role was created but may have no privileges yet. Fix and re-run —")
    print("  this script reuses the existing role by name.")
print()

print("Assigning role to Michael...")
try:
    assign_role_to_user(michael_id, role_id)
    print(f"  + {TARGET_USER}")
except RuntimeError as e:
    if "duplicate" in str(e).lower() or "already" in str(e).lower():
        print(f"  = {TARGET_USER} (already assigned)")
    else:
        print(f"  ! {TARGET_USER}: {e}")

print()
print("Done.")
print(f"  Role: {NEW_ROLE_NAME} ({role_id})")
