"""
Fix Dillon Fletcher's approval routing so lead submissions route to Tom Wenzler.

The lead approval flow routes to the submitting user's manager.
This script sets Dillon Fletcher's manager to Tom Wenzler.

Usage:
    python fix_dillon_approval_routing.py --dry-run   # preview
    python fix_dillon_approval_routing.py             # apply
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
dillon_matches = find_user("Dillon Fletcher")
tom_matches    = find_user("Tom Wenzler")

if not dillon_matches:
    print("ERROR: Dillon Fletcher not found"); exit(1)
if not tom_matches:
    print("ERROR: Tom Wenzler not found"); exit(1)

dillon = dillon_matches[0]
tom    = tom_matches[0]

print(f"  Dillon : {dillon['fullname']} — {dillon['systemuserid']}")
print(f"  Tom    : {tom['fullname']} — {tom['systemuserid']}")
print()

# ── Get current manager ───────────────────────────────────────────────────────
print("Checking Dillon's current manager...")
dillon_mgr = get_manager(dillon["systemuserid"])

print(f"  Current manager : {dillon_mgr['fullname'] if dillon_mgr else 'None'}")
print(f"  Target manager  : {tom['fullname']}")
print()

if dillon_mgr and dillon_mgr["systemuserid"] == tom["systemuserid"]:
    print("Dillon's manager is already Tom Wenzler — no change needed.")
    exit(0)

print(f"Change: Dillon's manager  {dillon_mgr['fullname'] if dillon_mgr else 'None'}")
print(f"     -> {tom['fullname']}")
print()

if DRY_RUN:
    print("Dry run — no changes made. Remove --dry-run to apply.")
    exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
print("Updating Dillon's manager...")
patch(
    f"systemusers({dillon['systemuserid']})",
    {"parentsystemuserid@odata.bind": f"/systemusers({tom['systemuserid']})"},
)
print(f"  Done. Dillon Fletcher's manager is now {tom['fullname']}.")
print()
print("Lead approval submissions from Dillon Fletcher will now route to")
print(f"{tom['fullname']} for approval.")
