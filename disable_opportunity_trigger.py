"""
Agent: Find and disable the workflow/flow that auto-creates opportunities
when an Account is created in Dynamics 365.
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

CATEGORY_NAMES = {
    0: "Classic Workflow",
    1: "Dialog",
    2: "Business Rule",
    3: "Action",
    4: "Business Process Flow",
    5: "Power Automate Flow",
}

# Step 1: Find all active workflows/flows on Account entity
print("Searching for active workflows triggered on Account creation...\n")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/workflows",
    headers=get_headers(),
    params={
        "$select": "workflowid,name,category,statecode,statuscode,description,triggeroncreate",
        "$filter": "primaryentity eq 'account' and statecode eq 1 and triggeroncreate eq true",
        "$top": 100,
    },
    timeout=30,
)

if not resp.ok:
    print(f"FAILED: {resp.status_code} {resp.text[:300]}")
    exit(1)

workflows = resp.json().get("value", [])
print(f"Found {len(workflows)} active workflow(s) that trigger on Account create:\n")

for wf in workflows:
    cat = CATEGORY_NAMES.get(wf.get("category"), f"Category {wf.get('category')}")
    print(f"  Name:        {wf.get('name')}")
    print(f"  Type:        {cat}")
    print(f"  ID:          {wf.get('workflowid')}")
    print(f"  Description: {(wf.get('description') or 'none')[:120]}")
    print()

# Step 2: Identify the one that creates opportunities
opportunity_workflows = [
    wf for wf in workflows
    if "opportunit" in (wf.get("name") or "").lower()
    or "opportunit" in (wf.get("description") or "").lower()
]

if not opportunity_workflows:
    print("Could not auto-identify the opportunity workflow by name/description.")
    print("Listed all Account-create workflows above — check which one creates opportunities.")
    print("To disable one manually, run:")
    print('  python disable_workflow.py <workflowid>')
    exit(0)

# Step 3: Disable it
for wf in opportunity_workflows:
    wf_id = wf["workflowid"]
    wf_name = wf["name"]
    print(f"Disabling: {wf_name} ({wf_id})...")

    # Must deactivate via SetState action
    resp2 = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows({wf_id})/Microsoft.Dynamics.CRM.SetState",
        headers=get_headers(),
        json={"State": 0, "Status": 1},
        timeout=30,
    )

    if resp2.ok or resp2.status_code == 204:
        print(f"  SUCCESS — '{wf_name}' is now disabled.")
    else:
        # Fallback: PATCH statecode directly
        resp3 = requests.patch(
            f"{DYNAMICS_URL}/api/data/v9.2/workflows({wf_id})",
            headers={**get_headers(), "If-Match": "*"},
            json={"statecode": 0, "statuscode": 1},
            timeout=30,
        )
        if resp3.ok or resp3.status_code == 204:
            print(f"  SUCCESS — '{wf_name}' is now disabled.")
        else:
            print(f"  FAILED: {resp3.status_code} {resp3.text[:200]}")
            print(f"  Try disabling manually in Settings > Processes in CRM.")
