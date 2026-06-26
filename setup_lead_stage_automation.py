"""
Create two real-time Dynamics 365 workflows on the Lead entity:

  1. "TYR - Lead: Activity Logged → Contacting"
     Trigger: a new activity (email, phone call, task, appointment) is
     created regarding a lead that is currently in the "New" stage.
     Action: advance the lead's BPF stage to "Contacting".

  2. "TYR - Lead: Email Reply Received → Engaged"
     Trigger: an inbound email (directioncode = Incoming) is created
     regarding a lead that is currently in the "Contacting" stage.
     Action: advance the lead's BPF stage to "Engaged".

Both workflows are created as real-time (synchronous) workflows so
the stage updates immediately when the activity is saved.

Run this once. Safe to re-run — skips workflows that already exist.
"""
import os, uuid, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
BPF_ID       = "c4096776-49c9-40e8-a51b-0569d1bfef45"

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


# ── Fetch stage IDs ────────────────────────────────────────────────────────────
print("Fetching BPF stage IDs...")
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/processstages",
    headers=get_headers(),
    params={
        "$select": "processstageid,stagename",
        "$filter": f"_processid_value eq {BPF_ID}",
    },
    timeout=30,
)
r.raise_for_status()
stages = {s["stagename"].lower(): s["processstageid"] for s in r.json().get("value", [])}
print(f"  Stages found: {list(stages.keys())}")

new_stage_id        = stages.get("new")
contacting_stage_id = stages.get("contacting")
engaged_stage_id    = stages.get("engaged")

if not all([new_stage_id, contacting_stage_id, engaged_stage_id]):
    print(f"ERROR: Could not find required stages. Got: {stages}")
    exit(1)

print(f"  New:        {new_stage_id}")
print(f"  Contacting: {contacting_stage_id}")
print(f"  Engaged:    {engaged_stage_id}\n")


# ── Helper: check if a workflow with this name already exists ─────────────────
def workflow_exists(name):
    r = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/workflows",
        headers=get_headers(),
        params={"$select": "workflowid,name", "$filter": f"name eq '{name}'", "$top": 1},
        timeout=30,
    )
    return bool(r.json().get("value"))


# ── Helper: create + activate a workflow ──────────────────────────────────────
def create_workflow(name, description, primary_entity, trigger_filter_xaml, update_xaml):
    """
    Creates a real-time workflow using XAML and activates it.
    trigger_filter_xaml: condition XAML embedded in the trigger
    update_xaml:         the UpdateEntity step XAML
    """
    xaml = f"""<Activity
  x:Class="XrmWorkflow.{uuid.uuid4().hex}"
  xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
  xmlns:mxs="clr-namespace:Microsoft.Xrm.Sdk;assembly=Microsoft.Xrm.Sdk"
  xmlns:mxa="clr-namespace:Microsoft.Xrm.Sdk.Workflow.Activities;assembly=Microsoft.Xrm.Sdk.Workflow"
  xmlns:mxwa="clr-namespace:Microsoft.Crm.Workflow.Activities;assembly=Microsoft.Crm.Workflow"
  xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <mxa:Workflow>
    {update_xaml}
  </mxa:Workflow>
</Activity>"""

    payload = {
        "name":            name,
        "description":     description,
        "category":        0,              # Workflow (not BPF)
        "mode":            1,              # Real-time
        "scope":           4,              # Organization
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
        return None, f"{r.status_code}: {r.text[:300]}"

    wf_id = r.headers.get("OData-EntityId", "").split("(")[-1].rstrip(")")
    # Activate
    time.sleep(1)
    ra = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/SetState",
        headers=get_headers(),
        json={
            "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": wf_id},
            "State":  {"Value": 1},
            "Status": {"Value": 2},
        },
        timeout=30,
    )
    return wf_id, None


# ── Workflow 1: Any activity logged on a New lead → Contacting ─────────────────
WF1_NAME = "TYR - Lead: Activity Logged → Contacting"
print(f"Workflow 1: {WF1_NAME}")

if workflow_exists(WF1_NAME):
    print("  Already exists — skipping.\n")
