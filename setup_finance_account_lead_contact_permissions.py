"""
Assign the existing "Create Account and Convert Lead to Contact" security
role (created earlier for Marina Preiss, Angela Nicolletta, Caroline Kulp,
Dillon Fletcher, Dan Macquarrie) to the 3 Finance users who need to use
the Convert to Contact button instead of native Qualify Lead, which is
blocked by a locked managed field-mapping bug we can't fix directly.

Does NOT create a new role -- reuses the role found by
lookup_finance_users.py. Only assigns it to users who don't already have it.

Usage:
    python setup_finance_account_lead_contact_permissions.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
ROLE_NAME = "Create Account and Convert Lead to Contact"

TARGET_USERS = [
    ("Andrea Lofmark", "ALofmark@TYRsportoffice.onmicrosoft.com"),
    ("Jaaber Saidi", "JSaidi@TYRsportoffice.onmicrosoft.com"),
    ("Jennifer Brandow", "jbrandow@TYRsportoffice.onmicrosoft.com"),
]

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET"])
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

def post(path, body):
    r = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                      headers=get_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed {r.status_code}: {r.text[:500]}")
    return r

role_data = get("roles", {
    "$select": "roleid,name",
    "$filter": f"name eq '{ROLE_NAME}'",
})
roles = role_data.get("value", [])
if not roles:
    print(f"ERROR: Role '{ROLE_NAME}' not found. Nothing to assign.")
    raise SystemExit(1)
role_id = roles[0]["roleid"]
print(f"Using role '{ROLE_NAME}' ({role_id})")
print()

for fullname_hint, email in TARGET_USERS:
    print("-" * 60)
    print(f"{fullname_hint}  ({email})")
    try:
        user_data = get("systemusers", {
            "$select": "systemuserid,fullname",
            "$filter": f"domainname eq '{email}' or internalemailaddress eq '{email}'",
        })
        users = user_data.get("value", [])
        if not users:
            print("  ! No matching systemuser found. Skipping.")
            continue
        user_id = users[0]["systemuserid"]
        print(f"  systemuserid: {user_id}  ({users[0].get('fullname')})")

        assigned = get(f"systemusers({user_id})/systemuserroles_association", {
            "$select": "roleid",
            "$filter": f"roleid eq {role_id}",
        })
        if assigned.get("value"):
            print("  Already has the role. Skipping.")
            continue

        post(f"systemusers({user_id})/systemuserroles_association/$ref", {
            "@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/roles({role_id})"
        })
        print("  Role assigned.")
    except RuntimeError as e:
        print(f"  ! Failed: {e}")
    print()

print("Done.")
