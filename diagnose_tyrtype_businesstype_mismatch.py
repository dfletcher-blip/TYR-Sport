"""
Diagnostic: why TYR Type / Business Type end up different on the new
Account than what was on the Lead, after Convert to Contact runs.

Our script only sets Account.name when creating the Account -- it never
copies TYR Type / Business Type from the Lead. There's also an existing
ACTIVE flow ('Account : Update TYR and Business Type on Creation',
found in the org-wide flow search earlier) that likely sets these
fields on every new Account using its own logic, independent of the
Lead -- so even copying the values ourselves might get overwritten
afterward if that flow doesn't check for an existing value first.

This checks:
  1. The exact logical field names on Lead and Account that relate to
     "type" or "business" (they may not be named identically).
  2. The clientdata (condition logic) of 'Account : Update TYR and
     Business Type on Creation', to see whether it always sets these
     fields or only when they're blank.

Read-only. Makes no changes.

Usage:
    python diagnose_tyrtype_businesstype_mismatch.py
"""
import os, time, json, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
FLOW_NAME = "Account : Update TYR and Business Type on Creation"

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

def truncate(val, n=600):
    s = json.dumps(val) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

# ── 1. Field names on Lead and Account ───────────────────────────────────────
for entity in ["lead", "account"]:
    print("=" * 60)
    print(f"1. '{entity}' fields matching 'type' or 'business'")
    print("=" * 60)
    try:
        data = get(f"EntityDefinitions(LogicalName='{entity}')/Attributes")
        for a in data.get("value", []):
            logical = a.get("LogicalName", "") or ""
            display = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
            if "type" in logical.lower() or "business" in logical.lower() or "type" in display.lower() or "business" in display.lower():
                print(f"  {logical}  (\"{display}\")  type={a.get('AttributeType')}")
    except RuntimeError as e:
        print(f"  ! Attribute lookup failed: {e}")
    print()

# ── 2. The 'on creation' flow's logic ────────────────────────────────────────
print("=" * 60)
print(f"2. '{FLOW_NAME}'")
print("=" * 60)
try:
    data = get("workflows", {
        "$select": "workflowid,name,clientdata,statecode,statuscode",
        "$filter": "category eq 5",
    })
    matches = [w for w in data.get("value", []) if w.get("name") == FLOW_NAME]
    if not matches:
        print("  ! Not found by exact name match.")
    else:
        wf = matches[0]
        clientdata = wf.get("clientdata") or ""
        parsed = json.loads(clientdata)
        definition = parsed.get("properties", {}).get("definition", parsed)

        with open("account_tyrtype_flow_raw.json", "w") as f:
            json.dump(definition, f, indent=2)
        print(f"  Full definition saved locally to account_tyrtype_flow_raw.json ({len(clientdata)} chars)")
        print()

        triggers = definition.get("triggers", {})
        for tname, tbody in triggers.items():
            print(f"  Trigger: {tname} ({tbody.get('type')})")
            inputs = tbody.get("inputs", {})
            if "parameters" in inputs:
                print(f"    parameters: {truncate(inputs['parameters'], 400)}")

        actions = definition.get("actions", {})
        print(f"  Top-level actions:")
        for aname, abody in actions.items():
            atype = abody.get("type")
            print(f"    {aname} ({atype})")
            if atype == "If":
                expr = abody.get("expression", {})
                print(f"      condition: {truncate(expr, 500)}")
            if atype == "OpenApiConnection":
                inp = abody.get("inputs", {})
                params = inp.get("parameters", {})
                if isinstance(params, dict):
                    for k, v in params.items():
                        if "tyr" in str(k).lower() or "business" in str(k).lower() or "type" in str(k).lower():
                            print(f"      parameters.{k}: {truncate(v, 300)}")
except RuntimeError as e:
    print(f"  ! Lookup failed: {e}")
except json.JSONDecodeError as e:
    print(f"  ! clientdata wasn't valid JSON: {e}")
print()

print("Done. This is read-only -- nothing was changed.")
