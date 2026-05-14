"""
Diagnose "Issue during Approval" errors on Lead records.

Checks:
  1. Recent failed workflow/approval async jobs for leads
  2. Michael Galindo's user record (active, roles, manager, email)
  3. Active lead approval workflows and their XAML for common misconfigs
  4. Optionally look up a specific lead by name

Usage:
    python diagnose_approval_failure.py
    python diagnose_approval_failure.py "Morayo Oshode"
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
LEAD_NAME    = sys.argv[1] if len(sys.argv) > 1 else None

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

def find_user(name):
    first, *rest = name.strip().split()
    last = " ".join(rest)
    d = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,islicensed",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}'",
    })
    users = d.get("value", [])
    if not users:
        d2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled,islicensed",
            "$filter": f"contains(fullname,'{name}')",
        })
        users = d2.get("value", [])
    return users

# ── 1. Specific lead lookup ───────────────────────────────────────────────────
if LEAD_NAME:
    print("=" * 64)
    print(f"1. Lead: '{LEAD_NAME}'")
    print("=" * 64)
    try:
        parts = LEAD_NAME.strip().split()
        fname, lname = parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""
        f = f"contains(fullname,'{LEAD_NAME}')"
        ld = get("leads", {
            "$select": "leadid,fullname,statuscode,statecode,_ownerid_value,tyr_approver,tyr_approverid",
            "$filter": f,
            "$top": 5,
        })
        for lead in ld.get("value", []):
            print(f"  Lead ID  : {lead.get('leadid')}")
            print(f"  Name     : {lead.get('fullname')}")
            print(f"  Status   : {lead.get('statuscode')} / state {lead.get('statecode')}")
            print(f"  Owner ID : {lead.get('_ownerid_value')}")
            # Print any approval-related fields
            for k, v in lead.items():
                if any(x in k.lower() for x in ["approv", "tyr_"]) and not k.startswith("@"):
                    print(f"  {k}: {v}")
            print()

            # Fetch all fields to find hidden approval fields
            full = get(f"leads({lead['leadid']})")
            approval_fields = {k: v for k, v in full.items()
                               if any(x in k.lower() for x in ["approv", "manager", "route"])
                               and not k.startswith("@")}
            if approval_fields:
                print("  Additional approval fields on this lead:")
                for k, v in approval_fields.items():
                    print(f"    {k}: {v!r}")
            print()
    except RuntimeError as e:
        print(f"  Error: {e}")
    print()

# ── 2. Recent failed async jobs for lead approval ─────────────────────────────
print("=" * 64)
print("2. Recent failed workflow/approval jobs (all entities, last 50)")
print("=" * 64)
try:
    jobs = get("asyncoperations", {
        "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,message,createdon,modifiedon,_regardingobjectid_value,regardingobjecttypecode",
        "$filter": "statecode eq 3 and operationtype eq 10",
        "$orderby": "modifiedon desc",
        "$top": 50,
    }).get("value", [])

    lead_jobs = [j for j in jobs if j.get("regardingobjecttypecode") == "lead"]
    other_jobs = [j for j in jobs if j.get("regardingobjecttypecode") != "lead"]

    print(f"  Total failed workflow jobs: {len(jobs)}")
    print(f"  Regarding 'lead' entity   : {len(lead_jobs)}")
    print()

    if lead_jobs:
        print("  --- Lead-related failures ---")
        for j in lead_jobs[:10]:
            print(f"  [{j.get('modifiedon','?')[:19]}] {j.get('name','?')}")
            msg = j.get("friendlymessage") or j.get("message") or ""
            if msg:
                print(f"    Error: {msg[:300]}")
            print(f"    Regarding: {j.get('_regardingobjectid_value','?')}")
            print()
    else:
        print("  No failed jobs directly against lead entity found.")
        print()
        if other_jobs:
            print("  --- Other recent failures (may include approval sub-flows) ---")
            for j in other_jobs[:5]:
                print(f"  [{j.get('modifiedon','?')[:19]}] {j.get('name','?')}")
                msg = j.get("friendlymessage") or j.get("message") or ""
                if msg:
                    print(f"    Error: {msg[:300]}")
                print()
except RuntimeError as e:
    print(f"  Error querying async jobs: {e}")
print()

# Also check approval-specific operation type (operationtype eq 52 = approval)
print("=" * 64)
print("3. Recent failed approval operations (operationtype 52)")
print("=" * 64)
try:
    approvals = get("asyncoperations", {
        "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,message,createdon,modifiedon,regardingobjecttypecode",
        "$filter": "statecode eq 3 and operationtype eq 52",
        "$orderby": "modifiedon desc",
        "$top": 20,
    }).get("value", [])
    print(f"  Failed approval operations: {len(approvals)}")
    for j in approvals[:10]:
        print(f"  [{j.get('modifiedon','?')[:19]}] {j.get('name','?')} (entity: {j.get('regardingobjecttypecode','?')})")
        msg = j.get("friendlymessage") or j.get("message") or ""
        if msg:
            print(f"    Error: {msg[:300]}")
        print()
except RuntimeError as e:
    print(f"  (operationtype 52 not available or no results: {e})")
print()

# ── 3. Michael Galindo user record ────────────────────────────────────────────
print("=" * 64)
print("4. Michael Galindo — user record health check")
print("=" * 64)
galindo_matches = find_user("Michael Galindo")
if not galindo_matches:
    # Try alternate spelling
    galindo_matches = find_user("Michael Gallindo")
if not galindo_matches:
    print("  ERROR: Michael Galindo not found in systemusers (check spelling/disabled).")
else:
    g = galindo_matches[0]
    gid = g["systemuserid"]
    print(f"  Found    : {g['fullname']}")
    print(f"  ID       : {gid}")
    print(f"  Email    : {g.get('internalemailaddress','?')}")
    print(f"  Disabled : {g.get('isdisabled')}")
    print(f"  Licensed : {g.get('islicensed')}")
    print()

    # Get his roles
    try:
        roles = get(f"systemusers({gid})/systemuserroles_association",
                    {"$select": "roleid,name"}).get("value", [])
        print(f"  Roles ({len(roles)}):")
        for r in roles:
            print(f"    {r['name']}")
    except RuntimeError as e:
        print(f"  Could not fetch roles: {e}")
    print()

    # Get his manager
    try:
        ud = get(f"systemusers({gid})", {
            "$select": "fullname",
            "$expand": "parentsystemuserid($select=systemuserid,fullname)",
        })
        mgr = ud.get("parentsystemuserid")
        print(f"  Manager  : {mgr['fullname'] if mgr else 'None (no manager set)'}")
    except RuntimeError as e:
        print(f"  Could not fetch manager: {e}")
    print()
print()

# ── 4. Active lead approval workflows ─────────────────────────────────────────
print("=" * 64)
print("5. Active lead approval workflows")
print("=" * 64)
try:
    wfs = get("workflows", {
        "$select": "workflowid,name,category,statecode,statuscode,primaryentity,xaml",
        "$filter": "statecode eq 1 and (primaryentity eq 'lead' or contains(name,'lead') or contains(name,'Lead'))",
        "$orderby": "name asc",
    }).get("value", [])

    cat_labels = {0: "Workflow", 1: "Dialog", 2: "BusinessRule",
                  3: "Action", 4: "BPF", 5: "ModernFlow", 6: "CustomApi"}
    approval_wfs = [w for w in wfs if
                    any(x in (w.get("name") or "").lower()
                        for x in ["approv", "approve"])]
    print(f"  Active lead-related workflows : {len(wfs)}")
    print(f"  Approval-named among those    : {len(approval_wfs)}")
    print()

    for w in wfs:
        cat = cat_labels.get(w.get("category"), str(w.get("category", "?")))
        print(f"  [{cat}] {w['name']}")
        xaml = w.get("xaml") or ""
        # Flag common misconfigs in XAML
        if xaml:
            flags = []
            if "Galindo" not in xaml and "galindo" not in xaml and "approv" in w.get("name","").lower():
                flags.append("approver name not hardcoded in XAML (uses dynamic lookup)")
            if "parentsystemuserid" in xaml or "manager" in xaml.lower():
                flags.append("routes via manager field")
            if "tyr_approver" in xaml or "tyr_approv" in xaml:
                flags.append("reads tyr_approver field from lead")
            if flags:
                for f in flags:
                    print(f"      NOTE: {f}")
        print()
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 5. Check all-entity approval workflows ────────────────────────────────────
print("=" * 64)
print("6. All active workflows with 'approval' in name (any entity)")
print("=" * 64)
try:
    all_approvals = get("workflows", {
        "$select": "workflowid,name,category,statecode,primaryentity",
        "$filter": "statecode eq 1 and (contains(name,'pproval') or contains(name,'pprove'))",
        "$orderby": "name asc",
    }).get("value", [])
    print(f"  Found: {len(all_approvals)}")
    for w in all_approvals:
        cat = cat_labels.get(w.get("category"), str(w.get("category", "?")))
        print(f"  [{cat}] {w['name']}  (entity: {w.get('primaryentity','?')})")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

print("Diagnostics complete.")
