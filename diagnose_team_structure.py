"""
Inspect tyr_team record structure to find how Teams relate to Accounts/Contacts.
Run: python diagnose_team_structure.py
"""
import os, time, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

def get_headers():
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        "Accept": "application/json",
        "Prefer": "odata.include-annotations=*",
    }

def get(path, params=None):
    r = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return r.json()


# ── 1. Show all fields on a sample Team record ────────────────────────────────
print("=" * 60)
print("All fields on a sample tyr_team record")
print("=" * 60)
sample = get("tyr_teams", {"$top": 1})
record = sample.get("value", [{}])[0]
for k, v in sorted(record.items()):
    if "@" not in k and v is not None:
        print(f"  {k}: {str(v)[:80]}")

print()

# ── 2. Cross-reference the 5 known linked contacts ───────────────────────────
print("=" * 60)
print("Cross-reference: contacts with tyr_team set")
print("(shows contact, their parent account, and the team)")
print("=" * 60)

contacts = get("contacts", {
    "$select": "contactid,fullname,_tyr_team_value,_parentcustomerid_value",
    "$filter": "_tyr_team_value ne null and statecode eq 0",
    "$top": 10,
}).get("value", [])

for c in contacts:
    team_id   = c.get("_tyr_team_value")
    team_name = c.get("_tyr_team_value@OData.Community.Display.V1.FormattedValue", "")
    acct_id   = c.get("_parentcustomerid_value")
    acct_name = c.get("_parentcustomerid_value@OData.Community.Display.V1.FormattedValue", "")

    print(f"  Contact : {c.get('fullname')}")
    print(f"  Account : {acct_name or acct_id or 'NONE'}")
    print(f"  Team    : {team_name or team_id}")

    # Fetch the team record to see its fields
    if team_id:
        try:
            team = get(f"tyr_teams({team_id})")
            # Show non-null, non-annotation fields
            team_fields = {k: v for k, v in team.items()
                           if "@" not in k and v is not None and k != "@odata.context"}
            print(f"  Team fields: {team_fields}")
        except RuntimeError as e:
            print(f"  Team fetch error: {e}")
    print()
