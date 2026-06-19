"""
Fix Conor Shelley's lead approval routing to route to Thomas Wenzler.

The lead approval flow routes to the submitting user's manager.
This script updates Conor Shelley's manager to Thomas Wenzler so his
lead submissions route to Thomas for approval.

Usage:
    python fix_conor_approval_routing.py --dry-run   # preview
    python fix_conor_approval_routing.py             # apply
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
conor_matches   = find_user("Conor Shelley")
thomas_matches  = find_user("Thomas Wenzler")

if not conor_matches:
    print("ERROR: Conor Shelley not found"); exit(1)
if not thomas_matches:
    print("ERROR: Thomas Wenzler not found"); exit(1)

conor  = conor_matches[0]
thomas = thomas_matches[0]

print(f"  Conor  : {conor['fullname']} — {conor['systemuserid']}")
print(f"  Thomas : {thomas['fullname']} — {thomas['systemuserid']}")
print()

# ── Get current manager ───────────────────────────────────────────────────────
print("Checking Conor's current manager...")
conor_mgr = get_manager(conor["systemuserid"])
print(f"  Current manager : {conor_mgr['fullname'] if conor_mgr else 'None'}")
print(f"  Target  manager : {thomas['fullname']}")
print()

if conor_mgr and conor_mgr["systemuserid"] == thomas["systemuserid"]:
    print("Conor's manager is already Thomas Wenzler — no change needed.")
    exit(0)

print(f"Change: Conor's manager  {conor_mgr['fullname'] if conor_mgr else 'None'}")
print(f"     -> {thomas['fullname']}")
print()

if DRY_RUN:
    print("Dry run — no changes made. Remove --dry-run to apply.")
    exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
print("Updating Conor's manager...")
patch(
    f"systemusers({conor['systemuserid']})",
    {"parentsystemuserid@odata.bind": f"/systemusers({thomas['systemuserid']})"},
)
print(f"  Done. Conor Shelley's manager is now {thomas['fullname']}.")
print()
print("Lead approval submissions from Conor Shelley will now route to")
print(f"Thomas Wenzler for approval.")
