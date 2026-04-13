"""
Fix BPF validation errors using direct JSON string manipulation.
Removes complete step objects referencing invalid fields, then deactivates/reactivates.
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

def find_object_end(s, start):
    """Find closing brace of a JSON object starting at `start`."""
    depth, in_string, escape = 0, False, False
    for i in range(start, len(s)):
        c = s[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
    return -1

def remove_steps_with_field(json_str, field_name):
    """Remove all JSON objects containing attributeName == field_name."""
    pattern = f'"attributeName":"{field_name}"'
    count = 0
    result = json_str
    while True:
        idx = result.find(pattern)
        if idx == -1:
            break
        obj_start = result.rfind('{', 0, idx)
        if obj_start == -1:
            break
        obj_end = find_object_end(result, obj_start)
        if obj_end == -1:
            break
        before = result[:obj_start].rstrip()
        after = result[obj_end + 1:].lstrip()
        if before.endswith(','):
            before = before[:-1]
        elif after.startswith(','):
            after = after[1:]
        result = before + after
        count += 1
    return result, count

# --- Fetch BPF ---
print("Fetching BPF...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,clientdata,statecode,ismanaged",
        "$filter": "category eq 4 and contains(name,'Lead to Opportunity')",
        "$top": 5,
    },
    timeout=30,
)
bpf = resp.json().get("value", [{}])[0]
bpf_id = bpf.get("workflowid")
clientdata = bpf.get("clientdata") or ""
print(f"  Name:      {bpf.get('name')}")
print(f"  ID:        {bpf_id}")
print(f"  Managed:   {bpf.get('ismanaged')}")
print(f"  Statecode: {bpf.get('statecode')}")
print(f"  Def size:  {len(clientdata)} chars\n")

# --- Valid Lead fields (paginated) ---
print("Fetching all Lead fields...")
valid_fields = set()
url = f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='lead')/Attributes"
params = {"$select": "LogicalName", "$top": 500}
while url:
    r = requests.get(url, headers=get_headers(), params=params, timeout=30)
    for a in r.json().get("value", []):
        valid_fields.add(a["LogicalName"].lower())
    url = r.json().get("@odata.nextLink")
    params = None
print(f"  {len(valid_fields)} Lead fields loaded\n")

# --- Find invalid refs ---
field_refs = set(
    f.lower().strip()
    for f in re.findall(r'"attributeName"\s*:\s*"([^"]+)"', clientdata)
)
invalid_fields = {f for f in field_refs if f and f != "null" and f not in valid_fields}
print(f"Invalid field references to remove ({len(invalid_fields)}):")
for f in sorted(invalid_fields):
    print(f"  - {f}")
print()

if not invalid_fields:
    print("No invalid fields found.")
    exit(0)

# --- Remove invalid steps via string manipulation ---
print("Removing invalid steps from definition...")
fixed = clientdata
total_removed = 0
for field in sorted(invalid_fields):
    fixed, count = remove_steps_with_field(fixed, field)
    if count:
        print(f"  Removed {count} step(s) for field: {field}")
        total_removed += count

print(f"\nTotal steps removed: {total_removed}")

# Verify fixed JSON is valid
try:
    json.loads(fixed)
    print("  JSON is valid after edits.\n")
except json.JSONDecodeError as e:
    print(f"  ERROR: JSON invalid after edits: {e}")
    print("  Aborting — no changes made.")
    exit(1)

if total_removed == 0:
    print("No steps were removed — definition structure may differ.")
    print("Showing attributeName contexts in definition:")
    for m in re.finditer(r'.{0,80}"attributeName"\s*:\s*"([^"]+)".{0,80}', clientdata):
        if m.group(1).lower() in invalid_fields:
            print(f"  ...{m.group(0)}...")
    exit(0)

# --- Deactivate ---
print("Deactivating BPF...")
r = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/SetState",
    headers=get_headers(),
    json={"EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": bpf_id}, "State": {"Value": 0}, "Status": {"Value": 1}},
    timeout=30,
)
if not (r.ok or r.status_code == 204):
    # Fallback to PATCH
    r = requests.patch(f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})", headers={**get_headers(), "If-Match": "*"}, json={"statecode": 0, "statuscode": 1}, timeout=30)
print(f"  Deactivate response: {r.status_code}")
time.sleep(3)

# --- Patch clientdata ---
print("Patching definition...")
r = requests.patch(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
    headers={**get_headers(), "If-Match": "*"},
    json={"clientdata": fixed},
    timeout=30,
)
print(f"  Patch response: {r.status_code}")
if not (r.ok or r.status_code == 204):
    print(f"  ERROR: {r.text[:300]}")
    exit(1)
time.sleep(3)

# --- Reactivate ---
print("Reactivating BPF...")
r = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/SetState",
    headers=get_headers(),
    json={"EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": bpf_id}, "State": {"Value": 1}, "Status": {"Value": 2}},
    timeout=30,
)
if not (r.ok or r.status_code == 204):
    r = requests.patch(f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})", headers={**get_headers(), "If-Match": "*"}, json={"statecode": 1, "statuscode": 2}, timeout=30)
print(f"  Activate response: {r.status_code}\n")

if r.ok or r.status_code == 204:
    print("SUCCESS — BPF updated and reactivated.")
    print("Refresh the BPF editor and click Validate to confirm.")
else:
    print(f"Reactivation failed: {r.text[:300]}")
    print("BPF is currently inactive — reactivate manually in CRM.")
