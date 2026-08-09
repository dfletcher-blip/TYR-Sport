"""
Ensure Larry Meltzer's Lead and Special Terms (STR) submissions route to
the "Finance" team/queue for approval.

Adds Larry to the Finance team and Finance queue in Dynamics 365 (if he
isn't already a member) so the existing Lead and Special Terms approval
workflows can route his submissions to Finance for sign-off. Also reports
the Active/Draft status of any Lead- or Special-Terms-related approval
workflows, since a Draft workflow won't fire regardless of team/queue
membership.

This script intentionally does NOT auto-activate inactive workflows —
that would be an org-wide change affecting every user, not just Larry.
If a relevant workflow is found in Draft/Inactive status, it is reported
so it can be activated separately with explicit confirmation.

Usage:
    python setup_larry_finance_approval_routing.py --dry-run   # preview
    python setup_larry_finance_approval_routing.py             # apply
"""
import sys, os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

TARGET_NAME = "Larry Meltzer"
FINANCE_NAME_FILTER = "Finance"

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

def post(path, body):
    r = _session.post(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                      headers=get_headers(), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} failed {r.status_code}: {r.text[:400]}")
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
               {"$select": "teamid,name,teamtype"})
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

def find_str_entity():
    """
    Discover the Special Terms entity via metadata. Dynamics stores two
    different names for a custom entity: the singular LogicalName (used by
    workflows.primaryentity) and the pluralized LogicalCollectionName (used
    in record URLs, e.g. tyr_specialterms -> tyr_specialtermses). Using the
    collection name where the logical name is expected causes a 400.

    Returns (collection_name, logical_name), or (None, None) if not found.
    """
    try:
        meta = get("EntityDefinitions", {
            "$select": "LogicalName,LogicalCollectionName,DisplayName",
            "$filter": "IsCustomEntity eq true",
        })
        for e in meta.get("value", []):
            label = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
            if "special term" in label.lower():
                return e.get("LogicalCollectionName", ""), e.get("LogicalName", "")
    except RuntimeError as e:
        print(f"  (entity metadata lookup failed: {e})")
    return None, None

def get_approval_workflows(entities):
    """
    Find approval-related workflows for the given entities.

    This org's 'workflows' entity rejects the contains() OData function
    (501 'function not supported'), so filter server-side only on fields
    that support eq (primaryentity, category), and match the name keyword
    client-side in Python instead.
    """
    results = {}
    for entity in entities:
        try:
            data = get("workflows", {
                "$select": "workflowid,name,statecode,statuscode,primaryentity",
                "$filter": f"primaryentity eq '{entity}' and category eq 0",
            })
            all_wf = data.get("value", [])
            results[entity] = [
                w for w in all_wf
                if "approval" in w.get("name", "").lower()
                or "finance" in w.get("name", "").lower()
            ]
        except RuntimeError as e:
            print(f"  (workflow lookup for '{entity}' failed: {e})")
            results[entity] = []
    return results

STATUS_LABELS = {(1, 2): "Active", (0, 1): "Draft", (0, 3): "Inactive"}

# ── Look up Larry ───────────────────────────────────────────────────────────
print("Looking up user...")
matches = find_user(TARGET_NAME)
if not matches:
    print(f"ERROR: '{TARGET_NAME}' not found")
    sys.exit(1)
larry = matches[0]
larry_id = larry["systemuserid"]
print(f"  {larry['fullname']} ({larry.get('internalemailaddress', '')}) — {larry_id}")
print()

if DRY_RUN:
    print("*** DRY RUN — no changes will be made ***\n")

# ── Find the Finance team & queue ────────────────────────────────────────────
print(f"Looking up teams/queues matching '{FINANCE_NAME_FILTER}'...")
finance_teams = get("teams", {
    "$select": "teamid,name,teamtype",
    "$filter": f"contains(name,'{FINANCE_NAME_FILTER}')",
}).get("value", [])

finance_queues = get("queues", {
    "$select": "queueid,name,queuetypecode",
    "$filter": f"contains(name,'{FINANCE_NAME_FILTER}')",
}).get("value", [])

if not finance_teams and not finance_queues:
    print(f"ERROR: No team or queue found matching '{FINANCE_NAME_FILTER}'.")
    print("Check the exact name in Dynamics (Settings > Security > Teams / Queues) and re-run.")
    sys.exit(1)

