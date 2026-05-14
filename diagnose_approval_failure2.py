"""
Follow-up approval failure diagnosis.

Fixes the field-name errors from the first run and drills into:
  1. Correct API name for the 'Approver' lookup on lead
  2. Recent failed async jobs (fixed query — no regardingobjecttypecode)
  3. Run history for the approval notification flow specifically
  4. All lead fields with 'approv' in name/label

Usage:
    python diagnose_approval_failure2.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

_session = requests.Session()
_retry   = Retry(total=4, backoff_factor=3,
                 status_forcelist=[429, 500, 502, 503, 504],
                 allowed_methods=["GET", "POST", "PATCH"])
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
        raise RuntimeError(f"GET {path} → {r.status_code}: {r.text[:500]}")
    return r.json()

# ── 1. Find the actual API field name for 'Approver' on lead ──────────────────
print("=" * 64)
print("1. Lead entity — fields with 'approv' in name or label")
print("=" * 64)
try:
    attrs = get(
        "EntityDefinitions(LogicalName='lead')/Attributes",
        {"$select": "LogicalName,DisplayName,AttributeType,IsCustomAttribute"},
    ).get("value", [])

    approv_fields = []
    for a in attrs:
        name = a.get("LogicalName", "").lower()
        label = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "").lower()
        if "approv" in name or "approv" in label:
            approv_fields.append(a)

    if approv_fields:
        print(f"  Found {len(approv_fields)} approval-related field(s):")
        for a in approv_fields:
            label = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "?")
            print(f"    LogicalName : {a['LogicalName']}")
            print(f"    Label       : {label}")
            print(f"    Type        : {a.get('AttributeType')}")
            print(f"    Custom      : {a.get('IsCustomAttribute')}")
            print()
    else:
        print("  No fields with 'approv' found on lead.")
        print("  Listing ALL custom lead fields instead:")
        custom = [a for a in attrs if a.get("IsCustomAttribute")]
        for a in custom[:30]:
            label = ((a.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "?")
            print(f"    {a['LogicalName']:40s}  ({label})")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 2. Recent failed async jobs — fixed query ─────────────────────────────────
print("=" * 64)
print("2. Recent failed workflow jobs (fixed — last 30)")
print("=" * 64)
try:
    jobs = get("asyncoperations", {
        "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,message,createdon,modifiedon",
        "$filter": "statecode eq 3 and operationtype eq 10",
        "$orderby": "modifiedon desc",
        "$top": 30,
    }).get("value", [])

    print(f"  Total failed workflow jobs: {len(jobs)}")
    print()
    for j in jobs[:15]:
        print(f"  [{j.get('modifiedon','?')[:19]}]  {j.get('name','?')}")
        msg = j.get("friendlymessage") or j.get("message") or ""
        if msg:
            print(f"    Error: {msg[:400]}")
        print()
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 3. Get the approval notification flow ID then check its run history ────────
print("=" * 64)
print("3. 'Lead : Send an Approval notification to manager' — details")
print("=" * 64)
approval_flow_id = None
try:
    wfs = get("workflows", {
        "$select": "workflowid,name,statecode,statuscode,category,description",
        "$filter": "contains(name,'Send an Approval notification')",
    }).get("value", [])
    for w in wfs:
        print(f"  Name     : {w['name']}")
        print(f"  ID       : {w['workflowid']}")
        print(f"  State    : {w.get('statecode')} / {w.get('statuscode')}")
        print(f"  Category : {w.get('category')}")
        print(f"  Desc     : {w.get('description','')[:200]}")
        print()
        approval_flow_id = w["workflowid"]
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 4. Failed runs for the approval notification flow ─────────────────────────
if approval_flow_id:
    print("=" * 64)
    print("4. Failed async jobs for approval notification flow")
    print("=" * 64)
    try:
        flow_jobs = get("asyncoperations", {
            "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,message,createdon,modifiedon",
            "$filter": f"statecode eq 3 and _workflowactivationid_value eq {approval_flow_id}",
            "$orderby": "modifiedon desc",
            "$top": 10,
        }).get("value", [])
        print(f"  Failed runs for this flow: {len(flow_jobs)}")
        for j in flow_jobs:
            print(f"  [{j.get('modifiedon','?')[:19]}]  {j.get('name','?')}")
            msg = j.get("friendlymessage") or j.get("message") or ""
            if msg:
                print(f"    Error: {msg[:400]}")
            print()
        if not flow_jobs:
            print("  No failed runs found by workflowactivationid.")
            print("  (Power Automate runs may not log to asyncoperations — see section 5)")
    except RuntimeError as e:
        print(f"  Error (trying fallback): {e}")
        # Fallback: search by name
        try:
            flow_jobs2 = get("asyncoperations", {
                "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,message,createdon,modifiedon",
                "$filter": "statecode eq 3 and contains(name,'Approval notification')",
                "$orderby": "modifiedon desc",
                "$top": 10,
            }).get("value", [])
            print(f"  (Fallback by name) Failed runs: {len(flow_jobs2)}")
            for j in flow_jobs2:
                print(f"  [{j.get('modifiedon','?')[:19]}]  {j.get('name','?')}")
                msg = j.get("friendlymessage") or j.get("message") or ""
                if msg:
                    print(f"    Error: {msg[:400]}")
                print()
        except RuntimeError as e2:
            print(f"  Fallback also failed: {e2}")
    print()

# ── 5. All 3 lead ModernFlows — check for any process errors logged ───────────
print("=" * 64)
print("5. All 3 lead ModernFlows — recent failed runs (search by name)")
print("=" * 64)
flow_names = [
    "Send an Approval notification to manager",
    "Send Notification to Finance Team",
    "Send Notification to Sales Rep",
]
for fname in flow_names:
    try:
        runs = get("asyncoperations", {
            "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,modifiedon",
            "$filter": f"statecode eq 3 and contains(name,'{fname[:40]}')",
            "$orderby": "modifiedon desc",
            "$top": 5,
        }).get("value", [])
        print(f"  '{fname}': {len(runs)} failed run(s)")
        for j in runs:
            print(f"    [{j.get('modifiedon','?')[:19]}]")
            msg = j.get("friendlymessage") or ""
            if msg:
                print(f"    Error: {msg[:300]}")
    except RuntimeError as e:
        print(f"  '{fname}': query error — {e}")
print()

# ── 6. Check Joe Eiden user record (lead owner in screenshot) ─────────────────
print("=" * 64)
print("6. Joe Eiden — user record check")
print("=" * 64)
try:
    users = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,islicensed",
        "$filter": "contains(fullname,'Joe Eiden') and isdisabled eq false",
    }).get("value", [])
    if not users:
        users = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled,islicensed",
            "$filter": "contains(fullname,'Eiden')",
        }).get("value", [])
    if users:
        u = users[0]
        uid = u["systemuserid"]
        print(f"  Found    : {u['fullname']}")
        print(f"  Email    : {u.get('internalemailaddress','?')}")
        print(f"  Disabled : {u.get('isdisabled')}")
        print(f"  Licensed : {u.get('islicensed')}")
        # Check manager
        ud = get(f"systemusers({uid})", {
            "$select": "fullname",
            "$expand": "parentsystemuserid($select=systemuserid,fullname)",
        })
        mgr = ud.get("parentsystemuserid")
        print(f"  Manager  : {mgr['fullname'] if mgr else 'NONE — no manager set'}")
        if not mgr:
            print()
            print("  *** LIKELY ROOT CAUSE ***")
            print("  The flow 'Send an Approval notification to manager' routes")
            print("  to the lead owner's MANAGER. If Joe Eiden has no manager set,")
            print("  the flow fails to resolve the approver and throws the error.")
    else:
        print("  Joe Eiden not found.")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("Diagnostics complete.")
