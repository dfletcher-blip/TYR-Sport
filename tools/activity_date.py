# ============================================================
# tools/activity_date.py — Last Activity Date Field Management
# ============================================================
# Create and maintain a tyr_lastactivitydate custom field on
# lead, contact, and account records. The field is updated by
# querying the activitypointer entity for the most recent
# activity (email, phone call, task, appointment) linked to
# each record.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone
from config.crm_connection import crm_get, crm_patch, crm_post, crm_action
from tools.form_customization import create_custom_field, add_fields_to_form

FIELD_LOGICAL_NAME = "tyr_lastactivitydate"
FIELD_DISPLAY_NAME = "Last Activity Date"
SUPPORTED_ENTITIES = ("lead", "contact", "account")

# Maps entity logical name → OData collection + ID field
_ENTITY_META = {
    "lead":    {"collection": "leads",    "id_field": "leadid"},
    "contact": {"collection": "contacts", "id_field": "contactid"},
    "account": {"collection": "accounts", "id_field": "accountid"},
}


def setup_last_activity_date_fields(add_to_form: bool = True) -> dict:
    """
    Create the tyr_lastactivitydate (Date) custom field on lead, contact,
    and account, then optionally add it to each entity's main form.

    add_to_form: if True (default), adds the field to the main form for each
                 entity so it is visible to users in the CRM UI.

    Returns a summary of what was created or skipped for each entity.
    """
    results = {}

    for entity in SUPPORTED_ENTITIES:
        entity_result = {"entity": entity, "field_created": False, "form_updated": False, "notes": []}

        # Create the custom field
        create_result = create_custom_field(
            entity=entity,
            display_name=FIELD_DISPLAY_NAME,
            field_type="date",
        )

        if create_result.get("success"):
            entity_result["field_created"] = True
            entity_result["logical_name"] = create_result.get("logical_name", FIELD_LOGICAL_NAME)
        elif "already exists" in str(create_result.get("error", "")).lower() or \
             "duplicate" in str(create_result.get("error", "")).lower():
            entity_result["notes"].append("Field already exists — skipped creation.")
            entity_result["logical_name"] = FIELD_LOGICAL_NAME
        else:
            entity_result["error"] = create_result.get("error", "Unknown error during field creation")
            results[entity] = entity_result
            continue

        # Add the field to the entity form
        if add_to_form:
            form_result = add_fields_to_form(
                entity=entity,
                fields=[FIELD_LOGICAL_NAME],
                section_label="Activity",
            )
            if form_result.get("success"):
                entity_result["form_updated"] = True
            else:
                entity_result["notes"].append(
                    f"Form update issue: {form_result.get('error') or form_result.get('message', 'unknown')}"
                )

        results[entity] = entity_result

    summary = {
        "success": True,
        "field_name": FIELD_LOGICAL_NAME,
        "display_name": FIELD_DISPLAY_NAME,
        "entities": results,
        "message": (
            f"Last Activity Date field setup complete for {', '.join(SUPPORTED_ENTITIES)}. "
            "Use sync_last_activity_dates to populate historical data, or "
            "update_last_activity_date to refresh a single record."
        ),
    }
    return summary


def update_last_activity_date(entity: str, record_id: str) -> dict:
    """
    Find the most recent activity linked to a single record and write its
    date into tyr_lastactivitydate.

    entity: "lead", "contact", or "account"
    record_id: the GUID of the record to update

    Activities checked: email, phone call, task, appointment, fax, letter.
    """
    entity = entity.lower()
    if entity not in _ENTITY_META:
        return {"error": f"Unsupported entity '{entity}'. Must be one of: {', '.join(SUPPORTED_ENTITIES)}"}

    meta = _ENTITY_META[entity]

    # Query activitypointer for the most recent activity linked to this record
    try:
        params = {
            "$select": "activityid,activitytypecode,actualend,createdon",
            "$filter": (
                f"_regardingobjectid_value eq {record_id} "
                "and statecode eq 1"  # 1 = Completed
            ),
            "$orderby": "actualend desc",
            "$top": 1,
        }
        activities = crm_get("activitypointers", params).get("value", [])

        # Fall back to any activity (not just completed) if none found
        if not activities:
            params["$filter"] = f"_regardingobjectid_value eq {record_id}"
            params["$orderby"] = "createdon desc"
            activities = crm_get("activitypointers", params).get("value", [])

    except Exception as e:
        return {"error": f"Could not query activities: {e}", "entity": entity, "record_id": record_id}

    if not activities:
        return {
            "success": True,
            "entity": entity,
            "record_id": record_id,
            "message": "No activities found for this record — field not updated.",
            "last_activity_date": None,
        }

    activity = activities[0]
    raw_date = activity.get("actualend") or activity.get("createdon")

    # Parse and reformat to date-only ISO string (YYYY-MM-DD)
    try:
        dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        date_only = dt.strftime("%Y-%m-%d")
    except Exception:
        date_only = raw_date[:10] if raw_date else None

    if not date_only:
        return {"error": "Could not parse activity date", "raw_date": raw_date}

    # Write the date to the record
    try:
        collection = meta["collection"]
        crm_patch(f"{collection}({record_id})", {FIELD_LOGICAL_NAME: date_only})
    except Exception as e:
        return {"error": f"Could not update record: {e}", "entity": entity, "record_id": record_id}

    return {
        "success": True,
        "entity": entity,
        "record_id": record_id,
        "last_activity_date": date_only,
        "activity_type": activity.get("activitytypecode", "unknown"),
        "message": f"Last Activity Date updated to {date_only}",
    }


