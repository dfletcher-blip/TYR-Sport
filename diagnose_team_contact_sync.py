"""
Diagnose why sync_team_contact_owners.py found 0 contacts to update.
Checks team owner population and contact→team linkage.

Run: python diagnose_team_contact_sync.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504])))

_token = {"value": None, "expires": 0}

def get_headers():
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        "Accept": "application/json",
        "Prefer": "odata.include-annotations=*",
    }

def get(path, params=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return r.json()


# ── 1. Check team owners ──────────────────────────────────────────────────────
print("=" * 60)
print("CHECK 1: Do tyr_teams records have an owner set?")
print("=" * 60)

# Get PK field name
sample = get("tyr_teams", {"$top": 1, "$select": "createdon"})
pk_field = next((k for k in sample.get("value", [{}])[0].keys()
                 if k.endswith("id") and "@" not in k and "odata" not in k), "tyr_teamid")
print(f"  Primary key field: {pk_field}")

teams = get("tyr_teams", {
    "$select": f"{pk_field},_ownerid_value",
    "$top": 10,
}).get("value", [])

teams_with_owner = [t for t in teams if t.get("_ownerid_value")]
print(f"  Sample of 10 teams — {len(teams_with_owner)}/10 have _ownerid_value set")
for t in teams[:5]:
    owner = t.get("_ownerid_value")
    owner_name = t.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", "")
    print(f"    {t.get(pk_field, '?')[:36]}  owner={owner_name or owner or 'NOT SET'}")

if not teams_with_owner:
    print("\n  *** NO TEAMS HAVE AN OWNER SET — this is why 0 contacts are updated.")
    print("  The tyr_team entity may not use a standard 'ownerid' field.")
    print("  Let's check what fields it actually has...")

    # Inspect the fields on a team record
    raw = get("tyr_teams", {"$top": 1}).get("value", [{}])[0]
    print("\n  All fields on a sample tyr_team record:")
    for k, v in sorted(raw.items()):
        if "@" not in k and v is not None:
            print(f"    {k}: {str(v)[:60]}")

print()


# ── 2. Check contact→team linkage ────────────────────────────────────────────
print("=" * 60)
print("CHECK 2: Do any contacts have tyr_team lookup set?")
print("=" * 60)

try:
    linked = get("contacts", {
        "$select": "contactid,fullname,_tyr_team_value",
        "$filter": "_tyr_team_value ne null and statecode eq 0",
        "$top": 5,
    })
    linked_contacts = linked.get("value", [])
    print(f"  Contacts with tyr_team set: {len(linked_contacts)} (showing up to 5)")
    for c in linked_contacts:
        team_name = c.get("_tyr_team_value@OData.Community.Display.V1.FormattedValue", "")
        print(f"    {c.get('fullname','?')}  →  team={team_name or c.get('_tyr_team_value','?')}")
    if not linked_contacts:
        print("  *** ZERO contacts have tyr_team populated.")
        print("  Contacts are not linked to any tyr_team record.")
except RuntimeError as e:
    print(f"  Query failed: {e}")

print()


# ── 3. Summary ────────────────────────────────────────────────────────────────
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print("""
  The sync script matches contacts to teams via the tyr_team lookup
  field on the Contact record. If that field is empty across all
  contacts, nothing will ever be synced.

  Possible next steps:
  A) Populate tyr_team on contacts (bulk-set from account or another field)
  B) Use a different relationship — e.g. account→team→contact chain
  C) The sync should be based on something else (e.g. Account owner → Contact owner)
""")
