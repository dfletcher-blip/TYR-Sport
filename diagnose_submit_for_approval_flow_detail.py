"""
Follow-up on 'Special Terms : Submit for Approval' -- get the full action
tree (not just the email step) so we can see exactly what
'Get_a_Manager_row_by_ID' queries (whose ID it uses as input), and what
feeds the Compose/email body. This tells us whether the flow is using
the record's own 'Approver' lookup field or the submitting user's
systemuser.manager hierarchy -- those can disagree, which would explain
Tom not getting the email even though he's listed as Approver on a
record.

Also pulls recent run history (via flow run bound query on
workflows(id)/... if available) is not exposed simply through Web API,
so instead this checks for any related async operations / failures
tied to this flow by name in the asyncoperations table as a proxy.

Read-only. Makes no changes.

Usage:
    python diagnose_submit_for_approval_flow_detail.py
"""
import os, time, json, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
WORKFLOW_ID = "2b90b0c1-92eb-f011-8543-000d3a5a5d81"  # Special Terms : Submit for Approval

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

def truncate(val, n=1200):
    s = json.dumps(val, indent=2) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

data = get("workflows", {
    "$select": "workflowid,name,clientdata",
    "$filter": f"workflowid eq {WORKFLOW_ID}",
})
matches = data.get("value", [])
if not matches:
    print("! Workflow not found by ID.")
    raise SystemExit(1)

wf = matches[0]
clientdata = wf.get("clientdata") or ""
parsed = json.loads(clientdata)
definition = parsed.get("properties", {}).get("definition", parsed)

with open("special_terms_submit_flow_FULL.json", "w") as f:
    json.dump(parsed, f, indent=2)
print(f"Full definition saved locally to special_terms_submit_flow_FULL.json")
print()

triggers = definition.get("triggers", {})
print("=" * 70)
print("TRIGGERS")
print("=" * 70)
for tname, tbody in triggers.items():
    print(f"  {tname} ({tbody.get('type')})")
    print(f"  inputs: {truncate(tbody.get('inputs', {}), 800)}")
print()

actions = definition.get("actions", {})
print("=" * 70)
print("ALL TOP-LEVEL ACTIONS (in file order)")
print("=" * 70)
for name, body in actions.items():
    print(f"  {name}  ({body.get('type')})")
    run_after = body.get("runAfter")
    if run_after:
        print(f"    runs after: {list(run_after.keys())}")
print()

print("=" * 70)
print("DETAIL: Get_a_Manager_row_by_ID")
print("=" * 70)
if "Get_a_Manager_row_by_ID" in actions:
    body = actions["Get_a_Manager_row_by_ID"]
    print(f"  type: {body.get('type')}")
    print(f"  inputs: {truncate(body.get('inputs', {}), 1200)}")
else:
    print("  ! Not found as a top-level action name -- may be nested or named differently.")
    for name in actions:
        if "manager" in name.lower():
            print(f"  Found similar name: {name}")
            print(f"    inputs: {truncate(actions[name].get('inputs', {}), 1200)}")
print()

print("=" * 70)
print("DETAIL: any action referencing the requester/current user (getting who submitted)")
print("=" * 70)
for name, body in actions.items():
    if any(k in name.lower() for k in ("requester", "current", "get_a_", "user")):
        print(f"  {name} ({body.get('type')})")
        print(f"    inputs: {truncate(body.get('inputs', {}), 600)}")
        print()

print("Done. This is read-only -- nothing was changed.")
