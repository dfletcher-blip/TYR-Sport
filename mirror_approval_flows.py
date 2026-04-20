"""
Mirror approval flow configuration from one user to another.

Reads Angie Nicoletta's team memberships, security roles, and queue memberships
then applies any missing ones to Julie Meredith.

Usage:
    python mirror_approval_flows.py

Set DRY_RUN=1 to preview changes without applying them:
    DRY_RUN=1 python mirror_approval_flows.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = os.getenv("DRY_RUN", "0").strip() == "1"

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

def delete(path):
    r = _session.delete(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                        headers=get_headers(), timeout=30)
    if not r.ok:
        raise RuntimeError(f"DELETE {path} failed {r.status_code}: {r.text[:400]}")
    return r

def find_user(full_name):
    """Look up a systemuser by full name."""
    first, *rest = full_name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,isdisabled",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}'",
    })
    users = [u for u in data.get("value", []) if not u.get("isdisabled")]
    if not users:
        # Fallback: contains search on fullname
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,isdisabled",
            "$filter": f"contains(fullname,'{full_name}')",
        })
        users = [u for u in data2.get("value", []) if not u.get("isdisabled")]
    return users

def get_user_teams(user_id):
    """Return list of teams the user belongs to."""
    data = get(f"systemusers({user_id})/teammembership_association",
               {"$select": "teamid,name,teamtype,isdefault"})
    return data.get("value", [])

def get_user_roles(user_id):
    """Return list of security roles assigned directly to the user."""
    data = get(f"systemusers({user_id})/systemuserroles_association",
               {"$select": "roleid,name,businessunitid"})
    return data.get("value", [])

def get_user_queues(user_id):
    """Return queues the user is a member of."""
    data = get("queuemembers", {
        "$select": "queuememberid,queueid",
        "$expand": "queueid($select=name,queueid,queuetypecode)",
        "$filter": f"systemuserid eq {user_id}",
    })
    return data.get("value", [])

# ── Find both users ───────────────────────────────────────────────────────────
print(f"Looking up users...")
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

# ── Fetch current state ───────────────────────────────────────────────────────
print("Fetching team memberships...")
src_teams = get_user_teams(src_id)
tgt_teams = get_user_teams(tgt_id)
tgt_team_ids = {t["teamid"] for t in tgt_teams}

print(f"  {SOURCE_NAME}: {len(src_teams)} team(s)")
for t in src_teams:
    marker = "(default)" if t.get("isdefault") else ""
    print(f"    [{t.get('teamtype','')}] {t['name']} {marker}")
print(f"  {TARGET_NAME}: {len(tgt_teams)} team(s)")
for t in tgt_teams:
    print(f"    [{t.get('teamtype','')}] {t['name']}")
print()

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

print("Fetching queue memberships...")
src_queues = get_user_queues(src_id)
tgt_queues = get_user_queues(tgt_id)
tgt_queue_ids = {q["queueid"]["queueid"] for q in tgt_queues if q.get("queueid")}

print(f"  {SOURCE_NAME}: {len(src_queues)} queue(s)")
for q in src_queues:
    qi = q.get("queueid") or {}
    print(f"    {qi.get('name','?')} (type {qi.get('queuetypecode','?')})")
print(f"  {TARGET_NAME}: {len(tgt_queues)} queue(s)")
for q in tgt_queues:
    qi = q.get("queueid") or {}
    print(f"    {qi.get('name','?')}")
print()

# ── Compute diffs ─────────────────────────────────────────────────────────────
teams_to_add   = [t for t in src_teams if not t.get("isdefault") and t["teamid"] not in tgt_team_ids]
roles_to_add   = [r for r in src_roles if r["roleid"] not in tgt_role_ids]
queues_to_add  = [q for q in src_queues
                  if (q.get("queueid") or {}).get("queueid") not in tgt_queue_ids]

print("=" * 60)
print("CHANGES TO APPLY")
print("=" * 60)
print(f"  Teams to add  : {len(teams_to_add)}")
for t in teams_to_add:
    print(f"    + {t['name']}")
print(f"  Roles to add  : {len(roles_to_add)}")
for r in roles_to_add:
    print(f"    + {r['name']}")
print(f"  Queues to add : {len(queues_to_add)}")
for q in queues_to_add:
    qi = q.get("queueid") or {}
    print(f"    + {qi.get('name','?')}")
print()

if not teams_to_add and not roles_to_add and not queues_to_add:
    print(f"{TARGET_NAME} already has the same approval configuration as {SOURCE_NAME}.")
    exit(0)

if DRY_RUN:
    print("Dry run complete — re-run without DRY_RUN=1 to apply changes.")
    exit(0)

# ── Apply changes ─────────────────────────────────────────────────────────────
added_teams = added_roles = added_queues = 0
errors = 0

if teams_to_add:
    print("Adding team memberships...")
    for t in teams_to_add:
        try:
            post(
                f"teams({t['teamid']})/teammembership_association/$ref",
                {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/systemusers({tgt_id})"},
            )
            print(f"  + Added to team: {t['name']}")
            added_teams += 1
        except RuntimeError as e:
            print(f"  ! Failed to add team '{t['name']}': {e}")
            errors += 1
        time.sleep(0.3)

if roles_to_add:
    print("Adding security roles...")
    for r in roles_to_add:
        try:
            post(
                f"systemusers({tgt_id})/systemuserroles_association/$ref",
                {"@odata.id": f"{DYNAMICS_URL}/api/data/v9.2/roles({r['roleid']})"},
            )
            print(f"  + Added role: {r['name']}")
            added_roles += 1
        except RuntimeError as e:
            print(f"  ! Failed to add role '{r['name']}': {e}")
            errors += 1
        time.sleep(0.3)

if queues_to_add:
    print("Adding queue memberships...")
    for q in queues_to_add:
        qi = q.get("queueid") or {}
        queue_id = qi.get("queueid")
        queue_name = qi.get("name", "?")
        if not queue_id:
            continue
        try:
            post("queuemembers", {
                "queueid@odata.bind": f"/queues({queue_id})",
                "systemuserid@odata.bind": f"/systemusers({tgt_id})",
            })
            print(f"  + Added to queue: {queue_name}")
            added_queues += 1
        except RuntimeError as e:
            print(f"  ! Failed to add queue '{queue_name}': {e}")
            errors += 1
        time.sleep(0.3)

print()
print(f"Done.")
print(f"  Teams added  : {added_teams}")
print(f"  Roles added  : {added_roles}")
print(f"  Queues added : {added_queues}")
if errors:
    print(f"  Errors       : {errors}")
