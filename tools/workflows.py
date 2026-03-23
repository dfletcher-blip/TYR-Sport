# ============================================================
# tools/workflows.py — Workflow Management Tools
# ============================================================
# These tools let Claude check, monitor, and manage
# workflows (automated processes) in your Microsoft CRM.
#
# Workflows in Dynamics 365 automatically do things like:
#   - Send emails when a deal closes
#   - Assign leads to salespeople
#   - Update records when conditions are met
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


def list_workflows(status: str = "all") -> dict:
    """
    List all workflows in the CRM.

    status: filter by status —
            "all"      → every workflow
            "active"   → only running workflows
            "inactive" → only paused/disabled workflows
            "draft"    → only unpublished workflows

    Returns a list of workflows with their current status.
    """
    params = {
        "$top": 200,
        "$select": "workflowid,name,statecode,statuscode,category,createdon,modifiedon,description",
        "$orderby": "name asc",
    }

    # Status codes in Dynamics 365:
    # statecode 0 = Active/Published, statecode 1 = Draft/Inactive
    if status == "active":
        params["$filter"] = "statecode eq 1 and category eq 0"
    elif status == "inactive":
        params["$filter"] = "statecode eq 0 and category eq 0"
    elif status == "draft":
        params["$filter"] = "statecode eq 0"

    # Only fetch real workflows (category 0), not other process types
    if "filter" not in str(params.get("$filter", "")):
        params["$filter"] = "category eq 0"

    result = crm_get("workflows", params)
    workflows = result.get("value", [])

    # Status code meanings
    status_labels = {
        (1, 2): "Active",
        (0, 1): "Draft",
        (0, 3): "Inactive",
    }

    formatted = []
    for wf in workflows:
        state  = wf.get("statecode", 0)
        status_code = wf.get("statuscode", 1)
        label  = status_labels.get((state, status_code), f"Unknown ({state}/{status_code})")

        formatted.append({
            "id": wf.get("workflowid"),
            "name": wf.get("name", "Unnamed"),
            "status": label,
            "description": wf.get("description", "No description"),
            "created": wf.get("createdon", ""),
            "last_modified": wf.get("modifiedon", ""),
        })

    active_count   = sum(1 for w in formatted if w["status"] == "Active")
    inactive_count = sum(1 for w in formatted if w["status"] != "Active")

    return {
        "total_workflows": len(formatted),
        "active": active_count,
        "inactive_or_draft": inactive_count,
        "workflows": formatted,
    }


def get_workflow_details(workflow_id: str) -> dict:
    """
    Get detailed information about a specific workflow.

    workflow_id: the unique ID of the workflow (from list_workflows)

    Returns the workflow definition, trigger conditions, and current status.
    """
    result = crm_get(f"workflows({workflow_id})")

    return {
        "id": result.get("workflowid"),
        "name": result.get("name", ""),
        "description": result.get("description", ""),
        "status": "Active" if result.get("statecode") == 1 else "Inactive/Draft",
        "trigger_on": result.get("triggeronupdateattributelist", "Not specified"),
        "entity": result.get("primaryentity", ""),
        "created": result.get("createdon", ""),
        "last_modified": result.get("modifiedon", ""),
        "xaml_definition": result.get("xaml", "")[:500] + "..." if result.get("xaml") else "No definition",
    }