print(f"  Finance team(s) : {', '.join(t['name'] for t in finance_teams) or '(none found)'}")
print(f"  Finance queue(s): {', '.join(q['name'] for q in finance_queues) or '(none found)'}")
print()

# ── Larry's current memberships ──────────────────────────────────────────────
print("Checking Larry's current team/queue memberships...")
larry_teams = get_user_teams(larry_id)
larry_team_ids = {t["teamid"] for t in larry_teams}
larry_queues = get_user_queues(larry_id)
larry_queue_ids = {queue_id(q) for q in larry_queues if queue_id(q)}

teams_to_add = [t for t in finance_teams if t["teamid"] not in larry_team_ids]
queues_to_add = [q for q in finance_queues if q["queueid"] not in larry_queue_ids]

print(f"  Currently on {len(larry_teams)} team(s), {len(larry_queues)} queue(s)")
print(f"  Finance team(s) to add : {len(teams_to_add)}")
for t in teams_to_add:
    print(f"    + {t['name']}")
print(f"  Finance queue(s) to add: {len(queues_to_add)}")
for q in queues_to_add:
    print(f"    + {q['name']}")
print()

# ── Check the Lead + Special Terms approval workflows exist and are active ──
str_collection, str_logical = find_str_entity()
if str_logical:
    print(f"Special Terms entity: logical name '{str_logical}' (records at '{str_collection}')")
else:
    print("Could not auto-discover the Special Terms entity from metadata.")
entities_to_check = ["lead"] + ([str_logical] if str_logical else [])
print(f"Checking approval workflows for: {', '.join(entities_to_check)}...")
workflows_by_entity = get_approval_workflows(entities_to_check)
inactive_found = []
for entity, wfs in workflows_by_entity.items():
    if not wfs:
        print(f"  {entity}: no approval-named workflow found — Finance routing may not be automated for this entity.")
        continue
    for w in wfs:
        label = STATUS_LABELS.get((w.get("statecode"), w.get("statuscode")), "Unknown")
        print(f"  {entity}: '{w['name']}' — {label}")
        if label != "Active":
            inactive_found.append(w)
print()

if inactive_found:
    print("WARNING: The following approval workflows are not Active. Finance")
    print("routing will not fire until these are published/activated:")
    for w in inactive_found:
        print(f"    - {w['name']}")
    print("This script does not activate workflows automatically since that")
    print("is an org-wide change affecting every user, not just Larry.")
    print("Activate manually, or ask for that as a separate explicit change.")
    print()

if not teams_to_add and not queues_to_add:
    print("Larry is already a member of the matching Finance team(s)/queue(s).")
    if not inactive_found:
        print("No further changes needed.")
    sys.exit(0)

if DRY_RUN:
    print("Dry run complete. Run without --dry-run to apply changes.")
    sys.exit(0)

# ── Apply ─────────────────────────────────────────────────────────────────────
added_teams = added_queues = 0
errors = 0

if teams_to_add:
    print("Adding Larry to Finance team(s)...")
    for t in teams_to_add:
        try:
            post(f"teams({t['teamid']})/teammembership_association/$ref",
                 {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/systemusers({larry_id})"})
            print(f"  + {t['name']}")
            added_teams += 1
        except RuntimeError as e:
            print(f"  ! {t['name']}: {e}")
            errors += 1
        time.sleep(0.3)

if queues_to_add:
    print("Adding Larry to Finance queue(s)...")
    for q in queues_to_add:
        try:
            post("queuemembers", {
                "queueid@odata.bind": f"/queues({q['queueid']})",
                "systemuserid@odata.bind": f"/systemusers({larry_id})",
            })
            print(f"  + {q['name']}")
            added_queues += 1
        except RuntimeError as e:
            print(f"  ! {q['name']}: {e}")
            errors += 1
        time.sleep(0.3)

print()
print("Done.")
print(f"  Finance teams added : {added_teams}")
print(f"  Finance queues added: {added_queues}")
if errors:
    print(f"  Errors              : {errors}")
if inactive_found:
    print(f"  NOTE: {len(inactive_found)} approval workflow(s) still need manual activation — see warning above.")
