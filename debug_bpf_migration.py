"""
Focused diagnostic: find correct field names on BPF instance entity and stage IDs.
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

# 1. processstages filtered by OLD BPF ID
print("=== processstages for OLD BPF ===")
r = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    params={"$select": "processstageid,stagename", "$filter": f"_processid_value eq {OLD_BPF_ID}", "$top": 20},
    timeout=30)
print(f"  Status: {r.status_code}")
for s in r.json().get("value", []):
    print(f"  {s['stagename']} — {s['processstageid']}")
print()

# 2. processstages filtered by NEW BPF ID
print("=== processstages for NEW BPF ===")
r = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    params={"$select": "processstageid,stagename", "$filter": f"_processid_value eq {NEW_BPF_ID}", "$top": 20},
    timeout=30)
print(f"  Status: {r.status_code}")
for s in r.json().get("value", []):
    print(f"  {s['stagename']} — {s['processstageid']}")
print()

# 3. BPF instance entity - no field filter to see all available fields
print("=== leadtoopportunitysalesprocesses fields ===")
r2 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/leadtoopportunitysalesprocesses",
    headers=get_headers(),
    params={"$top": 2},
    timeout=30)
print(f"  Status: {r2.status_code}")
if r2.ok:
    instances = r2.json().get("value", [])
    if instances:
        print(f"  Fields on instance: {sorted(instances[0].keys())}")
        print(f"  Sample: {instances[0]}")
    else:
        print("  No instances found")
else:
    print(f"  Error: {r2.text[:300]}")
print()

# 4. Sample lead - all fields containing 'process' or 'stage'
print("=== Sample lead process/stage fields ===")
r3 = requests.get(f"{DYNAMICS_URL}/api/data/v9.2/leads",
    headers=get_headers(),
    params={"$top": 1, "$filter": "statecode eq 0"},
    timeout=30)
if r3.ok:
    leads = r3.json().get("value", [])
    if leads:
        lead = leads[0]
        relevant = {k: v for k, v in lead.items() if any(x in k.lower() for x in ['process', 'stage', 'bpf'])}
        print(f"  Lead: {lead.get('fullname')}")
        for k, v in relevant.items():
            print(f"    {k}: {v}")
print()