def sync_last_activity_dates(entity: str, limit: int = 200, preview_only: bool = False) -> dict:
    """
    Backfill tyr_lastactivitydate for all active records of an entity by
    querying each record's linked activities.

    entity: "lead", "contact", or "account"
    limit: maximum number of records to process (default 200)
    preview_only: if True, show which records would be updated without writing

    Use this after setup_last_activity_date_fields to populate historical data.
    For ongoing updates, consider a Dynamics 365 workflow/Power Automate flow
    that calls update_last_activity_date when an activity is completed.
    """
    entity = entity.lower()
    if entity not in _ENTITY_META:
        return {"error": f"Unsupported entity '{entity}'. Must be one of: {', '.join(SUPPORTED_ENTITIES)}"}

    meta = _ENTITY_META[entity]
    collection = meta["collection"]
    id_field = meta["id_field"]

    # Fetch active records
    try:
        params = {
            "$select": f"{id_field},{'fullname' if entity != 'account' else 'name'}",
            "$filter": "statecode eq 0",
            "$top": limit,
        }
        records = crm_get(collection, params).get("value", [])
    except Exception as e:
        return {"error": f"Could not fetch {entity} records: {e}"}

    if not records:
        return {"message": f"No active {entity} records found.", "count": 0}

    name_field = "fullname" if entity != "account" else "name"

    if preview_only:
        return {
            "preview_only": True,
            "entity": entity,
            "record_count": len(records),
            "records": [
                {"id": r[id_field], "name": r.get(name_field, "")}
                for r in records
            ],
            "message": f"Would sync Last Activity Date for {len(records)} {entity} records. Set preview_only=False to execute.",
        }

    updated = []
    skipped = []
    errors = []

    for record in records:
        record_id = record.get(id_field)
        name = record.get(name_field, "")
        result = update_last_activity_date(entity, record_id)

        if result.get("success"):
            if result.get("last_activity_date"):
                updated.append({"id": record_id, "name": name, "date": result["last_activity_date"]})
            else:
                skipped.append({"id": record_id, "name": name, "reason": "No activities found"})
        else:
            errors.append({"id": record_id, "name": name, "error": result.get("error", "Unknown")})

    return {
        "success": True,
        "entity": entity,
        "total_processed": len(records),
        "updated": len(updated),
        "skipped_no_activity": len(skipped),
        "errors": len(errors),
        "error_details": errors,
        "message": (
            f"Sync complete for {entity}: {len(updated)} updated, "
            f"{len(skipped)} skipped (no activity), {len(errors)} errors."
        ),
    }


def get_last_activity_date_status(entity: str, limit: int = 50) -> dict:
    """
    Report on the tyr_lastactivitydate field population across records of an entity.
    Shows how many records have the field set vs blank, and lists records with no date.

    entity: "lead", "contact", or "account"
    limit: max records to inspect (default 50)
    """
    entity = entity.lower()
    if entity not in _ENTITY_META:
        return {"error": f"Unsupported entity '{entity}'. Must be one of: {', '.join(SUPPORTED_ENTITIES)}"}

    meta = _ENTITY_META[entity]
    collection = meta["collection"]
    id_field = meta["id_field"]
    name_field = "fullname" if entity != "account" else "name"

    try:
        params = {
            "$select": f"{id_field},{name_field},{FIELD_LOGICAL_NAME}",
            "$filter": "statecode eq 0",
            "$top": limit,
            "$orderby": f"{FIELD_LOGICAL_NAME} desc",
        }
        records = crm_get(collection, params).get("value", [])
    except Exception as e:
        return {"error": f"Could not fetch records: {e}"}

    filled = [r for r in records if r.get(FIELD_LOGICAL_NAME)]
    blank = [r for r in records if not r.get(FIELD_LOGICAL_NAME)]

    return {
        "entity": entity,
        "total_inspected": len(records),
        "field_populated": len(filled),
        "field_blank": len(blank),
        "fill_rate_pct": round(100 * len(filled) / len(records), 1) if records else 0,
        "most_recent": filled[0].get(FIELD_LOGICAL_NAME) if filled else None,
        "oldest": filled[-1].get(FIELD_LOGICAL_NAME) if filled else None,
        "blank_records": [
            {"id": r[id_field], "name": r.get(name_field, "")}
            for r in blank[:20]
        ],
        "message": (
            f"{len(filled)}/{len(records)} active {entity} records have Last Activity Date set "
            f"({round(100 * len(filled) / len(records), 1) if records else 0}%). "
            + (f"Run sync_last_activity_dates('{entity}') to fill blank records." if blank else "All records are populated.")
        ),
    }


