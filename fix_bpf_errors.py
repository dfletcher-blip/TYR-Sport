"""
Agent: Fix validation errors in the "Lead to Opportunity Sales Process" BPF.
Parses the clientdata JSON and removes steps referencing invalid Lead fields.
"""
import os, re, json, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

_token = {"value": None, "expires": 0}

def get_headers():
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def remove_invalid_steps(obj, invalid_fields, removed):
    """Recursively walk JSON and remove list items that reference invalid fields."""
    if isinstance(obj, list):
        cleaned = []
        for item in obj:
            if isinstance(item, dict):
                field = (item.get("dataFieldName") or item.get("attributeName") or "").lower().strip()
                if field and field in invalid_fields:
                    removed.append(field)
                    continue  # drop this step
            cleaned.append(remove_invalid_steps(item, invalid_fields, removed))
        return cleaned
    elif isinstance(obj, dict):
        return {k: remove_invalid_steps(v, invalid_fields, removed) for k, v in obj.items()}
    return obj

# --- Step 1: Find BPF ---
print("Step 1: Finding BPF...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,clientdata",
        "$filter": "category eq 4 and contains(name,'Lead to Opportunity')",
        "$top": 5,
    },
    timeout=30,
)
if not resp.ok:
    print(f"FAILED: {resp.status_code} {resp.text[:300]}")
    exit(1)

bpfs = resp.json().get("value", [])
if not bpfs:
    print("BPF not found.")
    exit(1)

bpf = bpfs[0]
bpf_id = bpf["workflowid"]
clientdata = bpf.get("clientdata") or ""
print(f"  Found: {bpf['name']} (ID: {bpf_id})")
print(f"  Definition length: {len(clientdata)} chars\n")

# --- Step 2: Get valid Lead fields ---
print("Step 2: Fetching valid Lead entity fields...")
resp_meta = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='lead')/Attributes",
    headers=get_headers(),
    params={"$select": "LogicalName", "$top": 500},
    timeout=30,
)
valid_fields = set()
if resp_meta.ok:
    for attr in resp_meta.json().get("value", []):
        valid_fields.add(attr["LogicalName"].lower())
print(f"  {len(valid_fields)} valid Lead fields loaded\n")

# --- Step 3: Find all field references in BPF ---
field_refs = set(
    f.lower().strip()
    for f in re.findall(
        r'"(?:dataFieldName|attributeName)"\s*:\s*"([^"]+)"',
        clientdata, re.IGNORECASE
    )
)
invalid_fields = {f for f in field_refs if f and f != "null" and f not in valid_fields}
print(f"Step 3: Found {len(field_refs)} field refs, {len(invalid_fields)} invalid:")
for f in sorted(invalid_fields):
    print(f"  - {f}")
print()

if not invalid_fields:
    print("No invalid fields found — BPF errors may have a different cause.")
    exit(0)

# --- Step 4: Parse JSON and remove invalid steps ---
print("Step 4: Parsing and fixing BPF definition...")
try:
    data = json.loads(clientdata)
except json.JSONDecodeError as e:
    print(f"  Cannot parse clientdata as JSON: {e}")
    print("  First 500 chars:", clientdata[:500])
    exit(1)

removed = []
fixed_data = remove_invalid_steps(data, invalid_fields, removed)
print(f"  Removed {len(removed)} invalid step(s): {removed}\n")

if not removed:
    print("  No steps were removed — the field refs may be in a different JSON structure.")
    print("  Printing relevant excerpt:")
    for f in sorted(invalid_fields):
        idx = clientdata.lower().find(f'"{f}"')
        if idx >= 0:
            print(f"  [{f}]: ...{clientdata[max(0,idx-100):idx+150]}...")
    exit(0)

# --- Step 5: Deactivate BPF ---
print("Step 5: Deactivating BPF...")
deactivate = requests.patch(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
    headers={**get_headers(), "If-Match": "*"},
    json={"statecode": 0, "statuscode": 1},
    timeout=30,
)
if deactivate.ok or deactivate.status_code == 204:
    print("  Deactivated.\n")
else:
    print(f"  FAILED to deactivate: {deactivate.status_code} {deactivate.text[:200]}")
    exit(1)

time.sleep(2)

# --- Step 6: Patch clientdata ---
print("Step 6: Saving fixed definition...")
fixed_json = json.dumps(fixed_data)
patch = requests.patch(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
    headers={**get_headers(), "If-Match": "*"},
    json={"clientdata": fixed_json},
    timeout=30,
)
if patch.ok or patch.status_code == 204:
    print("  Definition saved.\n")
else:
    print(f"  FAILED to patch: {patch.status_code} {patch.text[:300]}")
    exit(1)

time.sleep(2)

# --- Step 7: Reactivate BPF ---
print("Step 7: Reactivating BPF...")
activate = requests.patch(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
    headers={**get_headers(), "If-Match": "*"},
    json={"statecode": 1, "statuscode": 2},
    timeout=30,
)
if activate.ok or activate.status_code == 204:
    print("  SUCCESS — BPF reactivated with fixed definition.")
    print("  Open the BPF editor in CRM and click Validate to confirm.")
else:
    print(f"  FAILED to reactivate: {activate.status_code} {activate.text[:300]}")
    print("  The BPF is currently INACTIVE — manually reactivate it in CRM.")
