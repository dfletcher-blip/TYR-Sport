"""
Tom Wenzler isn't receiving email notifications for Special Terms
approvals. Find every flow with "Special Terms" in the name, and for
each one, print its triggers and any email/notification actions
(Send an email (V2), Send email, notification actions), including the
recipient expressions -- so we can see exactly who the flow is
configured to email and why Tom might not be getting it (wrong
recipient field, wrong condition, flow turned off, etc.).

Also looks up Tom Wenzler's systemuser record (email address, team
memberships) since the flow's recipient logic will likely reference
either his email directly, a lookup field on the record, or a team.

Read-only. Makes no changes.

Usage:
    python diagnose_special_terms_email_notification.py
"""
import os, time, json, requests
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

def truncate(val, n=800):
    s = json.dumps(val) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

def find_email_actions(tree, path=""):
    """Recursively walk an actions dict and yield (path, name, body) for
    anything that looks like an email/notification action."""
    results = []
    for name, body in tree.items():
        atype = body.get("type", "")
        full_path = f"{path}/{name}" if path else name
        if "email" in name.lower() or atype in ("OpenApiConnection", "ApiConnection") and "mail" in json.dumps(body.get("inputs", {})).lower():
            results.append((full_path, name, body))
        # Recurse into If/Switch branches
        if atype == "If":
            results += find_email_actions(body.get("actions", {}), full_path + "/actions")
            results += find_email_actions(body.get("else", {}).get("actions", {}), full_path + "/else")
        if atype == "Switch":
            for case_name, case_body in body.get("cases", {}).items():
                results += find_email_actions(case_body.get("actions", {}), f"{full_path}/{case_name}")
            results += find_email_actions(body.get("default", {}).get("actions", {}), full_path + "/default")
        if atype == "Foreach":
            results += find_email_actions(body.get("actions", {}), full_path + "/foreach")
        if atype == "Scope":
            results += find_email_actions(body.get("actions", {}), full_path + "/scope")
    return results

# ── 1. Tom Wenzler's user record ─────────────────────────────────────────────
print("=" * 70)
print("1. Tom Wenzler systemuser record")
print("=" * 70)
try:
    user_data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,domainname,isdisabled",
        "$filter": "fullname eq 'Tom Wenzler'",
    })
    users = user_data.get("value", [])
    if not users:
        print("  ! No systemuser found with fullname 'Tom Wenzler'. Trying contains match...")
        user_data = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,domainname,isdisabled",
            "$filter": "contains(fullname, 'Wenzler')",
        })
        users = user_data.get("value", [])
    for u in users:
        print(f"  {u.get('fullname')}  id={u.get('systemuserid')}")
        print(f"    email: {u.get('internalemailaddress')}")
        print(f"    domainname: {u.get('domainname')}")
        print(f"    isdisabled: {u.get('isdisabled')}")
except RuntimeError as e:
    print(f"  ! Lookup failed: {e}")
print()

# ── 2. All flows with 'Special Terms' in the name ────────────────────────────
print("=" * 70)
print("2. Flows with 'Special Terms' in the name")
print("=" * 70)
data = get("workflows", {
    "$select": "workflowid,name,clientdata,statecode,statuscode,category",
    "$filter": "category eq 5",
})
matches = [w for w in data.get("value", []) if "special terms" in (w.get("name") or "").lower()]
if not matches:
    print("  ! No flows found with 'Special Terms' in the name.")
for wf in matches:
    print("-" * 70)
    print(f"  {wf.get('name')}")
    print(f"  workflowid: {wf.get('workflowid')}")
    print(f"  statecode/statuscode: {wf.get('statecode')}/{wf.get('statuscode')}  (statecode 1 = Activated)")
    clientdata = wf.get("clientdata") or ""
    try:
        parsed = json.loads(clientdata)
    except json.JSONDecodeError:
        print("  ! clientdata wasn't valid JSON.")
        continue
    definition = parsed.get("properties", {}).get("definition", parsed)

    triggers = definition.get("triggers", {})
    print("  Triggers:")
    for tname, tbody in triggers.items():
        print(f"    {tname} ({tbody.get('type')})")
        inputs = tbody.get("inputs", {})
        if "parameters" in inputs:
            print(f"      parameters: {truncate(inputs['parameters'], 300)}")

    actions = definition.get("actions", {})
    email_actions = find_email_actions(actions)
    if not email_actions:
        print("  ! No email/notification-looking actions found in this flow.")
    for full_path, name, body in email_actions:
        print(f"  Email-like action: {full_path}")
        print(f"    type: {body.get('type')}")
        inputs = body.get("inputs", {})
        if isinstance(inputs, dict):
            host = inputs.get("host", {})
            if host:
                print(f"    operationId: {host.get('operationId')}")
            params = inputs.get("parameters", {})
            if isinstance(params, dict):
                for k, v in params.items():
                    if any(key in str(k).lower() for key in ("to", "recipient", "subject", "body")):
                        print(f"    param.{k}: {truncate(v, 500)}")
        print()
    print()

print("Done. This is read-only -- nothing was changed.")
