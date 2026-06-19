"""
Revert Conor Shelley's lead approval routing back to Larry Meltzer.

Usage:
    python fix_conor_approval_revert.py --dry-run
    python fix_conor_approval_revert.py
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

print("Looking up users...")
conor_matches = find_user("Conor Shelley")
larry_matches = find_user("Larry Meltzer")

if not conor_matches:
    print("ERROR: Conor Shelley not found"); exit(1)
if not larry_matches:
    print("ERROR: Larry Meltzer not found"); exit(1)

conor = conor_matches[0]
larry = larry_matches[0]

print(f"  Conor : {conor['fullname']} — {conor['systemuserid']}")
print(f"  Larry : {larry['fullname']} — {larry['systemuserid']}")
print()

current_mgr = get_manager(conor["systemuserid"])
print(f"  Current manager : {current_mgr['fullname'] if current_mgr else 'None'}")
print(f"  Target  manager : {larry['fullname']}")
print()

if current_mgr and current_mgr["systemuserid"] == larry["systemuserid"]:
    print("Conor's manager is already Larry Meltzer — no change needed.")
    exit(0)

print(f"Change: {current_mgr['fullname'] if current_mgr else 'None'} -> {larry['fullname']}")
print()

if DRY_RUN:
    print("Dry run — no changes made. Remove --dry-run to apply.")
    exit(0)

print("Updating Conor's manager...")
patch(
    f"systemusers({conor['systemuserid']})",
    {"parentsystemuserid@odata.bind": f"/systemusers({larry['systemuserid']})"},
)
print(f"  Done. Conor Shelley's manager is now {larry['fullname']}.")
print("Lead approval submissions from Conor Shelley will now route to Larry Meltzer.")
