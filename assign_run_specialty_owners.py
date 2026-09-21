# Assign Run Specialty / USA contacts and leads to regional reps by state.
# Skips records owned by Brandon Sullivan or Bill Potter.
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_patch

# ── Region map ─────────────────────────────────────────────────────────────
REGION_MAP = {
    # West
    "CA": "West", "WA": "West", "OR": "West", "NV": "West", "ID": "West",
    "UT": "West", "AZ": "West", "MT": "West", "WY": "West", "CO": "West",
    "NM": "West", "AK": "West", "HI": "West",
    # Midwest
    "IL": "Midwest", "VA": "Midwest", "MI": "Midwest", "IN": "Midwest",
    "WI": "Midwest", "MN": "Midwest", "IA": "Midwest", "MO": "Midwest",
    "KS": "Midwest", "NE": "Midwest", "SD": "Midwest", "ND": "Midwest",
    "AR": "Midwest", "WV": "Midwest", "KY": "Midwest", "DC": "Midwest",
    # South
    "TX": "South", "OK": "South", "LA": "South", "MS": "South", "AL": "South",
    "TN": "South", "FL": "South", "GA": "South", "SC": "South", "NC": "South",
    # Northeast
    "NY": "Northeast", "PA": "Northeast", "OH": "Northeast", "NJ": "Northeast",
    "MD": "Northeast", "DE": "Northeast", "CT": "Northeast", "MA": "Northeast",
    "RI": "Northeast", "NH": "Northeast", "VT": "Northeast", "ME": "Northeast",
}

# Full state name → abbreviation
STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

def normalize_state(raw):
    s = (raw or "").strip()
    if not s:
        return ""
    # Already a 2-letter abbreviation
    if len(s) <= 2:
        return s.upper()
    # Full name lookup
    abbr = STATE_NAME_TO_ABBR.get(s.lower())
    if abbr:
        return abbr
    # Fallback: first 2 chars (handles e.g. "TX - Texas")
    return s[:2].upper()

PREVIEW = "--preview" in sys.argv

# ── Look up rep GUIDs ───────────────────────────────────────────────────────
def find_user(name):
    parts = name.strip().split()
    first, last = parts[0], parts[-1]
    r = crm_get("systemusers", {
        "$filter": f"firstname eq '{first}' and lastname eq '{last}' and isdisabled eq false",
        "$select": "systemuserid,fullname",
        "$top": 5,
    })
    users = r.get("value", [])
    if not users:
        raise ValueError(f"User not found: {name}")
    return users[0]["systemuserid"], users[0]["fullname"]

print("Looking up rep GUIDs...")
region_owner = {}
for region, rep_name in [
    ("West",      "Marina Preiss"),
    ("Midwest",   "Caroline Kulp"),
    ("South",     "Angela Nicolletta"),
    ("Northeast", "Dan MacQuarrie"),
]:
    uid, full = find_user(rep_name)
    region_owner[region] = uid
    print(f"  {region}: {full} ({uid})")

skip_brandon_id, _ = find_user("Brandon Sullivan")
skip_bill_id, _    = find_user("Bill Potter")
print(f"  Skip: Brandon Sullivan ({skip_brandon_id})")
print(f"  Skip: Bill Potter ({skip_bill_id})")

# ── Helper: fetch pages ─────────────────────────────────────────────────────
def fetch_all(entity, params, limit=5000):
    from config.crm_connection import DYNAMICS_URL
    base = f"{DYNAMICS_URL}/api/data/v9.2/"
    records = []
    page = crm_get(entity, params)
    records.extend(page.get("value", []))
    nxt = page.get("@odata.nextLink")
    while nxt and len(records) < limit:
        rel = nxt[len(base):] if nxt.startswith(base) else nxt
        page = crm_get(rel, {})
        records.extend(page.get("value", []))
        nxt = page.get("@odata.nextLink")
    return records

# ── Process contacts and leads ──────────────────────────────────────────────
TYR_TYPE_RUN_SPECIALTY         = 935650018   # integer value for Run Specialty (contacts)
TYR_TYPE_RUN_SPECIALTY_LEAD    = 935650016   # string value for Run Specialty (leads)
TYR_ENTITY_USA         = 935650000   # integer value for USA

SKIP_OWNERS = {skip_brandon_id, skip_bill_id}

totals = {"updated": 0, "skipped_owner": 0, "skipped_no_state": 0,
          "skipped_no_region": 0, "errors": 0}

for entity, state_field, id_field, name_field, type_filter, entity_filter in [
    ("contacts", "address1_stateorprovince", "contactid", "fullname",
     f"tyr_tyrtype eq {TYR_TYPE_RUN_SPECIALTY}",
     f"tyr_tyrentity eq {TYR_ENTITY_USA}"),
    ("leads",    "address1_stateorprovince", "leadid",    "fullname",
     f"contains(tyr_tyrtype,'{TYR_TYPE_RUN_SPECIALTY_LEAD}')",
     f"tyr_tyrentity eq {TYR_ENTITY_USA}"),
]:
    print(f"\n=== Processing {entity} ===")
    records = fetch_all(entity, {
        "$select": f"{id_field},{name_field},{state_field},tyr_tyrtype,tyr_tyrentity,_ownerid_value",
        "$filter": (
            f"statecode eq 0 and {entity_filter}"
            if type_filter is None
            else f"statecode eq 0 and {type_filter} and {entity_filter}"
        ),
        "$top": 50000,
        "$orderby": f"{id_field} asc",
    })
    print(f"  Found {len(records)} Run Specialty / USA {entity}")

    for rec in records:
        rid   = rec[id_field]
        rname = rec.get(name_field, "")
        owner = rec.get("_ownerid_value", "")
        raw_state = rec.get(state_field) or ""

        # Skip if owned by Brandon or Bill
        if owner in SKIP_OWNERS:
            totals["skipped_owner"] += 1
            continue

        if not raw_state.strip():
            totals["skipped_no_state"] += 1
            print(f"  SKIP (no state): {rname}")
            continue

        state = normalize_state(raw_state)

        region = REGION_MAP.get(state)
        if not region:
            totals["skipped_no_region"] += 1
            print(f"  SKIP (unmapped state '{state}'): {rname}")
            continue

        new_owner_id = region_owner[region]

        # Already correct owner
        if owner == new_owner_id:
            continue

        print(f"  {'[PREVIEW] ' if PREVIEW else ''}Assign {rname} ({state} → {region}) to {new_owner_id}")

        if not PREVIEW:
            last_err = None
            for attempt in range(3):
                try:
                    crm_patch(entity, rid, {
                        "ownerid@odata.bind": f"/systemusers({new_owner_id})"
                    })
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            if last_err:
                totals["errors"] += 1
                print(f"  ERROR: {rname} — {last_err}")
            else:
                totals["updated"] += 1

print(f"\n=== Summary ===")
print(f"  Updated:              {totals['updated']}")
print(f"  Skipped (owner):      {totals['skipped_owner']} (Brandon/Bill)")
print(f"  Skipped (no state):   {totals['skipped_no_state']}")
print(f"  Skipped (no region):  {totals['skipped_no_region']}")
print(f"  Errors:               {totals['errors']}")
if PREVIEW:
    print("\n[PREVIEW MODE — no changes written. Run without --preview to apply.]")
