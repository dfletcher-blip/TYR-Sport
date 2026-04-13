"""
Diagnostic: find the correct entities and fields for BPF migration.
"""
import os, requests, time
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

OLD_BPF_ID = "919e14d1-6489-4852-abd0-a63a6ecaac5d"
NEW_BPF_ID = "c4096776-49c9-40e8-a51b-0569d1bfef45"

# 1. Get ALL processstages (no filter) - first 20
print("=== All processstages (sample) ===")
r = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    params={"$select": "processstageid,stagename,_processid_value", "$top": 20},
    timeout=30)
for s in r.json().get("value", []):
    print(f"  {s['stagename']} — stage: {s['processstageid']} — bpf: {s.get('_processid_value')}")
print()

# 2. Try leadtoopportunitysalesprocess BPF instance entity
print("=== BPF instance entity: leadtoopportunitysalesprocess ===")
r2 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/leadtoopportunitysalesprocesses",
    headers=get_headers(),
    params={"$select": "businessprocessflowinstanceid,bpf_leadid,activestageid,_activestageid_value", "$top": 5},
    timeout=30)
if r2.ok:
    instances = r2.json().get("value", [])
    print(f"  Found {len(instances)} instances (showing up to 5):")
    for inst in instances:
        print(f"  Lead: {inst.get('_bpf_leadid_value')} — Stage: {inst.get('_activestageid_value')}")
else:
    print(f"  FAILED {r2.status_code}: {r2.text[:200]}")
print()

# 3. Check a sample lead's BPF fields
print("=== Sample lead BPF fields ===")
r3 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/leads",
    headers=get_headers(),
    params={"$select": "leadid,fullname,processid,stageid,_processid_value,_stageid_value", "$top": 3, "$filter": "statecode eq 0"},
    timeout=30)
for lead in r3.json().get("value", []):
    print(f"  {lead.get('fullname')}")
    print(f"    processid:        {lead.get('processid')}")
    print(f"    _processid_value: {lead.get('_processid_value')}")
    print(f"    stageid:          {lead.get('stageid')}")
    print(f"    _stageid_value:   {lead.get('_stageid_value')}")
print()

# 4. Count leads per process
print("=== Lead count on old BPF ===")
r4 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/leads",
    headers=get_headers(),
    params={"$select": "leadid", "$filter": f"_processid_value eq {OLD_BPF_ID} and statecode eq 0", "$count": "true", "$top": 1},
    timeout=30)
print(f"  Leads with _processid_value = old BPF: {r4.json().get('@odata.count', 'unknown')}")

r5 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/leads",
    headers=get_headers(),
    params={"$select": "leadid", "$filter": "processid ne null and statecode eq 0", "$count": "true", "$top": 1},
    timeout=30)
print(f"  Leads with any processid set: {r5.json().get('@odata.count', 'unknown')}")
