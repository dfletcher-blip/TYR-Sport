"""
Deep-dive on 'Lead : Send an Approval notification to manager' --
extract the actual inputs of its key actions (how it determines who the
manager is, who gets emailed, what the bound action does) so we can see
exactly where a "if this is Larry, skip to Finance" branch would need
to go, instead of guessing from action names alone.

Read-only. Makes no changes. Prints condensed, not the full ~6KB JSON,
to keep output pasteable.

Usage:
    python diagnose_lead_manager_approval_flow.py
"""
import os, time, json, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
FLOW_NAME = "Lead : Send an Approval notification to manager"

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

def truncate(val, n=500):
    s = json.dumps(val) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

data = get("workflows", {
    "$select": "workflowid,name,clientdata",
    "$filter": "category eq 5",
})
matches = [w for w in data.get("value", []) if w.get("name") == FLOW_NAME]
if not matches:
    print(f"ERROR: '{FLOW_NAME}' not found")
    raise SystemExit(1)

wf = matches[0]
clientdata = wf.get("clientdata") or ""
parsed = json.loads(clientdata)
definition = parsed.get("properties", {}).get("definition", parsed)
actions = definition.get("actions", {})

# Save the full raw JSON locally too, in case we need to dig further
# without re-fetching, but don't print all of it to the console.
with open("lead_manager_approval_flow_raw.json", "w") as f:
    json.dump(definition, f, indent=2)
print(f"Full definition saved locally to lead_manager_approval_flow_raw.json ({len(clientdata)} chars)")
print()

INTERESTING = [
    "Get_a_Manager_row_by_ID",
    "Get_a_User_row_by_ID",
    "Get_a_row_by_ID",
    "Send_email_(V2)",
    "Perform_a_bound_action",
    "Add_a_new_row",
    "Compose",
    "Link",
]

for name in INTERESTING:
    if name not in actions:
        continue
    body = actions[name]
    print("=" * 60)
    print(f"{name}  (type: {body.get('type')})")
    print("=" * 60)
    inputs = body.get("inputs", {})
    if isinstance(inputs, dict):
        for k, v in inputs.items():
            print(f"  {k}: {truncate(v, 600)}")
    else:
        print(f"  inputs: {truncate(inputs, 600)}")
    run_after = body.get("runAfter")
    if run_after:
        print(f"  runs after: {list(run_after.keys())}")
    print()

print("Done. This is read-only -- nothing was changed.")
