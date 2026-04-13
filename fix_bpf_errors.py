"""
Agent: Find and fix validation errors in the "Lead to Opportunity Sales Process" BPF.
Errors typically mean a stage's data step references a deleted/renamed field.
"""
import os, re, requests, time
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

# Step 1: Find the BPF
print("Step 1: Finding 'Lead to Opportunity Sales Process' BPF...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,category,statecode,clientdata,xaml",
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
    print("BPF not found. Listing all active BPFs...")
    resp2 = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows",
        headers=get_headers(),
        params={
            "$select": "workflowid,name,statecode",
            "$filter": "category eq 4 and statecode eq 1",
            "$top": 50,
        },
        timeout=30,
    )
    for wf in resp2.json().get("value", []):
        print(f"  {wf['name']} — {wf['workflowid']}")
    exit(0)

bpf = bpfs[0]
bpf_id = bpf["workflowid"]
print(f"  Found: {bpf['name']} (ID: {bpf_id})\n")

# Step 2: Get Lead entity fields (valid fields we can reference)
print("Step 2: Fetching valid Lead entity fields...")
resp_meta = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='lead')/Attributes",
    headers=get_headers(),
    params={"$select": "LogicalName,DisplayName,AttributeType", "$top": 500},
    timeout=30,
)
valid_fields = set()
if resp_meta.ok:
    for attr in resp_meta.json().get("value", []):
        valid_fields.add(attr["LogicalName"].lower())
print(f"  Found {len(valid_fields)} valid Lead fields\n")

# Step 3: Get process stages for this BPF
print("Step 3: Getting BPF stages and their steps...")
resp_stages = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    params={
        "$select": "processstageid,stagename,stagecategory,rank",
        "$filter": f"processid eq {bpf_id}",
        "$orderby": "rank asc",
        "$top": 20,
    },
    timeout=30,
)
if not resp_stages.ok:
    print(f"FAILED to get stages: {resp_stages.status_code}")
else:
    stages = resp_stages.json().get("value", [])
    print(f"  Found {len(stages)} stages:")
    for s in stages:
        print(f"    [{s.get('rank')}] {s['stagename']} — ID: {s['processstageid']}")
print()

# Step 4: Inspect the clientdata/xaml for invalid field references
print("Step 4: Inspecting BPF definition for invalid field references...")
clientdata = bpf.get("clientdata") or bpf.get("xaml") or ""
if not clientdata:
    print("  No clientdata/xaml found on this BPF record.")
    print("  The BPF definition may be stored differently in this version.")
    exit(0)

print(f"  Definition length: {len(clientdata)} chars")

# Find all field references in the BPF definition
# BPF clientdata typically has AttributeName or attributeName references
field_refs = re.findall(r'[Aa]ttribute[Nn]ame["\s:=]+["\']?([a-z_0-9]+)["\']?', clientdata, re.IGNORECASE)
field_refs += re.findall(r'datafieldname["\s:=]+["\']?([a-z_0-9]+)["\']?', clientdata, re.IGNORECASE)
field_refs = list(set(f.lower() for f in field_refs))

print(f"\n  Field references found in BPF definition: {len(field_refs)}")
invalid_fields = [f for f in field_refs if f not in valid_fields]
print(f"  Invalid field references (not on Lead entity): {len(invalid_fields)}")
for f in invalid_fields:
    print(f"    - {f}")

if invalid_fields:
    print("\nStep 5: Removing invalid field references from BPF definition...")
    fixed_data = clientdata
    for field in invalid_fields:
        # Remove the step/DataField block referencing this field
        # Pattern varies by BPF XML format
        patterns = [
            rf'<DataField[^>]*[Aa]ttribute[Nn]ame[^>]*{re.escape(field)}[^>]*/?>',
            rf'<mxCell[^>]*{re.escape(field)}[^>]*/?>',
        ]
        for pat in patterns:
            fixed_data = re.sub(pat, '', fixed_data, flags=re.IGNORECASE)

    if fixed_data != clientdata:
        print("  Patching BPF with fixed definition...")
        patch = requests.patch(
            f"{DYNAMICS_URL}/api/data/v9.2/workflows({bpf_id})",
            headers={**get_headers(), "If-Match": "*"},
            json={"clientdata": fixed_data},
            timeout=30,
        )
        if patch.ok or patch.status_code == 204:
            print("  SUCCESS — BPF updated. Try validating again in CRM.")
        else:
            print(f"  FAILED to patch: {patch.status_code} {patch.text[:300]}")
    else:
        print("  Could not auto-remove fields — printing raw definition for manual review:")
        print(clientdata[:3000])
else:
    print("\n  No invalid fields found via field name scan.")
    print("  Printing first 2000 chars of definition for manual inspection:")
    print(clientdata[:2000])
