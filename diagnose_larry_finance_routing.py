"""
Diagnostic: understand how Lead and Special Terms approval routing to
Finance actually works in this org, now that we know real Power Automate
flows exist for it (discovered via diagnose_lead_qualify_email.py) --
they just weren't tagged with primaryentity the way earlier searches
this session assumed, which is why they were missed originally.

Checks:
  1. Larry Meltzer's current manager (a missing manager may explain why
     his leads never reach an approver, and therefore never reach Finance).
  2. The clientdata (flow definition) of the relevant flows, so we can
     see their actual trigger/condition logic rather than guessing:
       - Lead : Send an Approval notification to manager
       - Lead : Send Notification to Finance Team to Qualify lead
       - Special Terms : Submit for Approval
       - Special Terms Approval : Assign STR to Finance Credit Team

Read-only. Makes no changes.

Usage:
    python diagnose_larry_finance_routing.py
"""
import sys, os, time, json, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

TARGET_NAME = "Larry Meltzer"
FLOW_NAMES = [
    "Lead : Send an Approval notification to manager",
    "Lead : Send Notification to Finance Team to Qualify lead",
    "Special Terms : Submit for Approval",
    "Special Terms Approval : Assign STR to Finance Credit Team",
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

def find_user(full_name):
    first, *rest = full_name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}'",
    })
    users = [u for u in data.get("value", []) if not u.get("isdisabled")]
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled",
            "$filter": f"contains(fullname,'{full_name}')",
        })
        users = [u for u in data2.get("value", []) if not u.get("isdisabled")]
    return users

# ── 1. Larry's manager ───────────────────────────────────────────────────────
print("=" * 60)
print(f"1. {TARGET_NAME}'s manager")
print("=" * 60)
matches = find_user(TARGET_NAME)
if not matches:
    print(f"  ERROR: '{TARGET_NAME}' not found")
else:
    larry = matches[0]
    print(f"  {larry['fullname']} ({larry.get('internalemailaddress','')}) -- {larry['systemuserid']}")
    try:
        detail = get(f"systemusers({larry['systemuserid']})", {
            "$select": "fullname",
            "$expand": "parentsystemuserid($select=fullname,systemuserid)",
        })
        mgr = detail.get("parentsystemuserid")
        print(f"  Manager: {mgr.get('fullname') if mgr else '(none set)'}")
    except RuntimeError as e:
        print(f"  ! Manager lookup failed: {e}")
print()

# ── 2. Fetch and summarize the relevant flows ────────────────────────────────
print("=" * 60)
print("2. Flow definitions")
print("=" * 60)
for name in FLOW_NAMES:
    print(f"--- {name} ---")
    try:
        # Fetch all category-5 flows and match by exact name client-side,
        # since contains() isn't supported and we want an exact match anyway.
        data = get("workflows", {
            "$select": "workflowid,name,clientdata,statecode,statuscode",
            "$filter": "category eq 5",
        })
        candidates = [w for w in data.get("value", []) if w.get("name") == name]
        if not candidates:
            print("  ! Not found by exact name match.")
            print()
            continue
        wf = candidates[0]
        clientdata = wf.get("clientdata") or ""
        print(f"  workflowid: {wf.get('workflowid')}")
        print(f"  length: {len(clientdata)} chars")

        if not clientdata:
            print("  (no clientdata on this record)")
            print()
            continue

        try:
            parsed = json.loads(clientdata)
        except json.JSONDecodeError:
            print("  (clientdata is not valid JSON -- printing raw first 1500 chars)")
            print(f"  {clientdata[:1500]}")
            print()
            continue

        # Print the trigger and a condensed view of top-level actions/conditions
        definition = parsed.get("properties", {}).get("definition", parsed)
        triggers = definition.get("triggers", {})
        actions = definition.get("actions", {})

        print("  Triggers:")
        for tname, tbody in triggers.items():
            ttype = tbody.get("type")
            print(f"    {tname} ({ttype})")
            inputs = tbody.get("inputs", {})
            if "parameters" in inputs:
                print(f"      parameters: {json.dumps(inputs['parameters'])[:400]}")

        print("  Top-level actions:")
        for aname, abody in actions.items():
            atype = abody.get("type")
            print(f"    {aname} ({atype})")
            if atype == "If":
                expr = abody.get("expression", {})
                print(f"      condition expression: {json.dumps(expr)[:500]}")
            if atype in ("SendEmail", "ApiConnection") and "inputs" in abody:
                inp = abody["inputs"]
                # Try to surface recipient/body fields if present without dumping everything
                for key in ("to", "body", "parameters"):
                    if isinstance(inp, dict) and key in inp:
                        val = inp[key]
                        if isinstance(val, dict):
                            for subkey in ("emailTo", "to", "body", "Subject", "Body"):
                                if subkey in val:
                                    print(f"      {key}.{subkey}: {str(val[subkey])[:300]}")
        print()
    except RuntimeError as e:
        print(f"  ! Lookup failed: {e}")
        print()

print("Done. This is read-only -- nothing was changed.")