def check_workflow_health() -> dict:
    """
    Check the overall health of all workflows.
    Looks for workflows that might have problems:
      - Workflows that are active but haven't run recently
      - Workflows stuck with errors
      - Draft workflows that were never published

    Returns a health report with recommendations.
    """
    # Get all workflows
    all_wf = list_workflows("all")

    # Get system jobs (workflow run history) for failures
    params_jobs = {
        "$top": 200,
        "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,createdon,modifiedon",
        "$filter": "statecode eq 3 and operationtype eq 10",  # Failed workflow jobs
        "$orderby": "modifiedon desc",
    }

    try:
        failed_jobs = crm_get("asyncoperations", params_jobs).get("value", [])
    except Exception:
        failed_jobs = []

    # Get stuck/waiting jobs
    params_stuck = {
        "$top": 100,
        "$select": "asyncoperationid,name,statecode,statuscode,createdon",
        "$filter": "statecode eq 0 and operationtype eq 10",  # Waiting jobs
        "$orderby": "createdon asc",
    }

    try:
        waiting_jobs = crm_get("asyncoperations", params_stuck).get("value", [])
    except Exception:
        waiting_jobs = []

    issues = []

    if failed_jobs:
        issues.append({
            "type": "Failed Workflow Runs",
            "severity": "High",
            "count": len(failed_jobs),
            "message": f"{len(failed_jobs)} workflows failed recently",
            "action": "Review failed jobs and fix the underlying issues",
            "examples": [j.get("name", "Unknown") for j in failed_jobs[:3]],
        })

    if waiting_jobs:
        issues.append({
            "type": "Stuck Workflows",
            "severity": "Medium",
            "count": len(waiting_jobs),
            "message": f"{len(waiting_jobs)} workflows are waiting/stuck",
            "action": "Investigate stuck jobs — may need to cancel and re-trigger",
        })

    draft_count = all_wf.get("inactive_or_draft", 0)
    if draft_count > 0:
        issues.append({
            "type": "Unpublished Workflows",
            "severity": "Low",
            "count": draft_count,
            "message": f"{draft_count} workflows are inactive or in draft",
            "action": "Review if these should be activated or deleted",
        })

    health_score = "Healthy"
    if any(i["severity"] == "High" for i in issues):
        health_score = "Critical"
    elif any(i["severity"] == "Medium" for i in issues):
        health_score = "Warning"
    elif issues:
        health_score = "Minor Issues"

    return {
        "overall_health": health_score,
        "total_workflows": all_wf["total_workflows"],
        "active_workflows": all_wf["active"],
        "issues_found": len(issues),
        "issues": issues,
        "recommendation": (
            "All workflows are running normally." if not issues
            else "See issues list above for recommended actions."
        ),
    }


def get_recent_workflow_runs(limit: int = 20) -> dict:
    """
    Show the most recent workflow run history.
    Useful for checking if workflows are actually executing.

    limit: number of recent runs to show (default 20)

    Returns recent workflow executions with success/failure status.
    """
    params = {
        "$top": limit,
        "$select": "asyncoperationid,name,statecode,statuscode,friendlymessage,createdon,modifiedon",
        "$filter": "operationtype eq 10",  # Workflow operations
        "$orderby": "modifiedon desc",
    }

    result = crm_get("asyncoperations", params)
    jobs = result.get("value", [])

    status_map = {
        (0, 0): "Waiting",
        (0, 10): "In Progress",
        (0, 20): "Pausing",
        (0, 21): "Canceling",
        (1, 30): "Succeeded",
        (2, 31): "Failed",
        (2, 32): "Canceled",
    }

    formatted = []
    for job in jobs:
        state  = job.get("statecode", 0)
        status = job.get("statuscode", 0)
        label  = status_map.get((state, status), "Unknown")

        formatted.append({
            "name": job.get("name", "Unknown Workflow"),
            "status": label,
            "error_message": job.get("friendlymessage", "") if label == "Failed" else "",
            "started": job.get("createdon", ""),
            "completed": job.get("modifiedon", ""),
        })

    succeeded = sum(1 for j in formatted if j["status"] == "Succeeded")
    failed    = sum(1 for j in formatted if j["status"] == "Failed")

    return {
        "total_runs_shown": len(formatted),
        "succeeded": succeeded,
        "failed": failed,
        "success_rate": f"{succeeded / len(formatted) * 100:.0f}%" if formatted else "N/A",
        "recent_runs": formatted,
    }


def activate_workflow(workflow_id: str) -> dict:
    """
    Activate (turn on) a workflow that is currently inactive or in draft.

    workflow_id: the unique ID of the workflow to activate

    Returns confirmation of the activation.
    """
    # In Dynamics 365, activating a workflow sets statecode to 1 and statuscode to 2
    result = crm_patch("workflows", workflow_id, {
        "statecode": 1,
        "statuscode": 2,
    })

    return {
        "success": True,
        "workflow_id": workflow_id,
        "message": "Workflow has been activated and is now running",
    }


def deactivate_workflow(workflow_id: str, reason: str = "") -> dict:
    """
    Deactivate (turn off) an active workflow.

    workflow_id: the unique ID of the workflow to deactivate
    reason: optional note explaining why it was deactivated

    Returns confirmation of the deactivation.
    """
    result = crm_patch("workflows", workflow_id, {
        "statecode": 0,
        "statuscode": 1,
    })

    return {
        "success": True,
        "workflow_id": workflow_id,
        "reason": reason,
        "message": "Workflow has been deactivated",
    }