def create_activity_date_workflows() -> dict:
    """
    Create Dynamics 365 Classic Workflows that automatically update
    tyr_lastactivitydate on the regarding contact, lead, or account
    whenever an email, phone call, or task is marked as completed in the CRM.

    This covers activities logged by humans in the CRM UI — the agent already
    auto-stamps the field when it sends emails itself.

    Creates 3 workflows (one per activity type). Each runs asynchronously,
    triggers on record status change to Completed, and patches the regarding
    record's tyr_lastactivitydate to today's date.
    """
    from datetime import date

    activity_configs = [
        {
            "entity": "email",
            "display": "Email",
            "trigger_attr": "statecode",
            "name": "TYR - Update Last Activity Date on Email Completed",
        },
        {
            "entity": "phonecall",
            "display": "Phone Call",
            "trigger_attr": "statecode",
            "name": "TYR - Update Last Activity Date on Phone Call Completed",
        },
        {
            "entity": "task",
            "display": "Task",
            "trigger_attr": "statecode",
            "name": "TYR - Update Last Activity Date on Task Completed",
        },
    ]

    created = []
    skipped = []
    errors = []

    for cfg in activity_configs:
        # Build the XAML for a workflow that reads regardingobjectid and
        # patches tyr_lastactivitydate on the regarding record.
        # This uses the D365 Classic Workflow (WF4) format.
        xaml = f"""<Activity x:Class="TYR.UpdateLastActivityDate_{cfg['entity']}"
  xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
  xmlns:mxswa="clr-namespace:Microsoft.Xrm.Sdk.Workflow.Activities;assembly=Microsoft.Xrm.Sdk.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
  xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
  xmlns:crm="clr-namespace:Microsoft.Xrm.Sdk;assembly=Microsoft.Xrm.Sdk, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
  xmlns:scg="clr-namespace:System.Collections.Generic;assembly=mscorlib, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089"
  xmlns:this="clr-namespace:TYR">
  <mxswa:Workflow>
    <Sequence DisplayName="Update Last Activity Date on Regarding Record">
      <Sequence.Variables>
        <Variable x:TypeArguments="crm:EntityReference" Name="RegardingRef" />
        <Variable x:TypeArguments="x:DateTime" Name="TodayDate" />
      </Sequence.Variables>
      <mxswa:ActivityReference
        AssemblyQualifiedName="Microsoft.Crm.Workflow.Activities.EvaluateExpression, Microsoft.Crm.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
        DisplayName="Get Today">
        <mxswa:ActivityReference.Properties>
          <Property Name="ExpressionOperator" Value="SelectFirstNonNull" />
          <Property Name="Parameters">
            <scg:Dictionary x:TypeArguments="x:String, mxswa:MxExpression">
              <mxswa:MxExpression x:Key="P0">
                <mxswa:MxExpression.Arguments>
                  <InArgument x:TypeArguments="x:DateTime">
                    <mxswa:ActivityReference
                      AssemblyQualifiedName="Microsoft.Crm.Workflow.Activities.GetContextProperty, Microsoft.Crm.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
                      DisplayName="ExecutionTime">
                      <mxswa:ActivityReference.Properties>
                        <Property Name="PropertyName" Value="ExecutionTime" />
                        <Property Name="OdataType" Value="Edm.DateTimeOffset" />
                        <Property Name="Result">
                          <OutArgument x:TypeArguments="x:DateTime">
                            <Variable x:TypeArguments="x:DateTime" Name="TodayDate" />
                          </OutArgument>
                        </Property>
                      </mxswa:ActivityReference.Properties>
                    </mxswa:ActivityReference>
                  </InArgument>
                </mxswa:MxExpression.Arguments>
              </mxswa:MxExpression>
            </scg:Dictionary>
          </Property>
          <Property Name="ReturnType" Value="{{x:Type x:DateTime}}" />
          <Property Name="Result">
            <OutArgument x:TypeArguments="x:DateTime">
              <Variable x:TypeArguments="x:DateTime" Name="TodayDate" />
            </OutArgument>
          </Property>
        </mxswa:ActivityReference.Properties>
      </mxswa:ActivityReference>
      <mxswa:ActivityReference
        AssemblyQualifiedName="Microsoft.Crm.Workflow.Activities.GetEntityProperty, Microsoft.Crm.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
        DisplayName="Get Regarding">
        <mxswa:ActivityReference.Properties>
          <Property Name="Attribute" Value="regardingobjectid" />
          <Property Name="Entity">
            <InArgument x:TypeArguments="crm:Entity">
              <mxswa:ActivityReference
                AssemblyQualifiedName="Microsoft.Crm.Workflow.Activities.GetWorkflowEntity, Microsoft.Crm.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
                DisplayName="Get Primary Entity">
              </mxswa:ActivityReference>
            </InArgument>
          </Property>
          <Property Name="Result">
            <OutArgument x:TypeArguments="crm:EntityReference">
              <Variable x:TypeArguments="crm:EntityReference" Name="RegardingRef" />
            </OutArgument>
          </Property>
        </mxswa:ActivityReference.Properties>
      </mxswa:ActivityReference>
      <mxswa:ActivityReference
        AssemblyQualifiedName="Microsoft.Crm.Workflow.Activities.SetEntityProperty, Microsoft.Crm.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
        DisplayName="Set Last Activity Date">
        <mxswa:ActivityReference.Properties>
          <Property Name="Attribute" Value="{FIELD_LOGICAL_NAME}" />
          <Property Name="Entity">
            <InArgument x:TypeArguments="crm:Entity">
              <mxswa:ActivityReference
                AssemblyQualifiedName="Microsoft.Crm.Workflow.Activities.GetWorkflowEntity, Microsoft.Crm.Workflow, Version=9.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"
                DisplayName="Get Regarding Entity">
                <mxswa:ActivityReference.Properties>
                  <Property Name="EntityReference">
                    <InArgument x:TypeArguments="crm:EntityReference">
                      <Variable x:TypeArguments="crm:EntityReference" Name="RegardingRef" />
                    </InArgument>
                  </Property>
                </mxswa:ActivityReference.Properties>
              </mxswa:ActivityReference>
            </InArgument>
          </Property>
          <Property Name="Value">
            <InArgument x:TypeArguments="x:Object">
              <Variable x:TypeArguments="x:DateTime" Name="TodayDate" />
            </InArgument>
          </Property>
        </mxswa:ActivityReference.Properties>
      </mxswa:ActivityReference>
    </Sequence>
  </mxswa:Workflow>
</Activity>"""

        workflow_payload = {
            "name": cfg["name"],
            "primaryentity": cfg["entity"],
            "category": 0,          # Classic Workflow
            "type": 1,              # Definition
            "mode": 1,              # Asynchronous (background)
            "scope": 4,             # Organization scope
            "triggeroncreate": False,
            "triggeronupdateattributelist": cfg["trigger_attr"],
            "triggeronstatuschange": True,
            "isontdemand": False,
            "xaml": xaml,
        }

        try:
            # Check if a workflow with this name already exists
            existing = crm_get("workflows", {
                "$select": "workflowid,name,statecode",
                "$filter": f"name eq '{cfg['name']}'",
                "$top": 1,
            }).get("value", [])

            if existing:
                skipped.append({
                    "name": cfg["name"],
                    "id": existing[0]["workflowid"],
                    "reason": "Already exists",
                })
                continue

            result = crm_post("workflows", workflow_payload)
            workflow_id = result.get("workflowid") or result.get("@odata.id", "")

            # Activate the workflow
            if workflow_id:
                try:
                    crm_action("SetState", {
                        "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": workflow_id},
                        "State": {"Value": 1},   # Active
                        "Status": {"Value": 2},  # Active
                    })
                    activated = True
                except Exception as act_err:
                    activated = False

            created.append({
                "name": cfg["name"],
                "entity": cfg["entity"],
                "id": workflow_id,
                "activated": activated if workflow_id else False,
            })

        except Exception as e:
            errors.append({"name": cfg["name"], "entity": cfg["entity"], "error": str(e)})

    return {
        "success": True,
        "workflows_created": len(created),
        "workflows_skipped": len(skipped),
        "workflows_failed": len(errors),
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "message": (
            f"Created {len(created)} workflow(s), {len(skipped)} already existed, {len(errors)} failed. "
            "Active workflows will fire automatically when an email, phone call, or task is marked Completed "
            "and update tyr_lastactivitydate on the linked contact, lead, or account."
        ),
    }
