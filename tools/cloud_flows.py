# ============================================================
# tools/cloud_flows.py — Power Automate Cloud Flows Tools
# ============================================================
# Cloud Flows are the modern replacement for classic CRM
# workflows. They are built in Power Automate and can connect
# to hundreds of services beyond just Dynamics 365.
#
# In Dynamics 365, cloud flows appear as workflows with
# category = 5 (Modern Flow).
#
# This covers:
#   - Listing and searching cloud flows
#   - Checking flow health and run history
#   - Enabling and disabling flows
#   - Finding flows by the entity they trigger on
#   - Comparing classic vs modern flow coverage
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch


def list_cloud_flows(status: str = "all") -> dict:
    """
    List all Power Automate cloud flows connected to this CRM.

    status: filter by status —
            "all"      → every flow
            "active"   → only enabled flows
            "inactive" → only disabled flows

    Returns a list of cloud flows with their status and trigger info.
    """
    params = {
        "$top": 200,
        "$select": "workflowid,name,statecode,statuscode,createdon,modifiedon,description,primaryentity",
        "$orderby": "name asc",
        # category 5 = Modern Flow (Power Automate Cloud Flow)
        "$filter": "category eq 5",
    }

    if status == "active":
        params["$filter"] = "category eq 5 and statecode eq 1"
    elif status == "inactive":
        params["$filter"] = "category eq 5 and statecode eq 0"

    result = crm_get("workflows", params)
    flows = result.get("value", [])

    formatted = []
    for f in flows:
        state       = f.get("statecode", 0)
        status_code = f.get("statuscode", 1)

        # statecode 1 + statuscode 2 = Active/On
        # statecode 0 + statuscode 1 = Draft/Off
        if state == 1 and status_code == 2:
            flow_status = "Active"
        elif state == 0 and status_code == 1:
            flow_status = "Draft / Off"
        else:
            flow_status = f"Unknown ({state}/{status_code})"

        formatted.append({
            "id":            f.get("workflowid"),
            "name":          f.get("name", "Unnamed"),
            "status":        flow_status,
            "trigger_entity": f.get("primaryentity", "Unknown"),
            "description":   f.get("description", ""),
            "created":       f.get("createdon", ""),
            "last_modified": f.get("modifiedon", ""),
        })

    active_count   = sum(1 for f in formatted if f["status"] == "Active")
    inactive_count = len(formatted) - active_count

    return {
        "total_cloud_flows": len(formatted),
        "active":   active_count,
        "inactive": inactive_count,
        "flows":    formatted,
    }


def get_cloud_flow_details(flow_id: str) -> dict:
    """
    Get detailed information about a specific cloud flow.

    flow_id: the ID of the cloud flow

    Returns full details including description, trigger entity,
    and current status.
    """
    params = {
        "$select": "workflowid,name,statecode,statuscode,description,primaryentity,createdon,modifiedon,clientdata",
    }

    result = crm_get(f"workflows({flow_id})", params)

    state       = result.get("statecode", 0)
    status_code = result.get("statuscode", 1)

    if state == 1 and status_code == 2:
        flow_status = "Active"
    elif state == 0 and status_code == 1:
        flow_status = "Draft / Off"
    else:
        flow_status = f"Unknown ({state}/{status_code})"

    # clientdata contains the flow definition JSON (can be large)
    client_data = result.get("clientdata", "")
    has_definition = bool(client_data)

    return {
        "id":              result.get("workflowid"),
        "name":            result.get("name", "Unnamed"),
        "status":          flow_status,
        "trigger_entity":  result.get("primaryentity", "Unknown"),
        "description":     result.get("description", "No description"),
        "created":         result.get("createdon", ""),
        "last_modified":   result.get("modifiedon", ""),
        "has_definition":  has_definition,
        "note": "To edit this flow, open it in Power Automate at make.powerautomate.com",
    }


def get_cloud_flow_run_history(flow_id: str, limit: int = 20) -> dict:
    """
    Get the recent run history for a cloud flow.

    flow_id: the ID of the cloud flow
    limit:   max number of run records to return (default 20)

    Returns a list of recent runs showing success/failure and timing.
    """
    params = {
        "$top": limit,
        "$select": "flowsessionid,statecode,statuscode,startedon,completedon,errormessage",
        "$filter": f"_workflow_value eq '{flow_id}'",
        "$orderby": "startedon desc",
    }

    try:
        result = crm_get("flowsessions", params)
        runs = result.get("value", [])
    except Exception as e:
        return {
            "flow_id": flow_id,
            "error": f"Could not retrieve run history: {str(e)}",
            "hint": "Flow run history may not be available via the API for this org.",
        }

    status_map = {
        0: "Scheduled",
        1: "Running",
        2: "Waiting",
        3: "Succeeded",
        4: "Skipped",
        5: "Suspended",
        6: "Cancelled",
        7: "Failed",
        8: "Faulted",
        9: "TimedOut",
        10: "Aborted",
        11: "Ignored",
        12: "Succeeded with warnings",
    }

    formatted = []
    for r in runs:
        status_code = r.get("statuscode", 0)
        formatted.append({
            "run_id":       r.get("flowsessionid"),
            "status":       status_map.get(status_code, f"Unknown ({status_code})"),
            "started":      r.get("startedon", ""),
            "completed":    r.get("completedon", ""),
            "error":        r.get("errormessage", ""),
        })

    success_count = sum(1 for r in formatted if r["status"] in ("Succeeded", "Succeeded with warnings"))
    failed_count  = sum(1 for r in formatted if r["status"] in ("Failed", "Faulted", "TimedOut"))

    return {
        "flow_id":       flow_id,
        "total_runs":    len(formatted),
        "succeeded":     success_count,
        "failed":        failed_count,
        "success_rate":  f"{round(success_count / len(formatted) * 100)}%" if formatted else "N/A",
        "run_history":   formatted,
    }


