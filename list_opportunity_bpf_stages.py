"""
List the stage IDs for the Opportunity Sales Process BPF.
These GUIDs are what you use to filter opportunities by pipeline stage in views.
"""
import os, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

_token: dict = {"value": None, "expires": 0}
def get_headers():
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        "Accept": "application/json", "Content-Type": "application/json",
    }

# Find the Opportunity BPF
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name",
        "$filter": "category eq 4 and statecode eq 1 and primaryentity eq 'opportunity'",
        "$orderby": "name asc",
    },
    timeout=30,
)
bpfs = r.json().get("value", [])
if not bpfs:
    print("No active opportunity BPFs found.")
    exit(1)

for bpf in bpfs:
    print(f"\nBPF: {bpf['name']} ({bpf['workflowid']})")
    print("-" * 70)

    r2 = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/processstages",
        headers=get_headers(),
        params={
            "$select": "processstageid,stagename,stagecategory",
            "$filter": f"_processid_value eq {bpf['workflowid']}",
            "$orderby": "stagecategory asc",
        },
        timeout=30,
    )
    stages = r2.json().get("value", [])
    print(f"  {'Stage Name':<30} {'processstageid'}")
    print(f"  {'-'*28}   {'-'*36}")
    for s in stages:
        print(f"  {s['stagename']:<30} {s['processstageid']}")

print("\nTo filter a view by pipeline stage, use:")
print("  activestageid eq <processstageid>")
print("  (applied via the opportunitysalesprocess related entity in FetchXML)")
