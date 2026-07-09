"""
Add Miguel de las Casas to the same STR approval flow as Ross Davenport.

The approval flow routes to the submitting user's manager.
This script finds Ross Davenport's manager and sets the same manager
on Miguel de las Casas.

Usage:
    python fix_miguel_str_approval.py --dry-run
    python fix_miguel_str_approval.py
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

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
         "Accept": "application/json", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

def get(path, params=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:400]}")
    return r.json()

def patch(path, body):
    r = _session.patch(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                       headers=get_headers({"If-Match": "*"}), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PATCH {path} failed {r.status_code}: {r.text[:400]}")
    return r

def find_user(name):
    first, *rest = name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}' and isdisabled eq false",
    })
    users = data.get("value", [])
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress",
            "$filter": f"contains(fullname,'{name}') and isdisabled eq false",
        })
        users = data2.get("value", [])
    return users

def get_manager(user_id):
    data = get(f"systemusers({user_id})",
               {"$select": "fullname,_parentsystemuserid_value",
                "$expand": "parentsystemuserid($select=systemuserid,fullname)"})
    return data.get("parentsystemuserid")

# ── Look up users ─────────────────────────────────────────────────────────────
print("Looking up users...")
ross_matches   = find_user("Ross Davenport")
miguel_matches = find_user("Miguel de las Casas")

if not ross_matches:
    print("ERROR: Ross Davenport not found"); exit(1)
if not miguel_matches:
    print("ERROR: Miguel de las Casas not found")
    similar = find_user("Miguel")
    if similar:
        print("  Did you mean one of these?")
        for u in similar:
            print(f"    {u['fullname']} — {u['internalemailaddress']}")
    exit(1)

ross  = ross_matches[0]
miguel = miguel_matches[0]

print(f"  Ross   : {ross['fullname']} — {ross['systemuserid']}")
print(f"  Miguel : {miguel['fullname']} — {miguel['systemuserid']}")
print()

# ── Get Ross's manager (the STR approver) ────────────────────────────────────
print("Checking managers...")
ross_mgr   = get_manager(ross["systemuserid"])
miguel_mgr = get_manager(miguel["systemuserid"])

if not ross_mgr:
    print("ERROR: Ross Davenport has no manager set — cannot determine STR approver.")
    exit(1)

print(f"  Ross's manager (STR approver) : {ross_mgr['fullname']}")
print(f"  Miguel's current manager      : {miguel_mgr['fullname'] if miguel_mgr else 'None'}")
print()

if miguel_mgr and miguel_mgr["systemuserid"] == ross_mgr["systemuserid"]:
    print("Miguel's manager already matches Ross's — no change needed.")
    exit(0)

print(f"Change: Miguel's manager  {miguel_mgr['fullname'] if miguel_mgr else 'None'}")
print(f"     -> {ross_mgr['fullname']}")
print()

if DRY_RUN:
    print("Dry run — no changes made. Remove --dry-run to apply.")
    exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
print("Updating Miguel's manager...")
patch(
    f"systemusers({miguel['systemuserid']})",
    {"parentsystemuserid@odata.bind": f"/systemusers({ross_mgr['systemuserid']})"},
)
print(f"  Done. Miguel de las Casas's manager is now {ross_mgr['fullname']}.")
print(f"STR approval submissions from Miguel will now route to {ross_mgr['fullname']}.")
