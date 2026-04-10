"""
Find the Power Automate flow or workflow that creates opportunities on Account create.
Searches all category=5 flows and all classic workflows mentioning account/opportunity.
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

def search(label, params):
    print(f"\n--- {label} ---")
    resp = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows",
        headers=get_headers(),
        params=params,
        timeout=30,
    )
    if not resp.ok:
        print(f"FAILED {resp.status_code}: {resp.text[:200]}")
        return []
    results = resp.json().get("value", [])
    print(f"Found {len(results)} result(s):")
    for wf in results:
        print(f"  Name:    {wf.get('name')}")
        print(f"  ID:      {wf.get('workflowid')}")
        print(f"  Entity:  {wf.get('primaryentity')}")
        print(f"  Category:{wf.get('category')} (0=Workflow,5=PA Flow)")
        print(f"  TriggerOnCreate: {wf.get('triggeroncreate')}")
        print()
    return results

# All active Power Automate flows (category=5)
search("All active Power Automate Flows (category=5)", {
    "$select": "workflowid,name,category,primaryentity,statecode,triggeroncreate,description",
    "$filter": "statecode eq 1 and category eq 5",
    "$top": 100,
})

# All active classic workflows (category=0) - any entity
search("All active Classic Workflows (category=0)", {
    "$select": "workflowid,name,category,primaryentity,statecode,triggeroncreate,description",
    "$filter": "statecode eq 1 and category eq 0",
    "$top": 100,
})

# Workflows on Opportunity entity that trigger on create (might cascade from account)
search("Active workflows on Opportunity entity", {
    "$select": "workflowid,name,category,primaryentity,statecode,triggeroncreate,description",
    "$filter": "primaryentity eq 'opportunity' and statecode eq 1",
    "$top": 50,
})
