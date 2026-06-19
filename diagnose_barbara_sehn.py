"""
Diagnose Barbara Sehn's login issue in Dynamics CRM.
Checks: account enabled/disabled, security roles, business unit, licenses.

Usage:
    python diagnose_barbara_sehn.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

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
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:400]}")
    return r.json()

def patch(path, body):
    r = _session.patch(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                       headers=get_headers({"If-Match": "*"}), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PATCH {path} failed {r.status_code}: {r.text[:400]}")
    return r

# ── 1. Find Barbara Sehn ──────────────────────────────────────────────────────
print("=" * 60)
print("1. User lookup (including disabled accounts)")
print("=" * 60)
data = get("systemusers", {
    "$select": "systemuserid,fullname,internalemailaddress,isdisabled,accessmode,islicensed,caltype",
    "$filter": "contains(fullname,'Barbara Sehn')",
})
users = data.get("value", [])
if not users:
    # Try without isdisabled filter in case name differs
    data2 = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,accessmode,islicensed,caltype",
        "$filter": "contains(fullname,'Barbara') and contains(fullname,'Sehn')",
    })
    users = data2.get("value", [])

if not users:
    print("ERROR: Barbara Sehn not found in systemusers at all.")
    exit(1)

user = users[0]
uid = user["systemuserid"]
access_labels = {0: "Read-Write", 1: "Administrative", 2: "Read", 3: "Support User", 4: "Non-interactive", 5: "Delegated Admin"}
cal_labels = {0: "No CAL", 1: "Professional", 2: "Administrative", 3: "Basic", 4: "DevicePro", 5: "DeviceBasic", 200: "Essential", 201: "Basic", 202: "Professional", 203: "Enterprise"}

print(f"  Name    : {user['fullname']}")
print(f"  Email   : {user.get('internalemailaddress')}")
print(f"  ID      : {uid}")
print(f"  Disabled: {user.get('isdisabled')}")
print(f"  Licensed: {user.get('islicensed')}")
print(f"  Access  : {access_labels.get(user.get('accessmode'), user.get('accessmode'))}")
print(f"  CAL Type: {cal_labels.get(user.get('caltype'), user.get('caltype'))}")
print()

# ── 2. Business unit ──────────────────────────────────────────────────────────
print("=" * 60)
print("2. Business unit")
print("=" * 60)
try:
    bu_data = get(f"systemusers({uid})", {
        "$select": "fullname",
        "$expand": "businessunitid($select=businessunitid,name,isdisabled)",
    })
    bu = bu_data.get("businessunitid")
    if bu:
        print(f"  BU Name    : {bu.get('name')}")
        print(f"  BU Disabled: {bu.get('isdisabled')}")
    else:
        print("  No business unit found")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 3. Security roles ─────────────────────────────────────────────────────────
print("=" * 60)
print("3. Security roles")
print("=" * 60)
try:
    roles = get(f"systemusers({uid})/systemuserroles_association",
                {"$select": "roleid,name"})
    role_list = roles.get("value", [])
    if role_list:
        for r in role_list:
            print(f"  {r['name']}")
    else:
        print("  WARNING: No security roles assigned — this will prevent login")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 4. Summary & fix suggestion ───────────────────────────────────────────────
print("=" * 60)
print("4. Summary")
print("=" * 60)
if user.get("isdisabled"):
    print("  ISSUE: Account is DISABLED — run fix_barbara_sehn.py to re-enable")
elif not user.get("islicensed"):
    print("  ISSUE: User is not licensed — assign a Dynamics license in M365 admin")
elif user.get("accessmode") != 0:
    print(f"  ISSUE: Access mode is '{access_labels.get(user.get('accessmode'))}' — should be Read-Write for normal login")
else:
    print("  Account looks enabled and licensed. Check Azure AD / M365 for MFA or password issues.")
