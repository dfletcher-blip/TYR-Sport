"""
Part 2 of approval diagnosis — runs sections 4-6 from diagnose_approval_failure2.py
using the already-known flow ID, plus checks ALL lead owners for missing managers.

Usage:
    python diagnose_approval_failure3.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL    = os.getenv("DYNAMICS_URL", "").rstrip("/")
APPROVAL_FLOW_ID = "221ff832-9cb2-fdb7-427c-db720a92ca8a"

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

# ── 1. Failed runs for the approval notification flow ─────────────────────────
print("=" * 64)
print("1. Failed async jobs for the approval flow (by ID)")
print("=" * 64)
try:
    flow_jobs = get("asyncoperations", {
        "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,message,createdon,modifiedon",
        "$filter": f"statecode eq 3 and _workflowactivationid_value eq {APPROVAL_FLOW_ID}",
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
        print("  None — Power Automate flows log run history in PA portal, not asyncoperations.")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 2. Joe Eiden — manager check ──────────────────────────────────────────────
print("=" * 64)
print("2. Joe Eiden — manager check")
print("=" * 64)
try:
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
        ud = get(f"systemusers({uid})", {
            "$select": "fullname",
            "$expand": "parentsystemuserid($select=systemuserid,fullname)",
        })
        mgr = ud.get("parentsystemuserid")
        print(f"  Manager  : {mgr['fullname'] if mgr else 'NONE — no manager set'}")
    else:
        print("  Joe Eiden not found.")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 3. ALL active lead owners — check which have no manager ───────────────────
print("=" * 64)
print("3. Active leads — owners with no manager set")
print("=" * 64)
try:
    leads = get("leads", {
        "$select": "leadid,fullname,_ownerid_value",
        "$filter": "statecode eq 0",
        "$top": 500,
    }).get("value", [])

    owner_ids = list({l["_ownerid_value"] for l in leads if l.get("_ownerid_value")})
    print(f"  Open leads     : {len(leads)}")
    print(f"  Unique owners  : {len(owner_ids)}")
    print()

    no_manager = []
    has_manager = []
    for uid in owner_ids:
        try:
            ud = get(f"systemusers({uid})", {
                "$select": "fullname,internalemailaddress",
                "$expand": "parentsystemuserid($select=systemuserid,fullname)",
            })
            mgr = ud.get("parentsystemuserid")
            name = ud.get("fullname", uid)
            if mgr:
                has_manager.append((name, mgr["fullname"]))
            else:
                no_manager.append(name)
        except RuntimeError:
            no_manager.append(f"(unknown user {uid})")
        time.sleep(0.15)

    print(f"  Owners WITH manager    : {len(has_manager)}")
    for name, mgr in has_manager:
        print(f"    {name:35s}  → {mgr}")
    print()
    print(f"  Owners WITHOUT manager : {len(no_manager)}")
    for name in no_manager:
        print(f"    *** {name}")
    print()

    if no_manager:
        print("  *** ROOT CAUSE CONFIRMED if flow routes to lead-owner's manager ***")
        print("  The 'Send an Approval notification to manager' flow will fail for")
        print("  any lead owned by a user with no manager set.")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 4. Sample open leads — check tyr_approvedby field ────────────────────────
print("=" * 64)
print("4. Sample open leads — tyr_approvedby field populated?")
print("=" * 64)
try:
    sample = get("leads", {
        "$select": "leadid,fullname,tyr_approvalstatus,_tyr_approvedby_value,_ownerid_value",
        "$filter": "statecode eq 0",
        "$top": 10,
    }).get("value", [])
    submitted = [l for l in sample if l.get("tyr_approvalstatus") is not None]
    print(f"  Sample leads: {len(sample)}")
    for l in sample:
        status = l.get("tyr_approvalstatus")
        approvedby = l.get("_tyr_approvedby_value")
        print(f"  {l.get('fullname','?'):35s}  status={status}  approvedby={approvedby or 'NULL'}")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 5. Approval flow XAML (may be empty for ModernFlow) ───────────────────────
print("=" * 64)
print("5. Approval flow definition (clientdata/xaml excerpt)")
print("=" * 64)
try:
    wf = get(f"workflows({APPROVAL_FLOW_ID})", {
        "$select": "name,xaml,clientdata,description,primaryentity,triggeronupdateattributelist,triggeroncreate",
    })
    print(f"  Name             : {wf.get('name')}")
    print(f"  Primary entity   : {wf.get('primaryentity') or 'none'}")
    print(f"  Trigger on create: {wf.get('triggeroncreate')}")
    print(f"  Trigger fields   : {wf.get('triggeronupdateattributelist') or 'none'}")
    print()
    xaml = (wf.get("xaml") or "")[:800]
    client = (wf.get("clientdata") or "")[:800]
    if xaml:
        print(f"  XAML (first 800 chars):\n{xaml}\n")
    else:
        print("  XAML: empty (ModernFlow — definition stored in Power Automate)")
    if client:
        print(f"  clientdata (first 800 chars):\n{client}\n")
    else:
        print("  clientdata: empty")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("Diagnostics complete.")
