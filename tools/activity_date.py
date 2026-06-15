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
from config.crm_connection import crm_get, crm_patch, crm_post, crm_action, crm_delete
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
                f"_regardingobjectid_value eq '{record_id}' "
                "and statecode eq 1"
            ),
            "$orderby": "actualend desc",
            "$top": 1,
        }
        activities = crm_get("activitypointers", params).get("value", [])

        # Fall back to any activity (not just completed) if none found
        if not activities:
            params["$filter"] = f"_regardingobjectid_value eq '{record_id}'"
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
        crm_patch(collection, record_id, {FIELD_LOGICAL_NAME: date_only})
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


def delete_broken_activity_date_workflows() -> dict:
    """
    Find and delete the broken 'Update Last Activity Date' Classic Workflows
    that were created with the wrong entity (Quick Campaign) and wrong steps.
    Safe to run multiple times.
    """
    broken_names = [
        "Update Last Activity Date – Email",
        "Update Last Activity Date – Phone Call",
        "Update Last Activity Date – Task",
        "Update Last Activity Date – Appointment",
        "TYR - Update Last Activity Date on Email Completed",
        "TYR - Update Last Activity Date on Phone Call Completed",
        "TYR - Update Last Activity Date on Task Completed",
    ]

    deleted = []
    not_found = []
    errors = []

    for name in broken_names:
        try:
            existing = crm_get("workflows", {
                "$select": "workflowid,name,statecode",
                "$filter": f"name eq '{name}'",
                "$top": 5,
            }).get("value", [])

            if not existing:
                not_found.append(name)
                continue

            for wf in existing:
                wf_id = wf["workflowid"]
                # Deactivate first (required before delete)
                try:
                    crm_action("SetState", {
                        "EntityMoniker": {"@odata.type": "Microsoft.Dynamics.CRM.workflow", "workflowid": wf_id},
                        "State": {"Value": 0},
                        "Status": {"Value": 1},
                    })
                except Exception:
                    pass
                crm_delete("workflows", wf_id)
                deleted.append({"name": name, "id": wf_id})

        except Exception as e:
            errors.append({"name": name, "error": str(e)})

    return {
        "success": True,
        "deleted": len(deleted),
        "not_found": len(not_found),
        "errors": len(errors),
        "deleted_details": deleted,
        "error_details": errors,
        "message": (
            f"Deleted {len(deleted)} broken workflow(s). "
            + ("Errors on some: " + str(errors) if errors else "")
        ),
    }


def create_activity_date_workflows() -> dict:
    """
    Clean up broken workflows and return step-by-step Power Automate instructions
    for setting up automatic Last Activity Date population. Also reports on what
    the agent already handles automatically (email sends).

    The D365 Classic Workflow API cannot reliably create 'update regarding record'
    workflows via XAML injection. Power Automate (make.powerautomate.com) handles
    this correctly and is the recommended approach.
    """
    # Clean up any broken workflows first
    cleanup = delete_broken_activity_date_workflows()

    instructions = {
        "what_agent_already_does": (
            "The agent automatically stamps tyr_lastactivitydate whenever it sends an email "
            "to a contact or lead through the CRM. No setup needed for agent-sent emails."
        ),
        "for_human_logged_activities": (
            "Create 3 Power Automate flows at make.powerautomate.com — one for each entity. "
            "Each flow watches for completed activities and updates tyr_lastactivitydate."
        ),
        "flow_1_contacts": {
            "name": "TYR - Last Activity Date - Contact",
            "steps": [
                "Go to make.powerautomate.com and click Create > Automated cloud flow",
                "Name it: TYR - Last Activity Date - Contact",
                "Search for trigger: 'When a row is added, modified or deleted' (Dataverse)",
                "Set Change type = Modified, Table = Activities (not a specific type — all activities)",
                "Set Filter rows = statecode eq 1",
                "Click Next / Create",
                "Add action: 'Update a row' (Dataverse)",
                "Set Table = Contacts",
                "Set Row ID = regardingobjectid (pick from dynamic content)",
                "Set tyr_lastactivitydate = utcNow() expression",
                "Save and turn on the flow",
            ],
        },
        "flow_2_leads": {
            "name": "TYR - Last Activity Date - Lead",
            "steps": [
                "Repeat the same steps as flow 1",
                "Change Table in 'Update a row' to Leads",
                "All other settings are the same",
            ],
        },
        "flow_3_accounts": {
            "name": "TYR - Last Activity Date - Account",
            "steps": [
                "Repeat the same steps as flow 1",
                "Change Table in 'Update a row' to Accounts",
                "All other settings are the same",
            ],
        },
        "note": (
            "Power Automate is free with your Dynamics 365 license. "
            "You can also use sync_last_activity_dates to backfill any records that were missed."
        ),
    }

    return {
        "success": True,
        "broken_workflows_deleted": cleanup.get("deleted", 0),
        "what_agent_does_automatically": instructions["what_agent_already_does"],
        "next_step": "Create 3 Power Automate flows at make.powerautomate.com using the instructions below.",
        "power_automate_instructions": instructions,
        "message": (
            f"Deleted {cleanup.get('deleted', 0)} broken workflow(s). "
            "The agent now auto-stamps tyr_lastactivitydate when it sends emails. "
            "For activities logged by humans, create the 3 Power Automate flows described above. "
            "Use sync_last_activity_dates to backfill historical data any time."
        ),
    }
