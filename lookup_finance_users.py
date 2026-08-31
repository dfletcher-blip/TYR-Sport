"""
Look up systemuserid + full name for the 3 Finance users being added to
the Convert to Contact button's authorized list, and check whether they
already have the "Create Account and Convert Lead to Contact" security
role assigned (the role set up earlier for Marina/Angela/Caroline/Dillon/Dan).

Read-only. Makes no changes.

Usage:
    python lookup_finance_users.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
ROLE_NAME = "Create Account and Convert Lead to Contact"

EMAILS = [
    "ALofmark@TYRsportoffice.onmicrosoft.com",
    "JSaidi@TYRsportoffice.onmicrosoft.com",
    "jbrandow@TYRsportoffice.onmicrosoft.com",
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

print("=" * 60)
print("Finance user lookup")
print("=" * 60)

role_id = None
try:
    role_data = get("roles", {
        "$select": "roleid,name",
        "$filter": f"name eq '{ROLE_NAME}'",
    })
    roles = role_data.get("value", [])
    if roles:
        role_id = roles[0]["roleid"]
        print(f"Role '{ROLE_NAME}' found: {role_id}")
    else:
        print(f"! Role '{ROLE_NAME}' not found by exact name.")
except RuntimeError as e:
    print(f"! Role lookup failed: {e}")
print()

for email in EMAILS:
    print("-" * 60)
    print(email)
    try:
        user_data = get("systemusers", {
            "$select": "systemuserid,fullname,domainname,internalemailaddress,isdisabled",
            "$filter": f"domainname eq '{email}' or internalemailaddress eq '{email}'",
        })
        users = user_data.get("value", [])
        if not users:
            print("  ! No matching systemuser found.")
            continue
        u = users[0]
        user_id = u.get("systemuserid")
        print(f"  systemuserid: {user_id}")
        print(f"  fullname: {u.get('fullname')}")
        print(f"  isdisabled: {u.get('isdisabled')}")

        if role_id:
            assigned = get(f"systemusers({user_id})/systemuserroles_association", {
                "$select": "roleid,name",
                "$filter": f"roleid eq {role_id}",
            })
            has_role = len(assigned.get("value", [])) > 0
            print(f"  already has '{ROLE_NAME}' role: {has_role}")
    except RuntimeError as e:
        print(f"  ! Lookup failed: {e}")
    print()

print("Done. This is read-only -- nothing was changed.")
