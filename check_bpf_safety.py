"""
Safety check before applying BPF fix.
Shows exactly what will be removed and scans for workflows that reference those fields.
Does NOT make any changes.
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

def find_step_context(obj, invalid_fields, results=None, path="root"):
    """Find all steps referencing invalid fields, with context."""
    if results is None:
        results = []
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            find_step_context(item, invalid_fields, results, f"{path}[{i}]")
    elif isinstance(obj, dict):
        field = (obj.get("dataFieldName") or obj.get("attributeName") or "").lower().strip()
        if field and field in invalid_fields:
            results.append({
                "field": field,
                "path": path,
                "label": obj.get("displayName") or obj.get("label") or obj.get("name") or "(no label)",
                "required": obj.get("requiredLevel") or obj.get("isRequired") or False,
            })
        for k, v in obj.items():
            find_step_context(v, invalid_fields, results, f"{path}.{k}")
    return results

# --- Fetch BPF ---
print("=" * 60)
print("SAFETY CHECK — no changes will be made")
print("=" * 60)
print()

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
bpf = resp.json().get("value", [{}])[0]
bpf_id = bpf.get("workflowid")
clientdata = bpf.get("clientdata") or ""
print(f"BPF: {bpf.get('name')} ({bpf_id})\n")

# --- Valid Lead fields ---
resp_meta = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='lead')/Attributes",
    headers=get_headers(),
    params={"$select": "LogicalName", "$top": 500},
    timeout=30,
)
valid_fields = {a["LogicalName"].lower() for a in resp_meta.json().get("value", [])}

# --- Find invalid refs ---
field_refs = set(
    f.lower().strip()
    for f in re.findall(r'"(?:dataFieldName|attributeName)"\s*:\s*"([^"]+)"', clientdata, re.IGNORECASE)
)
invalid_fields = {f for f in field_refs if f and f != "null" and f not in valid_fields}

# --- Show what will be removed ---
print("STEPS THAT WILL BE REMOVED:")
print("-" * 40)
try:
    data = json.loads(clientdata)
    hits = find_step_context(data, invalid_fields)
    if hits:
        for h in hits:
            print(f"  Field:    {h['field']}")
            print(f"  Label:    {h['label']}")
            print(f"  Required: {h['required']}")
            print(f"  Path:     {h['path']}")
            print()
    else:
        print("  (Steps not found in expected structure — see raw refs below)")
        for f in sorted(invalid_fields):
            print(f"  - {f}")
except Exception as e:
    print(f"  Could not parse: {e}")
print()

# --- Scan all active workflows for these field names ---
print("SCANNING ACTIVE WORKFLOWS FOR REFERENCES TO THESE FIELDS...")
print("-" * 40)
resp_wf = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,category,primaryentity,xaml,clientdata",
        "$filter": "statecode eq 1 and primaryentity eq 'lead'",
        "$top": 100,
    },
    timeout=30,
)
workflows = resp_wf.json().get("value", [])
print(f"Checking {len(workflows)} active Lead workflows...\n")

affected = []
for wf in workflows:
    definition = (wf.get("xaml") or "") + (wf.get("clientdata") or "")
    matched = [f for f in invalid_fields if f in definition.lower()]
    if matched:
        affected.append((wf["name"], matched))

if affected:
    print("  WARNING — these workflows reference the fields being removed:")
    for name, fields in affected:
        print(f"  - {name}: {fields}")
else:
    print("  CLEAR — no active Lead workflows reference these fields.")
print()

# --- Summary ---
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Fields to remove: {sorted(invalid_fields)}")
print(f"  Workflows at risk: {len(affected)}")
print()
if not affected:
    print("  SAFE TO PROCEED — run python fix_bpf_errors.py to apply.")
else:
    print("  REVIEW WARNINGS above before running fix_bpf_errors.py.")
