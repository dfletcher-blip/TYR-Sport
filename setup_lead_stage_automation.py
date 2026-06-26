"""
Create two Dynamics 365 workflows that update a field on the lead record:

  1. "TYR - Lead: Activity Logged → Contacting"
     Trigger: any activity (email, call, task) created regarding a lead
     Action:  set the lead's status field to Contacting

  2. "TYR - Lead: Email Reply Received → Engaged"
     Trigger: inbound email (directioncode = Incoming) regarding a lead
     Action:  set the lead's status field to Engaged

Reads the lead's statuscode optionset to find the correct integer values
for Contacting and Engaged before building the workflows.

Safe to re-run — skips workflows that already exist.
"""
import os, uuid, requests, time, json
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
        "OData-Version":   "4.0",
        "Accept":          "application/json",
        "Content-Type":    "application/json",
    }


# ── Step 1: Find the statuscode options for Lead ───────────────────────────────
print("Step 1: Reading lead statuscode options...")
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='lead')"
    f"/Attributes(LogicalName='statuscode')/Microsoft.Dynamics.CRM.StatusAttributeMetadata"
    f"?$select=LogicalName&$expand=OptionSet",
    headers=get_headers(),
    timeout=30,
)
r.raise_for_status()
options = r.json().get("OptionSet", {}).get("Options", [])
print(f"  Found {len(options)} status options:")
label_to_value = {}
for o in options:
    label = (o.get("Label", {}).get("UserLocalizedLabel") or {}).get("Label", "")
    value = o.get("Value")
    print(f"    [{value}] {label}")
    if label:
        label_to_value[label.lower()] = value

contacting_value = label_to_value.get("contacting")
engaged_value    = label_to_value.get("engaged")

if contacting_value is None or engaged_value is None:
    print()
    print("  'Contacting' or 'Engaged' not found in statuscode options.")
    print("  These values need to be added to the lead statuscode field first.")
    print()
    print("  To add them in Dynamics 365:")
    print("    Settings → Customizations → Customize the System")
    print("    → Entities → Lead → Fields → statuscode")
    print("    → Add option 'Contacting' and 'Engaged' under Status Reason")
    print("    → Publish")
    print()
    print("  Then re-run this script.")
    exit(1)

print(f"\n  Contacting = {contacting_value}")
print(f"  Engaged    = {engaged_value}\n")


# ── Step 2: Check if workflows already exist ───────────────────────────────────
def workflow_exists(name):
    r = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows",
        headers=get_headers(),
        params={
            "$select": "workflowid,name",
            "$filter": f"name eq '{name}'",
            "$top": 1,
        },
        timeout=30,
    )
    return bool(r.json().get("value"))


# ── Step 3: Create + activate a workflow ───────────────────────────────────────
def create_and_activate(name, description, primary_entity, statuscode_value):
    """
    Creates a real-time workflow on primary_entity that updates statuscode
    on the regarding lead record.
    """
    wf_id = str(uuid.uuid4())

    xaml = f"""<Activity
  x:Class="XrmWorkflow.{uuid.uuid4().hex}"
  xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
  xmlns:mxs="clr-namespace:Microsoft.Xrm.Sdk;assembly=Microsoft.Xrm.Sdk"
  xmlns:mxa="clr-namespace:Microsoft.Xrm.Sdk.Workflow.Activities;assembly=Microsoft.Xrm.Sdk.Workflow"
  xmlns:mxwa="clr-namespace:Microsoft.Crm.Workflow.Activities;assembly=Microsoft.Crm.Workflow"
  xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <mxa:Workflow>
    <mxwa:UpdateEntityStep
      EntityId="{{Binding Path=InputParameters[regardingobjectid]}}"
      EntityName="lead">
      <mxwa:UpdateEntityStep.UpdateAttributes>
        <mxs:AttributeCollection>
          <mxs:KeyValuePairOfstringobject>
            <mxs:key>statuscode</mxs:key>
            <mxs:value x:TypeArguments="x:Int32">{statuscode_value}</mxs:value>
          </mxs:KeyValuePairOfstringobject>
        </mxs:AttributeCollection>
      </mxwa:UpdateEntityStep.UpdateAttributes>
    </mxwa:UpdateEntityStep>
  </mxa:Workflow>
</Activity>"""

    payload = {
        "workflowid":      wf_id,
        "name":            name,
        "description":     description,
        "category":        0,
        "mode":            1,        # Real-time
        "scope":           4,        # Organization
        "ondemand":        False,
        "triggeroncreate": True,
        "primaryentity":   primary_entity,
        "xaml":            xaml,
        "statecode":       0,
        "statuscode":      1,
    }
    r = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows",
        headers=get_headers(),
        json=payload,
        timeout=30,
    )
    if r.status_code not in (201, 204):
        return None, f"{r.status_code}: {r.text[:400]}"

    created_id = r.headers.get("OData-EntityId", "").split("(")[-1].rstrip(")")
    if not created_id:
        created_id = wf_id

    time.sleep(2)

    # Activate
    ra = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/SetState",
        headers=get_headers(),
        json={
            "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": created_id},
            "State":  {"Value": 1},
            "Status": {"Value": 2},
        },
        timeout=30,
    )
    if not (ra.ok or ra.status_code == 204):
        return created_id, f"Created but activation failed: {ra.status_code}: {ra.text[:200]}"

    return created_id, None


# ── Workflow 1: Activity logged → Contacting ───────────────────────────────────
WF1 = "TYR - Lead: Activity Logged → Contacting"
print(f"Creating: {WF1}")
if workflow_exists(WF1):
    print("  Already exists — skipping.\n")
else:
    wid, err = create_and_activate(
        name=WF1,
        description="When any activity is created regarding a lead, set lead status to Contacting.",
        primary_entity="activitypointer",
        statuscode_value=contacting_value,
    )
    if err:
        print(f"  ERROR: {err}\n")
    else:
        print(f"  Created & activated ({wid})\n")


# ── Workflow 2: Inbound email → Engaged ───────────────────────────────────────
WF2 = "TYR - Lead: Email Reply Received → Engaged"
print(f"Creating: {WF2}")
if workflow_exists(WF2):
    print("  Already exists — skipping.\n")
else:
    wid, err = create_and_activate(
        name=WF2,
        description="When an inbound email is created regarding a lead, set lead status to Engaged.",
        primary_entity="email",
        statuscode_value=engaged_value,
    )
    if err:
        print(f"  ERROR: {err}\n")
    else:
        print(f"  Created & activated ({wid})\n")


print("=" * 60)
print("Done.")
print()
print("If workflows errored, build them in Power Automate instead:")
print()
print("FLOW 1 — Activity Logged → Contacting")
print("  Trigger : When a row is added → Table: Activities")
print("  Condition: Regarding Object Type = lead")
print(f"  Action  : Update a row → Table: Leads")
print(f"            Status Reason = {contacting_value} (Contacting)")
print()
print("FLOW 2 — Email Reply → Engaged")
print("  Trigger : When a row is added → Table: Emails")
print("  Condition: Direction = Incoming AND Regarding Object Type = lead")
print(f"  Action  : Update a row → Table: Leads")
print(f"            Status Reason = {engaged_value} (Engaged)")
print("=" * 60)