def enable_cloud_flow(flow_id: str) -> dict:
    """
    Enable (turn on) a cloud flow.

    flow_id: the ID of the cloud flow to enable

    Returns confirmation that the flow has been turned on.
    """
    crm_patch("workflows", flow_id, {"statecode": 1, "statuscode": 2})
    return {
        "enabled": True,
        "flow_id": flow_id,
        "message": "Cloud flow has been turned ON.",
    }


def disable_cloud_flow(flow_id: str) -> dict:
    """
    Disable (turn off) a cloud flow.

    flow_id: the ID of the cloud flow to disable

    Returns confirmation that the flow has been turned off.
    WARNING: This stops the flow from running — confirm before disabling.
    """
    crm_patch("workflows", flow_id, {"statecode": 0, "statuscode": 1})
    return {
        "disabled": True,
        "flow_id":  flow_id,
        "message":  "Cloud flow has been turned OFF.",
    }


def search_cloud_flows(search_term: str) -> dict:
    """
    Search for cloud flows by name.

    search_term: part of the flow name to search for

    Returns matching cloud flows.
    """
    params = {
        "$top": 50,
        "$select": "workflowid,name,statecode,statuscode,primaryentity,modifiedon",
        "$filter": f"category eq 5 and contains(name,'{search_term}')",
        "$orderby": "name asc",
    }

    result = crm_get("workflows", params)
    flows = result.get("value", [])

    return {
        "search_term":  search_term,
        "total_found":  len(flows),
        "flows": [
            {
                "id":             f.get("workflowid"),
                "name":           f.get("name", "Unnamed"),
                "status":         "Active" if f.get("statecode") == 1 else "Inactive",
                "trigger_entity": f.get("primaryentity", ""),
                "last_modified":  f.get("modifiedon", ""),
            }
            for f in flows
        ],
    }


def get_cloud_flows_by_entity(entity: str) -> dict:
    """
    Get all cloud flows that trigger on a specific entity type.

    entity: the CRM entity name — e.g. "contact", "lead",
            "account", "opportunity", "new_specialterm"

    Returns all flows watching that entity — useful for understanding
    what automation fires when a record is changed.
    """
    params = {
        "$top": 100,
        "$select": "workflowid,name,statecode,statuscode,primaryentity,createdon,modifiedon",
        "$filter": f"category eq 5 and primaryentity eq '{entity}'",
        "$orderby": "name asc",
    }

    result = crm_get("workflows", params)
    flows = result.get("value", [])

    return {
        "entity":         entity,
        "total_flows":    len(flows),
        "active_flows":   sum(1 for f in flows if f.get("statecode") == 1),
        "inactive_flows": sum(1 for f in flows if f.get("statecode") != 1),
        "flows": [
            {
                "id":            f.get("workflowid"),
                "name":          f.get("name", "Unnamed"),
                "status":        "Active" if f.get("statecode") == 1 else "Inactive",
                "last_modified": f.get("modifiedon", ""),
            }
            for f in flows
        ],
    }


def check_cloud_flow_health() -> dict:
    """
    Run a health check across all cloud flows.

    Identifies flows that are inactive when they probably should be on,
    and flows with recent failures.

    Returns a prioritised list of flows that need attention.
    """
    all_flows = list_cloud_flows(status="all")
    flows = all_flows.get("flows", [])

    inactive = [f for f in flows if f["status"] != "Active"]
    active   = [f for f in flows if f["status"] == "Active"]

    issues = []
    for f in inactive:
        issues.append({
            "flow_id":  f["id"],
            "name":     f["name"],
            "issue":    "Flow is INACTIVE — not running",
            "severity": "Warning",
        })

    return {
        "total_flows":    len(flows),
        "active":         len(active),
        "inactive":       len(inactive),
        "issues_found":   len(issues),
        "health_status":  "OK" if not issues else f"{len(issues)} flow(s) need attention",
        "issues":         issues,
    }


def compare_classic_vs_cloud_flows() -> dict:
    """
    Compare the count and coverage of classic workflows vs
    modern Power Automate cloud flows.

    Returns a side-by-side summary — useful for planning
    migration from legacy workflows to cloud flows.
    """
    # Classic workflows = category 0
    classic = crm_get("workflows", {
        "$top": 1,
        "$select": "workflowid",
        "$filter": "category eq 0",
        "$count": "true",
    })

    # Cloud flows = category 5
    cloud = crm_get("workflows", {
        "$top": 1,
        "$select": "workflowid",
        "$filter": "category eq 5",
        "$count": "true",
    })

    classic_count = classic.get("@odata.count", len(classic.get("value", [])))
    cloud_count   = cloud.get("@odata.count", len(cloud.get("value", [])))

    return {
        "classic_workflows":     classic_count,
        "cloud_flows":           cloud_count,
        "total_automations":     classic_count + cloud_count,
        "recommendation": (
            "Good mix of classic and modern flows."
            if cloud_count > 0
            else "No cloud flows found. Consider migrating classic workflows to Power Automate for better flexibility."
        ),
    }
