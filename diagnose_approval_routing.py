"""
Diagnostic: find how Angie Nicolletta's lead approval routing is configured
(manager hierarchy, custom routing tables, or workflow conditions) so we
can mirror the same setup for Julie Meredith.
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

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

def find_user(name):
    first, *rest = name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress,parentsystemuserid,_parentsystemuserid_value",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}' and isdisabled eq false",
    })
    users = data.get("value", [])
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress,parentsystemuserid,_parentsystemuserid_value",
            "$filter": f"contains(fullname,'{name}') and isdisabled eq false",
        })
        users = data2.get("value", [])
    return users

def get_manager(user_id):
    try:
        data = get(f"systemusers({user_id})", {
            "$select": "fullname,_parentsystemuserid_value",
            "$expand": "parentsystemuserid($select=systemuserid,fullname,internalemailaddress)",
        })
        mgr = data.get("parentsystemuserid")
        return mgr
    except RuntimeError:
        return None

# ── 1. Look up both users ─────────────────────────────────────────────────────
print("=" * 60)
print("1. Users")
print("=" * 60)
src = find_user("Angie Nicolletta")
tgt = find_user("Julie Meredith")
mgl = find_user("Michael Gallindo")

if not src:
    print("ERROR: Angie Nicolletta not found"); exit(1)
if not tgt:
    print("ERROR: Julie Meredith not found"); exit(1)

src, tgt = src[0], tgt[0]
src_id, tgt_id = src["systemuserid"], tgt["systemuserid"]

print(f"  Angie  : {src['fullname']} — {src_id}")
print(f"  Julie  : {tgt['fullname']} — {tgt_id}")
if mgl:
    mgl = mgl[0]
    print(f"  Michael: {mgl['fullname']} — {mgl['systemuserid']}")
else:
    print("  Michael Gallindo: NOT FOUND — check spelling")
print()

# ── 2. Manager hierarchy ──────────────────────────────────────────────────────
print("=" * 60)
print("2. Manager hierarchy")
print("=" * 60)
src_mgr = get_manager(src_id)
tgt_mgr = get_manager(tgt_id)
print(f"  Angie's manager : {src_mgr['fullname'] if src_mgr else 'None'}")
print(f"  Julie's manager : {tgt_mgr['fullname'] if tgt_mgr else 'None'}")
print()

# ── 3. Find active lead approval workflows ────────────────────────────────────
print("=" * 60)
print("3. Active workflows referencing 'lead' + 'approv'")
print("=" * 60)
try:
    wf_data = get("workflows", {
        "$select": "workflowid,name,category,primaryentity,statecode,_ownerid_value",
        "$filter": "statecode eq 1",
        "$orderby": "name asc",
    })
    wfs = wf_data.get("value", [])
    cat_labels = {0: "Workflow", 1: "Dialog", 4: "BPF", 5: "ModernFlow"}
    relevant = [w for w in wfs if
                ("lead" in (w.get("name") or "").lower() or
                 w.get("primaryentity") == "lead") and
                ("approv" in (w.get("name") or "").lower() or True)]
    print(f"  Lead-related active workflows: {len(relevant)}")
    for w in relevant:
        cat = cat_labels.get(w.get("category"), str(w.get("category")))
        print(f"  [{cat}] {w['name']}  (entity: {w.get('primaryentity','?')})")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 4. Custom routing/approval entities ──────────────────────────────────────
print("=" * 60)
print("4. Custom entities that might hold approval routing")
print("=" * 60)
try:
    ent_data = get("EntityDefinitions", {
        "$select": "LogicalName,DisplayName,IsCustomEntity",
        "$filter": "IsCustomEntity eq true",
    })
    custom = ent_data.get("value", [])
    keywords = ["approv", "routing", "approver", "escalat", "matrix", "delegate"]
    matches = []
    for e in custom:
        name = e.get("LogicalName", "").lower()
        lbl = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "").lower()
        if any(k in name or k in lbl for k in keywords):
            matches.append(e)
    print(f"  Custom entities with approval/routing in name ({len(matches)}):")
    for e in matches:
        lbl = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
        print(f"    {e['LogicalName']}  ({lbl})")
    if not matches:
        print("  None found.")
except RuntimeError as e:
    print(f"  Error: {e}")
print()

# ── 5. Check if Michael Gallindo is on any approval-related team ──────────────
if mgl:
    print("=" * 60)
    print("5. Michael Gallindo's teams")
    print("=" * 60)
    try:
        mgl_teams = get(f"systemusers({mgl['systemuserid']})/teammembership_association",
                        {"$select": "teamid,name,teamtype,isdefault"})
        for t in mgl_teams.get("value", []):
            print(f"  [{t.get('teamtype')}] {t['name']}")
    except RuntimeError as e:
        print(f"  Error: {e}")
    print()

# ── 6. Any records where Angie is listed as approver ─────────────────────────
print("=" * 60)
print("6. Leads owned by Angie (sample) — check approval fields")
print("=" * 60)
try:
    leads = get("leads", {
        "$select": "leadid,fullname,statuscode,statecode",
        "$filter": f"_ownerid_value eq {src_id}",
        "$top": 3,
    })
    lead_list = leads.get("value", [])
    if lead_list:
        # Fetch all fields for first lead to find approval-related ones
        first = lead_list[0]
        full = get(f"leads({first['leadid']})")
        approval_keys = {k: v for k, v in full.items()
                         if any(x in k.lower() for x in ["approv", "tyr_", "manager", "route"])
                         and not k.startswith("@")}
        print(f"  Sample lead: {first.get('fullname','?')}")
        print(f"  Approval-related fields:")
        for k, v in approval_keys.items():
            print(f"    {k}: {v!r}")
    else:
        print("  No leads found for Angie.")
except RuntimeError as e:
    print(f"  Error: {e}")
