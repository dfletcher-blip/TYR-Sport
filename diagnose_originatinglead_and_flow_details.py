"""
Follow-up to diagnose_tyrtype_businesstype_mismatch.py.

1. Checks whether Account.originatingleadid is writable on create --
   if our Convert to Contact script binds the new Account to the source
   Lead via this field, the existing 'Account : Update TYR and Business
   Type on Creation' flow should handle copying TYR Type/Business Type
   correctly for us, the same way it does for native Qualify Lead.

2. Reads the ALREADY-SAVED account_tyrtype_flow_raw.json (from the
   previous diagnostic run, in the current directory) and prints the
   full Initialize_variable / Initialize_Business_Type_Variable action
   expressions, so we can see exactly what values/mapping that flow
   actually uses instead of guessing.

Read-only against Dataverse. Makes no changes.

Usage:
    python diagnose_originatinglead_and_flow_details.py
"""
import os, json, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

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

def truncate(val, n=1500):
    s = json.dumps(val, indent=2) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

# ── 1. Is originatingleadid writable on create? ──────────────────────────────
print("=" * 60)
print("1. Account.originatingleadid writability")
print("=" * 60)
try:
    data = get("EntityDefinitions(LogicalName='account')/Attributes")
    matches = [a for a in data.get("value", []) if a.get("LogicalName") == "originatingleadid"]
    if not matches:
        print("  ! originatingleadid attribute not found on account.")
    else:
        a = matches[0]
        print(f"  Type: {a.get('AttributeType')}")
        print(f"  IsValidForCreate: {a.get('IsValidForCreate')}")
        print(f"  IsValidForUpdate: {a.get('IsValidForUpdate')}")
except RuntimeError as e:
    print(f"  ! Lookup failed: {e}")
print()

# ── 2. Read the already-saved flow JSON for the exact copy logic ────────────
print("=" * 60)
print("2. Initialize_variable / Initialize_Business_Type_Variable details")
print("=" * 60)
LOCAL_FILE = "account_tyrtype_flow_raw.json"
if not os.path.isfile(LOCAL_FILE):
    print(f"  ! {LOCAL_FILE} not found in the current directory.")
    print("  Run diagnose_tyrtype_businesstype_mismatch.py first to generate it.")
else:
    with open(LOCAL_FILE) as f:
        definition = json.load(f)
    actions = definition.get("actions", {})
    for name in ("Initialize_variable", "Initialize_Business_Type_Variable"):
        if name not in actions:
            print(f"  ! '{name}' not found in the saved definition.")
            continue
        body = actions[name]
        print(f"--- {name} ({body.get('type')}) ---")
        print(f"  {truncate(body.get('inputs', {}))}")
        print()

print("Done. This is read-only -- nothing was changed.")
