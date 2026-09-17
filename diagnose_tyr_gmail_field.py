"""
Confirms the suspected root cause: 'Special Terms : Submit for
Approval' sends via the Gmail connector but pulls its recipient from
Get_a_Manager_row_by_ID's 'internalemailaddress' (the Microsoft 365
login address) -- but the OTHER Special Terms flow (Assign STR to
Finance Credit Team) uses a separate custom field 'tyr_gmail' for its
Gmail-connector sends, which is presumably the actual correct/deliverable
address for Gmail-based sends.

Checks Tom Wenzler's systemuser record for a tyr_gmail field (or any
field with 'gmail' in its logical name), and prints its value so we can
confirm it's populated with his real tyr.com/Gmail-hosted address
before changing the flow to use it.

Read-only. Makes no changes.

Usage:
    python diagnose_tyr_gmail_field.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
TOM_ID = "d66af34f-3308-f111-8406-000d3a328ec4"

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

# ── 1. Find all gmail-related fields on systemuser ───────────────────────────
print("=" * 70)
print("1. systemuser fields with 'gmail' in the name")
print("=" * 70)
attr_data = get("EntityDefinitions(LogicalName='systemuser')/Attributes", {
    "$select": "LogicalName,DisplayName,AttributeType",
})
gmail_fields = []
for a in attr_data.get("value", []):
    logical = a.get("LogicalName", "") or ""
    display = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
    if "gmail" in logical.lower() or "gmail" in display.lower():
        gmail_fields.append(logical)
        print(f"  {logical}  (\"{display}\")  type={a.get('AttributeType')}")
if not gmail_fields:
    print("  ! No gmail-named field found on systemuser.")
print()

# ── 2. Tom Wenzler's value for that field ────────────────────────────────────
print("=" * 70)
print("2. Tom Wenzler's values")
print("=" * 70)
select_fields = "systemuserid,fullname,internalemailaddress,domainname"
if gmail_fields:
    select_fields += "," + ",".join(gmail_fields)
user = get(f"systemusers({TOM_ID})", {"$select": select_fields})
for k, v in user.items():
    if not k.startswith("@") and "OData" not in k:
        print(f"  {k}: {v}")

print()
print("Done. This is read-only -- nothing was changed.")
