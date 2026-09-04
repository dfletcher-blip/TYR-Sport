#!/usr/bin/env python3
"""
Update account owner to Laura Whitehead for accounts where:
  - tyr_tyrtype includes Crossfit, Sport Specialty, or Direct to Consumer
  - address1_stateorprovince is in the western/central states list

Run with --preview to see what would change without writing.
Run without --preview to apply changes.
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get, crm_patch, DYNAMICS_URL

PREVIEW = "--preview" in sys.argv

TARGET_STATES = {
    "AK", "AZ", "AR", "CA", "CO", "HI", "ID", "IL", "IA", "KS",
    "MN", "MO", "MT", "NE", "NV", "NM", "ND", "OK", "OR", "SD",
    "TX", "UT", "WA", "WI", "WY",
}

# Step 1: Find Laura Whitehead's user ID
print("=== Step 1: Find Laura Whitehead ===")
users = crm_get("systemusers", {
    "$select": "systemuserid,fullname",
    "$filter": "contains(fullname,'Laura') and contains(fullname,'Whitehead')",
    "$top": 5,
}).get("value", [])
if not users:
    print("ERROR: Laura Whitehead not found in systemusers."); sys.exit(1)
laura = users[0]
laura_id = laura["systemuserid"]
print(f"Found: {laura['fullname']} — ID: {laura_id}")

# Step 2: Find TYR type option values for the target types
print("\n=== Step 2: Find TYR type option values ===")
try:
    meta = crm_get(
        "EntityDefinitions(LogicalName='account')/Attributes(LogicalName='tyr_tyrtype')"
        "/Microsoft.Dynamics.CRM.MultiSelectPicklistAttributeMetadata"
        "?$select=LogicalName&$expand=OptionSet($select=Options)",
        {},
    )
    options = (meta.get("OptionSet") or {}).get("Options", [])
    target_keywords = ["crossfit", "sport specialty", "sportspecialty", "direct to consumer", "dtc"]
    target_values = []
    for opt in options:
        label = ((opt.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
        if any(kw in label.lower() for kw in target_keywords):
            target_values.append(opt["Value"])
            print(f"  Matched: {label} = {opt['Value']}")
    if not target_values:
        print("  No matching options found. Available options:")
        for opt in options:
            label = ((opt.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
            print(f"    {opt['Value']}: {label}")
        sys.exit(1)
except Exception as e:
    print(f"  Could not fetch metadata: {e}")
    print("  Falling back to string search on tyr_tyrtype formatted values.")
    target_values = None

# Step 3: Fetch all active accounts with state filter
print("\n=== Step 3: Fetch accounts in target states ===")
state_filter = " or ".join(f"address1_stateorprovince eq '{s}'" for s in sorted(TARGET_STATES))
base_prefix = f"{DYNAMICS_URL}/api/data/v9.2/"

accounts = []
page = crm_get("accounts", {
    "$select": "accountid,name,address1_stateorprovince,tyr_tyrtype,_ownerid_value",
    "$filter": f"statecode eq 0 and ({state_filter})",
    "$top": 2000,
    "$orderby": "accountid asc",
})
accounts.extend(page.get("value", []))
next_link = page.get("@odata.nextLink")
while next_link:
    relative = next_link[len(base_prefix):] if next_link.startswith(base_prefix) else next_link
    page = crm_get(relative, {})
    accounts.extend(page.get("value", []))
    next_link = page.get("@odata.nextLink")

print(f"Found {len(accounts)} active accounts in target states")

# Step 4: Filter by TYR type
def matches_tyr_type(acct):
    raw = acct.get("tyr_tyrtype") or ""
    if not raw:
        return False
    if target_values:
        # tyr_tyrtype is stored as comma-separated ints e.g. "935650002,935650012"
        acct_vals = {v.strip() for v in str(raw).split(",")}
        return any(str(tv) in acct_vals for tv in target_values)
    else:
        # Fallback: check formatted value annotation
        formatted = acct.get("tyr_tyrtype@OData.Community.Display.V1.FormattedValue") or ""
        return any(kw in formatted.lower() for kw in ["crossfit", "sport specialty", "direct to consumer"])

to_update = [a for a in accounts if matches_tyr_type(a)]
already_owned = [a for a in to_update if a.get("_ownerid_value") == laura_id]
needs_update = [a for a in to_update if a.get("_ownerid_value") != laura_id]

print(f"\nMatching TYR type: {len(to_update)} accounts")
print(f"  Already owned by Laura: {len(already_owned)}")
print(f"  Need ownership change:  {len(needs_update)}")

if PREVIEW or not needs_update:
    print("\n=== PREVIEW (first 20) ===" if PREVIEW else "\n=== No updates needed ===")
    for a in needs_update[:20]:
        print(f"  {a['name']} | {a.get('address1_stateorprovince')} | tyrtype={a.get('tyr_tyrtype')} | current_owner={a.get('_ownerid_value')}")
    if len(needs_update) > 20:
        print(f"  ... and {len(needs_update) - 20} more")
    if PREVIEW:
        print(f"\nRun without --preview to apply {len(needs_update)} update(s).")
    sys.exit(0)

# Step 5: Apply updates
print(f"\n=== Step 5: Updating {len(needs_update)} accounts ===")
updated, errors = [], []
for a in needs_update:
    try:
        crm_patch("accounts", a["accountid"], {
            "ownerid@odata.bind": f"/systemusers({laura_id})"
        })
        updated.append(a["name"])
        print(f"  OK: {a['name']} ({a.get('address1_stateorprovince')})")
    except Exception as e:
        errors.append({"name": a["name"], "error": str(e)})
        print(f"  ERR: {a['name']} — {e}")

print(f"\nDone: {len(updated)} updated, {len(errors)} errors.")
