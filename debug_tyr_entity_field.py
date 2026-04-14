"""
Diagnostic: find the correct option set name for tyr_tyrentity on Account.
Run this first, then we'll use the name to fix the sync script.
"""
import os, json, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

def get_headers():
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

FIELD = "tyr_tyrentity"

# --- 1. Fetch attribute metadata (all keys) ---
print("=" * 60)
print("1. Raw attribute metadata from Account")
print("=" * 60)
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='account')/Attributes(LogicalName='{FIELD}')",
    headers=get_headers(), timeout=30,
)
print(f"Status: {r.status_code}")
meta = r.json()
for k, v in sorted(meta.items()):
    print(f"  {k}: {v!r}")
print()

# --- 2. $expand=OptionSet via cast navigation ---
print("=" * 60)
print("2. PicklistAttributeMetadata with $expand=OptionSet")
print("=" * 60)
r2 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='account')/Attributes/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
    headers=get_headers(),
    params={"$filter": f"LogicalName eq '{FIELD}'", "$expand": "OptionSet"},
    timeout=30,
)
print(f"Status: {r2.status_code}")
if r2.ok:
    items = r2.json().get("value", [])
    if items:
        attr = items[0]
        os_data = attr.get("OptionSet") or {}
        print(f"  OptionSet keys: {list(os_data.keys())}")
        print(f"  IsGlobal: {os_data.get('IsGlobal')}")
        print(f"  Name: {os_data.get('Name')!r}")
        print(f"  MetadataId: {os_data.get('MetadataId')}")
        # Show first 3 option values
        opts = os_data.get("Options", [])
        print(f"  Options ({len(opts)} total):")
        for o in opts[:5]:
            lbl = ((o.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
            print(f"    {o.get('Value')}: {lbl}")
    else:
        print("  No items returned")
else:
    print(f"  Error: {r2.text[:300]}")
print()

# --- 3. List ALL global option sets with "tyr" in the name ---
print("=" * 60)
print("3. Global option sets matching 'tyr'")
print("=" * 60)
r3 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/GlobalOptionSetDefinitions",
    headers=get_headers(),
    params={"$select": "Name,MetadataId,IsGlobal"},
    timeout=30,
)
print(f"Status: {r3.status_code}")
if r3.ok:
    all_gos = r3.json().get("value", [])
    tyr_gos = [g for g in all_gos if "tyr" in g.get("Name", "").lower()]
    print(f"  Total global option sets: {len(all_gos)}")
    print(f"  TYR global option sets ({len(tyr_gos)}):")
    for g in tyr_gos:
        print(f"    Name: {g['Name']!r}  MetadataId: {g['MetadataId']}")
else:
    print(f"  Error: {r3.text[:300]}")
print()

# --- 4. Check if field exists on Contact ---
print("=" * 60)
print("4. Does tyr_tyrentity exist on Contact?")
print("=" * 60)
r4 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='contact')/Attributes(LogicalName='{FIELD}')",
    headers=get_headers(), timeout=30,
)
print(f"Status: {r4.status_code} ({'exists' if r4.ok else 'not found'})")
if r4.ok:
    m = r4.json()
    print(f"  Type: {m.get('AttributeType')}")
    print(f"  GlobalOptionSetName: {m.get('GlobalOptionSetName')}")
print()
