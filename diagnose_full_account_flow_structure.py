"""
Full structural read of 'Account : Update TYR and Business Type on Creation'
before we attempt to fix it -- we only ever read two of its actions'
declarations before (Initialize_variable / Initialize_Business_Type_Variable),
never the full condition/branch tree that actually sets the values on the
Account. This is a shared, org-wide flow (not just our Convert to Contact
button), so before editing it we need the complete picture.

Prints every action: name, type, condition/expression (if a Condition or
Switch), inputs (truncated), and what it runs after -- in execution order
where possible. Saves the full raw definition locally as
account_tyrtype_flow_FULL.json.

Read-only. Makes no changes.

Usage:
    python diagnose_full_account_flow_structure.py
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

def truncate(val, n=800):
    s = json.dumps(val) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

def print_action_tree(actions, indent=0):
    pad = "  " * indent
    for name, body in actions.items():
        atype = body.get("type")
        print(f"{pad}- {name}  ({atype})")
        run_after = body.get("runAfter")
        if run_after:
            print(f"{pad}    runs after: {list(run_after.keys())}")
        if atype in ("If", "Switch"):
            expr = body.get("expression", body.get("cases"))
            print(f"{pad}    expression/cases: {truncate(expr, 1200)}")
            if atype == "If":
                for branch_key in ("actions", "else"):
                    branch = body.get(branch_key)
                    if branch_key == "else" and isinstance(branch, dict):
                        branch = branch.get("actions", {})
                    if branch:
                        print(f"{pad}    [{branch_key}]")
                        print_action_tree(branch, indent + 3)
            if atype == "Switch":
                cases = body.get("cases", {})
                for case_name, case_body in cases.items():
                    print(f"{pad}    [case: {case_name}] value={truncate(case_body.get('case'), 200)}")
                    print_action_tree(case_body.get("actions", {}), indent + 3)
                default = body.get("default", {}).get("actions", {})
                if default:
                    print(f"{pad}    [default]")
                    print_action_tree(default, indent + 3)
        elif atype in ("InitializeVariable",):
            print(f"{pad}    inputs: {truncate(body.get('inputs', {}), 500)}")
        elif atype in ("SetVariable",):
            print(f"{pad}    inputs: {truncate(body.get('inputs', {}), 500)}")
        elif atype in ("OpenApiConnection",):
            inputs = body.get("inputs", {})
            params = inputs.get("parameters", {})
            host = inputs.get("host", {})
            print(f"{pad}    operationId: {host.get('operationId')}")
            if isinstance(params, dict):
                for k, v in params.items():
                    print(f"{pad}    param.{k}: {truncate(v, 300)}")
        else:
            print(f"{pad}    inputs: {truncate(body.get('inputs', {}), 400)}")
        print()

print("=" * 70)
print(f"'{FLOW_NAME}'")
print("=" * 70)

data = get("workflows", {
    "$select": "workflowid,name,clientdata,statecode,statuscode",
    "$filter": "category eq 5",
})
matches = [w for w in data.get("value", []) if w.get("name") == FLOW_NAME]
if not matches:
    print("! Not found by exact name match.")
    raise SystemExit(1)

wf = matches[0]
workflow_id = wf.get("workflowid")
print(f"workflowid: {workflow_id}")
print(f"statecode/statuscode: {wf.get('statecode')}/{wf.get('statuscode')}")
print()

clientdata = wf.get("clientdata") or ""
parsed = json.loads(clientdata)
definition = parsed.get("properties", {}).get("definition", parsed)

with open("account_tyrtype_flow_FULL.json", "w") as f:
    json.dump(parsed, f, indent=2)
print(f"Full raw clientdata saved locally to account_tyrtype_flow_FULL.json ({len(clientdata)} chars)")
print()

triggers = definition.get("triggers", {})
print("TRIGGERS:")
for tname, tbody in triggers.items():
    print(f"  {tname} ({tbody.get('type')})")
    inputs = tbody.get("inputs", {})
    if "parameters" in inputs:
        print(f"    parameters: {truncate(inputs['parameters'], 500)}")
print()

print("ACTION TREE (top-level, in file order -- not necessarily execution order):")
print()
actions = definition.get("actions", {})
print_action_tree(actions)

print("Done. This is read-only -- nothing was changed.")
