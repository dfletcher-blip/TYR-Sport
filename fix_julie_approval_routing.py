"""
Fix Julie Meredith's approval routing to match Angie Nicolletta.

The lead approval flow routes to the submitting user's manager.
Angie's manager = Michael Galindo.
Julie's manager = Larry Meltzer (wrong).

This script updates Julie's manager to Michael Galindo so her
lead submissions route to the same approver as Angie's.

Usage:
    python fix_julie_approval_routing.py --dry-run   # preview
    python fix_julie_approval_routing.py             # apply
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
julie_matches  = find_user("Julie Meredith")
angie_matches  = find_user("Angie Nicolletta")

if not julie_matches:
    print("ERROR: Julie Meredith not found"); exit(1)
if not angie_matches:
    print("ERROR: Angie Nicolletta not found"); exit(1)

julie = julie_matches[0]
angie = angie_matches[0]

print(f"  Julie  : {julie['fullname']} — {julie['systemuserid']}")
print(f"  Angie  : {angie['fullname']} — {angie['systemuserid']}")
print()

# ── Get current managers ──────────────────────────────────────────────────────
print("Checking managers...")
angie_mgr = get_manager(angie["systemuserid"])
julie_mgr  = get_manager(julie["systemuserid"])

if not angie_mgr:
    print("ERROR: Angie has no manager set — cannot determine target approver.")
    exit(1)

print(f"  Angie's manager (target) : {angie_mgr['fullname']} — {angie_mgr['systemuserid']}")
print(f"  Julie's manager (current): {julie_mgr['fullname'] if julie_mgr else 'None'}")
print()

if julie_mgr and julie_mgr["systemuserid"] == angie_mgr["systemuserid"]:
    print("Julie's manager already matches Angie's — no change needed.")
    exit(0)

print(f"Change: Julie's manager  {julie_mgr['fullname'] if julie_mgr else 'None'}")
print(f"     -> {angie_mgr['fullname']}")
print()

if DRY_RUN:
    print("Dry run — no changes made. Remove --dry-run to apply.")
    exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
print("Updating Julie's manager...")
patch(
    f"systemusers({julie['systemuserid']})",
    {"parentsystemuserid@odata.bind": f"/systemusers({angie_mgr['systemuserid']})"},
)
print(f"  Done. Julie Meredith's manager is now {angie_mgr['fullname']}.")
print()
print("Lead approval submissions from Julie will now route to the same")
print(f"approver as Angie: {angie_mgr['fullname']}.")
