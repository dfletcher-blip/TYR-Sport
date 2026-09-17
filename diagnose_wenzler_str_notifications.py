"""
Diagnostic: why isn't Tom Wenzler receiving email notifications on
Special Terms (STR) approvals?

Compares Tom Wenzler against Ross Davenport (a known-working STR approver)
across the same dimensions that have caused approval-routing gaps before:
  1. User record health (disabled, missing/invalid email address)
  2. Team memberships
  3. Security roles
  4. Queue memberships
  5. Manager hierarchy (some STR steps route via manager)
  6. Workflows/flows related to Special Terms — which ones name/target
     Ross but not Tom, and whether they're Active or Draft/Inactive
  7. Recent failed runs of any STR-related workflow

This is READ-ONLY. It makes no changes. Run this first; a follow-up
fix script (mirroring fix_julie_approval_routing.py / mirror_approval_flows.py)
should only be written once the actual cause is confirmed here.

Usage:
    python diagnose_wenzler_str_notifications.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

WORKING_APPROVER = "Ross Davenport"
NOT_RECEIVING = "Tom Wenzler"

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
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
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:400]}")
    return r.json()

def find_user(full_name):
    first, *rest = full_name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled,"
                    "_parentsystemuserid_value,donotbulkemail,donotemail",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}'",
    })
    users = data.get("value", [])
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled,"
                        "_parentsystemuserid_value,donotbulkemail,donotemail",
            "$filter": f"contains(fullname,'{full_name}')",
        })
        users = data2.get("value", [])
    return users

def get_manager(user_id):
    data = get(f"systemusers({user_id})",
               {"$select": "fullname,_parentsystemuserid_value",
                "$expand": "parentsystemuserid($select=systemuserid,fullname)"})
    return data.get("parentsystemuserid")

def get_user_teams(user_id):
    return get(f"systemusers({user_id})/teammembership_association",
               {"$select": "teamid,name,teamtype,isdefault"}).get("value", [])

def get_user_roles(user_id):
    return get(f"systemusers({user_id})/systemuserroles_association",
               {"$select": "roleid,name"}).get("value", [])

def get_user_queues(user_id):
    for attempt in [
        lambda: get(f"systemusers({user_id})/queuemembership_systemuser",
                    {"$select": "queueid,name,queuetypecode"}),
        lambda: get("queues", {
            "$select": "queueid,name,queuetypecode",
            "$filter": f"queue_membership/any(m: m/_systemuserid_value eq {user_id})",
        }),
    ]:
        try:
            return attempt().get("value", [])
        except RuntimeError:
            pass
    print("  (queue membership lookup not supported on this org — skipping)")
    return []

def get_str_entity():
    candidates = ["tyr_specialterms", "tyr_specialterm", "cr_specialterms",
                  "cr_specialterm", "new_specialterms", "new_specialterm",
                  "tyr_strs", "tyr_str"]
    for name in candidates:
        try:
            result = get(name, {"$top": 1, "$select": "createdon"})
            if "value" in result:
                return name
        except RuntimeError:
            continue
    return None

def get_str_related_workflows():
    """All workflows (classic + Power Automate) touching Special Terms/approval, any state."""
    results = {}
    try:
        by_name = get("workflows", {
            "$select": "workflowid,name,category,statecode,statuscode,primaryentity,"
                        "description,_ownerid_value,modifiedon",
            "$filter": "(contains(tolower(name),'special term') or contains(tolower(name),'str') "
                        "or contains(tolower(name),'approval'))",
            "$orderby": "name asc",
        }).get("value", [])
        for w in by_name:
            results[w["workflowid"]] = w
    except RuntimeError as e:
        print(f"  (workflow name search failed: {e})")

    entity = get_str_entity()
    if entity:
        entity_singular = entity.rstrip("s")
        try:
            by_entity = get("workflows", {
                "$select": "workflowid,name,category,statecode,statuscode,primaryentity,"
                            "description,_ownerid_value,modifiedon",
                "$filter": f"contains(primaryentity,'{entity_singular}')",
            }).get("value", [])
            for w in by_entity:
                results[w["workflowid"]] = w
        except RuntimeError as e:
            print(f"  (workflow entity search failed: {e})")

    return list(results.values())

def recent_failed_runs_for_workflow(workflow_name, limit=10):
    try:
        jobs = get("asyncoperations", {
            "$top": limit,
            "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,modifiedon",
            "$filter": f"statecode eq 3 and operationtype eq 10 and contains(name,'{workflow_name}')",
            "$orderby": "modifiedon desc",
        }).get("value", [])
        return jobs
    except RuntimeError:
        return []

cat_labels = {0: "Workflow", 1: "Dialog", 2: "BusinessRule", 3: "Action",
              4: "BPF", 5: "ModernFlow (Power Automate)", 6: "CustomApi"}
state_labels = {(1, 2): "Active", (0, 1): "Draft", (0, 3): "Inactive"}

print("=" * 70)
print(f"Diagnosing: why does {WORKING_APPROVER} get STR approval emails")
print(f"            but {NOT_RECEIVING} does not?")
print("=" * 70)
print()

# ── 1. User records ──────────────────────────────────────────────────────────
print("1. User records")
print("-" * 70)
src_matches = find_user(WORKING_APPROVER)
tgt_matches = find_user(NOT_RECEIVING)

if not src_matches:
    print(f"  ERROR: could not find '{WORKING_APPROVER}' — check spelling."); exit(1)
if not tgt_matches:
    print(f"  ERROR: could not find '{NOT_RECEIVING}' — check spelling."); exit(1)

src, tgt = src_matches[0], tgt_matches[0]
src_id, tgt_id = src["systemuserid"], tgt["systemuserid"]

for label, u in [(WORKING_APPROVER, src), (NOT_RECEIVING, tgt)]:
    print(f"  {label}")
    print(f"    id            : {u['systemuserid']}")
    print(f"    email         : {u.get('internalemailaddress') or 'MISSING'}")
    print(f"    disabled      : {u.get('isdisabled')}")
    print(f"    donotemail    : {u.get('donotemail')}")
    print(f"    donotbulkemail: {u.get('donotbulkemail')}")
print()

issues = []
if tgt.get("isdisabled"):
    issues.append(f"{NOT_RECEIVING}'s user record is DISABLED.")
if not tgt.get("internalemailaddress"):
    issues.append(f"{NOT_RECEIVING} has no email address on file.")
if tgt.get("donotemail"):
    issues.append(f"{NOT_RECEIVING} has 'Do Not Email' set — this alone can suppress CRM-sent email.")

# ── 2. Manager hierarchy ─────────────────────────────────────────────────────
print("2. Manager hierarchy")
print("-" * 70)
src_mgr = get_manager(src_id)
tgt_mgr = get_manager(tgt_id)
print(f"  {WORKING_APPROVER}'s manager: {src_mgr['fullname'] if src_mgr else 'None'}")
print(f"  {NOT_RECEIVING}'s manager: {tgt_mgr['fullname'] if tgt_mgr else 'None'}")
print()

# ── 3. Teams ──────────────────────────────────────────────────────────────────
print("3. Team memberships")
print("-" * 70)
src_teams = get_user_teams(src_id)
tgt_teams = get_user_teams(tgt_id)
tgt_team_ids = {t["teamid"] for t in tgt_teams}
print(f"  {WORKING_APPROVER}: {len(src_teams)} team(s)")
for t in src_teams:
    flag = "  <-- missing on Tom" if t["teamid"] not in tgt_team_ids and not t.get("isdefault") else ""
    print(f"    [{t.get('teamtype')}] {t['name']}{flag}")
print(f"  {NOT_RECEIVING}: {len(tgt_teams)} team(s)")
for t in tgt_teams:
    print(f"    [{t.get('teamtype')}] {t['name']}")
teams_missing = [t for t in src_teams if not t.get("isdefault") and t["teamid"] not in tgt_team_ids]
print()

# ── 4. Security roles ─────────────────────────────────────────────────────────
print("4. Security roles")
print("-" * 70)
src_roles = get_user_roles(src_id)
tgt_roles = get_user_roles(tgt_id)
tgt_role_ids = {r["roleid"] for r in tgt_roles}
print(f"  {WORKING_APPROVER}: {len(src_roles)} role(s)")
for r in src_roles:
    flag = "  <-- missing on Tom" if r["roleid"] not in tgt_role_ids else ""
    print(f"    {r['name']}{flag}")
print(f"  {NOT_RECEIVING}: {len(tgt_roles)} role(s)")
for r in tgt_roles:
    print(f"    {r['name']}")
roles_missing = [r for r in src_roles if r["roleid"] not in tgt_role_ids]
print()

# ── 5. Queues ─────────────────────────────────────────────────────────────────
print("5. Queue memberships")
print("-" * 70)
src_queues = get_user_queues(src_id)
tgt_queues = get_user_queues(tgt_id)
def qid(q):
    raw = q.get("queueid"); return raw.get("queueid") if isinstance(raw, dict) else raw
def qname(q):
    raw = q.get("queueid"); return raw.get("name", "?") if isinstance(raw, dict) else q.get("name", "?")
tgt_queue_ids = {qid(q) for q in tgt_queues if qid(q)}
print(f"  {WORKING_APPROVER}: {len(src_queues)} queue(s)")
for q in src_queues:
    flag = "  <-- missing on Tom" if qid(q) not in tgt_queue_ids else ""
    print(f"    {qname(q)}{flag}")
print(f"  {NOT_RECEIVING}: {len(tgt_queues)} queue(s)")
for q in tgt_queues:
    print(f"    {qname(q)}")
queues_missing = [q for q in src_queues if qid(q) not in tgt_queue_ids]
print()

# ── 6. Special Terms workflows / flows ────────────────────────────────────────
print("6. Special Terms / approval workflows & flows")
print("-" * 70)
wfs = get_str_related_workflows()
print(f"  Found {len(wfs)} related workflow(s)/flow(s):")
draft_or_inactive = []
modern_flows = []
for w in wfs:
    cat = cat_labels.get(w.get("category"), str(w.get("category")))
    state = state_labels.get((w.get("statecode"), w.get("statuscode")), "Unknown")
    print(f"    [{cat}] {w['name']}  — {state}  (entity: {w.get('primaryentity','?')})")
    if state != "Active":
        draft_or_inactive.append(w)
    if w.get("category") == 5:
        modern_flows.append(w)
print()
if draft_or_inactive:
    issues.append(
        f"{len(draft_or_inactive)} STR/approval workflow(s) are Draft/Inactive: "
        + ", ".join(w["name"] for w in draft_or_inactive)
    )
if modern_flows:
    print("  NOTE: Power Automate flow(s) found. This API cannot read their step-by-step")
    print("  recipient configuration (e.g. dynamic 'To' expressions). If the cause isn't")
    print("  found below, check these directly in the Power Automate portal's run history:")
    for w in modern_flows:
        print(f"    - {w['name']}")
    print()

# ── 7. Recent failures on STR-related workflows ───────────────────────────────
print("7. Recent failed runs on STR/approval workflows")
print("-" * 70)
any_failures = False
for w in wfs:
    fails = recent_failed_runs_for_workflow(w["name"])
    if fails:
        any_failures = True
        print(f"  {w['name']}: {len(fails)} recent failure(s)")
        for f in fails[:3]:
            print(f"    - {f.get('modifiedon','')}: {f.get('friendlymessage','')[:150]}")
if not any_failures:
    print("  No recent failures found for these workflows.")
print()

# ── Summary ────────────────────────────────────────────────────────────────────
print("=" * 70)
print("SUMMARY")
print("=" * 70)
if teams_missing:
    issues.append(
        f"{NOT_RECEIVING} is missing {len(teams_missing)} team(s) that {WORKING_APPROVER} has: "
        + ", ".join(t["name"] for t in teams_missing)
    )
if roles_missing:
    issues.append(
        f"{NOT_RECEIVING} is missing {len(roles_missing)} security role(s) that {WORKING_APPROVER} has: "
        + ", ".join(r["name"] for r in roles_missing)
    )
if queues_missing:
    issues.append(
        f"{NOT_RECEIVING} is missing {len(queues_missing)} queue(s) that {WORKING_APPROVER} has: "
        + ", ".join(qname(q) for q in queues_missing)
    )

if issues:
    print("Likely cause(s):")
    for i in issues:
        print(f"  - {i}")
else:
    print(f"No difference found between {WORKING_APPROVER} and {NOT_RECEIVING} in team/role/queue/")
    print("manager/user-record configuration. The workflow's email step likely has a static")
    print("recipient list (or an individually-named recipient) that simply never included Tom —")
    print("open the workflow(s)/flow(s) listed in section 6 in the Dynamics UI and check the")
    print("'Send Email' step's To/CC configuration directly.")
