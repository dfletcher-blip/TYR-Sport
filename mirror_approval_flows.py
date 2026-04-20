"""
Mirror approval flow configuration from Angie Nicolletta to Julie Meredith.

Checks and syncs:
  1. Team memberships
  2. Security roles
  3. Queue memberships
  4. Approval workflows where Angie is a named approver

Usage:
    python mirror_approval_flows.py            # apply changes
    python mirror_approval_flows.py --dry-run  # preview only
"""
import sys, os, json, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

SOURCE_NAME = "Angie Nicolletta"
TARGET_NAME = "Julie Meredith"

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET", "POST", "PATCH", "DELETE"])
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

def post(path, body):
    r = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                      headers=get_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed {r.status_code}: {r.text[:400]}")
    return r

def patch(path, body):
    r = _session.patch(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                       headers=get_headers({"If-Match": "*"}), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PATCH {path} failed {r.status_code}: {r.text[:400]}")
    return r

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

def get_user_teams(user_id):
    data = get(f"systemusers({user_id})/teammembership_association",
               {"$select": "teamid,name,teamtype,isdefault"})
    return data.get("value", [])

def get_user_roles(user_id):
    data = get(f"systemusers({user_id})/systemuserroles_association",
               {"$select": "roleid,name"})
    return data.get("value", [])

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

def queue_id(q):
    raw = q.get("queueid")
    return raw.get("queueid") if isinstance(raw, dict) else raw

def queue_name(q):
    raw = q.get("queueid")
    return raw.get("name", "?") if isinstance(raw, dict) else q.get("name", "?")

def get_approval_workflows_for_user(user_id):
    """
    Find active approval workflows (classic + Power Automate) where this
    user is the owner/assigned approver, or where the workflow is owned
    by this user.
    """
    results = []
    # Workflows owned by the user
    try:
        data = get("workflows", {
            "$select": "workflowid,name,category,statecode,statuscode",
            "$filter": f"_ownerid_value eq {user_id} and statecode eq 1",
        })
        for w in data.get("value", []):
            w["_match_reason"] = "owner"
            results.append(w)
    except RuntimeError as e:
        print(f"  (workflow owner query failed: {e})")

    # Workflows with a process trigger on this user
    try:
        data2 = get("workflows", {
            "$select": "workflowid,name,category,statecode",
            "$filter": (
                f"statecode eq 1 and "
                f"(contains(name,'approval') or contains(name,'Approval') or "
                f"contains(name,'approve') or contains(name,'Approve'))"
            ),
        })
        for w in data2.get("value", []):
            if not any(x["workflowid"] == w["workflowid"] for x in results):
                w["_match_reason"] = "name-match"
                results.append(w)
    except RuntimeError as e:
        print(f"  (approval workflow name query failed: {e})")

    return results

# ── Find both users ───────────────────────────────────────────────────────────
print("Looking up users...")
src_matches = find_user(SOURCE_NAME)
tgt_matches = find_user(TARGET_NAME)

if not src_matches:
    print(f"ERROR: Could not find active user '{SOURCE_NAME}'")
    exit(1)
if not tgt_matches:
    print(f"ERROR: Could not find active user '{TARGET_NAME}'")
    exit(1)

src = src_matches[0]
tgt = tgt_matches[0]
src_id = src["systemuserid"]
tgt_id = tgt["systemuserid"]

print(f"  Source : {src['fullname']} ({src.get('internalemailaddress','')}) — {src_id}")
print(f"  Target : {tgt['fullname']} ({tgt.get('internalemailaddress','')}) — {tgt_id}")
print()

if DRY_RUN:
    print("*** DRY RUN — no changes will be made ***\n")

# ── Teams ─────────────────────────────────────────────────────────────────────
print("Fetching team memberships...")
src_teams = get_user_teams(src_id)
tgt_teams = get_user_teams(tgt_id)
tgt_team_ids = {t["teamid"] for t in tgt_teams}

print(f"  {SOURCE_NAME}: {len(src_teams)} team(s)")
for t in src_teams:
    print(f"    [{t.get('teamtype','')}] {t['name']}" + (" (default)" if t.get("isdefault") else ""))
print(f"  {TARGET_NAME}: {len(tgt_teams)} team(s)")
for t in tgt_teams:
    print(f"    [{t.get('teamtype','')}] {t['name']}")
print()

# ── Roles ─────────────────────────────────────────────────────────────────────
print("Fetching security roles...")
src_roles = get_user_roles(src_id)
tgt_roles = get_user_roles(tgt_id)
tgt_role_ids = {r["roleid"] for r in tgt_roles}

print(f"  {SOURCE_NAME}: {len(src_roles)} role(s)")
for r in src_roles:
    print(f"    {r['name']}")
print(f"  {TARGET_NAME}: {len(tgt_roles)} role(s)")
for r in tgt_roles:
    print(f"    {r['name']}")
print()

# ── Queues ────────────────────────────────────────────────────────────────────
print("Fetching queue memberships...")
src_queues = get_user_queues(src_id)
tgt_queues = get_user_queues(tgt_id)
tgt_queue_ids = {queue_id(q) for q in tgt_queues if queue_id(q)}

print(f"  {SOURCE_NAME}: {len(src_queues)} queue(s)")
for q in src_queues:
    print(f"    {queue_name(q)}")
print(f"  {TARGET_NAME}: {len(tgt_queues)} queue(s)")
for q in tgt_queues:
    print(f"    {queue_name(q)}")
print()

# ── Approval workflows ────────────────────────────────────────────────────────
print("Fetching approval workflows owned by source user...")
src_workflows = get_approval_workflows_for_user(src_id)
tgt_wf_ids = set()
try:
    tgt_wf_data = get("workflows", {
        "$select": "workflowid",
        "$filter": f"_ownerid_value eq {tgt_id} and statecode eq 1",
    })
    tgt_wf_ids = {w["workflowid"] for w in tgt_wf_data.get("value", [])}
except RuntimeError:
    pass

cat_labels = {0: "Workflow", 1: "Dialog", 2: "BusinessRule", 3: "Action",
              4: "BPF", 5: "ModernFlow", 6: "CustomApi"}

print(f"  {SOURCE_NAME} approval-related workflows: {len(src_workflows)}")
for w in src_workflows:
    cat = cat_labels.get(w.get("category"), str(w.get("category", "?")))
    print(f"    [{cat}] {w['name']} (reason: {w.get('_match_reason','')})")
print()

# Workflows owned by Angie that Julie doesn't own
workflows_to_reassign = [w for w in src_workflows
                         if w.get("_match_reason") == "owner"
                         and w["workflowid"] not in tgt_wf_ids]

# ── Diffs ─────────────────────────────────────────────────────────────────────
teams_to_add      = [t for t in src_teams if not t.get("isdefault") and t["teamid"] not in tgt_team_ids]
roles_to_add      = [r for r in src_roles if r["roleid"] not in tgt_role_ids]
queues_to_add     = [q for q in src_queues if queue_id(q) not in tgt_queue_ids]

print("=" * 60)
print("CHANGES TO APPLY")
print("=" * 60)
print(f"  Teams to add        : {len(teams_to_add)}")
for t in teams_to_add:
    print(f"    + {t['name']}")
print(f"  Roles to add        : {len(roles_to_add)}")
for r in roles_to_add:
    print(f"    + {r['name']}")
print(f"  Queues to add       : {len(queues_to_add)}")
for q in queues_to_add:
    print(f"    + {queue_name(q)}")
print(f"  Workflows to co-own : {len(workflows_to_reassign)}")
for w in workflows_to_reassign:
    print(f"    ~ {w['name']} (will add {TARGET_NAME} as owner)")
print()

if not any([teams_to_add, roles_to_add, queues_to_add, workflows_to_reassign]):
    print(f"{TARGET_NAME} already mirrors {SOURCE_NAME}'s approval configuration.")
    exit(0)

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to apply changes.")
    exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
added_teams = added_roles = added_queues = added_wf = 0
errors = 0

if teams_to_add:
    print("Adding team memberships...")
    for t in teams_to_add:
        try:
            post(f"teams({t['teamid']})/teammembership_association/$ref",
                 {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/systemusers({tgt_id})"})
            print(f"  + {t['name']}")
            added_teams += 1
        except RuntimeError as e:
            print(f"  ! {t['name']}: {e}")
            errors += 1
        time.sleep(0.3)

if roles_to_add:
    print("Adding security roles...")
    for r in roles_to_add:
        try:
            post(f"systemusers({tgt_id})/systemuserroles_association/$ref",
                 {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/roles({r['roleid']})"})
            print(f"  + {r['name']}")
            added_roles += 1
        except RuntimeError as e:
            print(f"  ! {r['name']}: {e}")
            errors += 1
        time.sleep(0.3)

if queues_to_add:
    print("Adding queue memberships...")
    for q in queues_to_add:
        qid, qname = queue_id(q), queue_name(q)
        if not qid:
            continue
        try:
            post("queuemembers", {
                "queueid@odata.bind": f"/queues({qid})",
                "systemuserid@odata.bind": f"/systemusers({tgt_id})",
            })
            print(f"  + {qname}")
            added_queues += 1
        except RuntimeError as e:
            print(f"  ! {qname}: {e}")
            errors += 1
        time.sleep(0.3)

if workflows_to_reassign:
    print("Updating workflow ownership...")
    for w in workflows_to_reassign:
        try:
            patch(f"workflows({w['workflowid']})",
                  {"ownerid@odata.bind": f"/systemusers({tgt_id})"})
            print(f"  + {w['name']}")
            added_wf += 1
        except RuntimeError as e:
            print(f"  ! {w['name']}: {e}")
            errors += 1
        time.sleep(0.3)

print()
print("Done.")
print(f"  Teams added        : {added_teams}")
print(f"  Roles added        : {added_roles}")
print(f"  Queues added       : {added_queues}")
print(f"  Workflows updated  : {added_wf}")
if errors:
    print(f"  Errors             : {errors}")
