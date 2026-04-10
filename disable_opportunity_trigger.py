"""
Agent: Find the workflow/plugin that auto-creates opportunities on Account create.
Searches workflows, Power Automate flows, and plugin steps.
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

CATEGORY_NAMES = {0: "Classic Workflow", 1: "Dialog", 2: "Business Rule",
                  3: "Action", 4: "Business Process Flow", 5: "Power Automate Flow"}

def search(label, url, params):
    print(f"--- {label} ---")
    resp = requests.get(url, headers=get_headers(), params=params, timeout=30)
    if not resp.ok:
        print(f"  FAILED {resp.status_code}: {resp.text[:200]}\n")
        return []
    results = resp.json().get("value", [])
    print(f"  Found {len(results)} result(s)")
    return results

# 1. All active workflows/flows with "opportunity" in name (any entity)
opp_workflows = search(
    "Workflows with 'opportunity' in name",
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    {
        "$select": "workflowid,name,category,statecode,primaryentity,description,triggeroncreate",
        "$filter": "statecode eq 1 and contains(name,'pportunit')",
        "$top": 50,
    },
)
for wf in opp_workflows:
    cat = CATEGORY_NAMES.get(wf.get("category"), f"cat{wf.get('category')}")
    print(f"  [{cat}] {wf['name']} (entity: {wf.get('primaryentity')}, triggeroncreate: {wf.get('triggeroncreate')})")
    print(f"    ID: {wf['workflowid']}")
print()

# 2. Active Power Automate flows on Account (category=5)
pa_flows = search(
    "Power Automate Flows on Account (category=5)",
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    {
        "$select": "workflowid,name,category,statecode,description",
        "$filter": "primaryentity eq 'account' and statecode eq 1 and category eq 5",
        "$top": 50,
    },
)
for wf in pa_flows:
    print(f"  {wf['name']} — ID: {wf['workflowid']}")
print()

# 3. Plugin steps with "opportunity" in name
opp_plugins = search(
    "Plugin steps with 'opportunity' in name",
    f"{DYNAMICS_URL}/api/data/v9.2/sdkmessageprocessingsteps",
    {
        "$select": "sdkmessageprocessingstepid,name,statecode",
        "$filter": "contains(name,'pportunit')",
        "$top": 50,
    },
)
for s in opp_plugins:
    print(f"  [{s.get('statecode')}] {s['name']} — ID: {s['sdkmessageprocessingstepid']}")
print()

# 4. All active plugin steps that fire on Create and mention account
acct_create_plugins = search(
    "Active plugin steps: Account + Create",
    f"{DYNAMICS_URL}/api/data/v9.2/sdkmessageprocessingsteps",
    {
        "$select": "sdkmessageprocessingstepid,name,statecode",
        "$filter": "statecode eq 0 and contains(name,'ccount') and contains(name,'reate')",
        "$top": 50,
    },
)
for s in acct_create_plugins:
    print(f"  {s['name']} — ID: {s['sdkmessageprocessingstepid']}")
print()

print("Review the results above and share with the agent to identify and disable the correct trigger.")