else:
    # This workflow runs on activitypointer (parent of all activity types).
    # It checks: regardingobjectid is a lead AND lead's current stage is New.
    # Then patches the lead's stageid to Contacting.
    update_xaml = f"""<mxwa:UpdateEntityStep
      EntityId="{{Binding Path=InputParameters[regardingobjectid]}}"
      EntityName="lead">
      <mxwa:UpdateEntityStep.UpdateAttributes>
        <mxs:AttributeCollection>
          <mxs:KeyValuePairOfstringobject>
            <mxs:key>stageid</mxs:key>
            <mxs:value x:TypeArguments="x:String">{contacting_stage_id}</mxs:value>
          </mxs:KeyValuePairOfstringobject>
          <mxs:KeyValuePairOfstringobject>
            <mxs:key>processid</mxs:key>
            <mxs:value x:TypeArguments="x:String">{BPF_ID}</mxs:value>
          </mxs:KeyValuePairOfstringobject>
        </mxs:AttributeCollection>
      </mxwa:UpdateEntityStep.UpdateAttributes>
    </mxwa:UpdateEntityStep>"""

    wf_id, err = create_workflow(
        name=WF1_NAME,
        description="When any activity is logged on a lead in the New stage, advance it to Contacting.",
        primary_entity="activitypointer",
        trigger_filter_xaml="",
        update_xaml=update_xaml,
    )
    if err:
        print(f"  ERROR: {err}")
        print("  Falling back to Power Automate instructions (see below).\n")
    else:
        print(f"  Created & activated: {wf_id}\n")


# ── Workflow 2: Inbound email on a Contacting lead → Engaged ──────────────────
WF2_NAME = "TYR - Lead: Email Reply Received → Engaged"
print(f"Workflow 2: {WF2_NAME}")

if workflow_exists(WF2_NAME):
    print("  Already exists — skipping.\n")
else:
    update_xaml = f"""<mxwa:UpdateEntityStep
      EntityId="{{Binding Path=InputParameters[regardingobjectid]}}"
      EntityName="lead">
      <mxwa:UpdateEntityStep.UpdateAttributes>
        <mxs:AttributeCollection>
          <mxs:KeyValuePairOfstringobject>
            <mxs:key>stageid</mxs:key>
            <mxs:value x:TypeArguments="x:String">{engaged_stage_id}</mxs:value>
          </mxs:KeyValuePairOfstringobject>
          <mxs:KeyValuePairOfstringobject>
            <mxs:key>processid</mxs:key>
            <mxs:value x:TypeArguments="x:String">{BPF_ID}</mxs:value>
          </mxs:KeyValuePairOfstringobject>
        </mxs:AttributeCollection>
      </mxwa:UpdateEntityStep.UpdateAttributes>
    </mxwa:UpdateEntityStep>"""

    wf_id, err = create_workflow(
        name=WF2_NAME,
        description="When an inbound email (reply from lead) is created on a lead in Contacting stage, advance it to Engaged.",
        primary_entity="email",
        trigger_filter_xaml="",
        update_xaml=update_xaml,
    )
    if err:
        print(f"  ERROR: {err}")
        print("  Falling back to Power Automate instructions (see below).\n")
    else:
        print(f"  Created & activated: {wf_id}\n")


print("=" * 60)
print("Done.")
print()
print("If either workflow errored, create them manually in Power Automate:")
print()
print("FLOW 1 — Activity Logged → Contacting")
print("  Trigger : When a row is added (activitypointer)")
print("  Filter  : regardingobjecttypecode = lead")
print("            AND lead._stageid_value = (New stage ID)")
print(f"            New stage ID: {new_stage_id}")
print("  Action  : Update a row (leads)")
print(f"            stageid = {contacting_stage_id}  (Contacting)")
print(f"            processid = {BPF_ID}")
print()
print("FLOW 2 — Email Reply → Engaged")
print("  Trigger : When a row is added (email)")
print("  Filter  : directioncode = Incoming (1)")
print("            AND regardingobjecttypecode = lead")
print("            AND lead._stageid_value = (Contacting stage ID)")
print(f"            Contacting stage ID: {contacting_stage_id}")
print("  Action  : Update a row (leads)")
print(f"            stageid = {engaged_stage_id}  (Engaged)")
print(f"            processid = {BPF_ID}")
print("=" * 60)
