# ============================================================
# tools/activities.py — Activities & Notes Tools
# ============================================================
# Activities are the daily work of CRM — logging calls made,
# tasks to follow up on, meetings scheduled, and notes taken.
# Every contact, lead, account, and opportunity can have
# activities and notes attached to it.
#
# Covers:
#   - Tasks       (to-do items with due dates)
#   - Phone Calls (inbound and outbound call logs)
#   - Appointments (meetings and events)
#   - Notes       (free-text notes on any record)
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post


# ── TASKS ────────────────────────────────────────────────────


def get_tasks(regarding_id: str = "", regarding_type: str = "contact",
              status: str = "open", limit: int = 50) -> dict:
    """
    Get tasks from the CRM.

    regarding_id:   ID of the record to get tasks for (contact, lead, account, etc.)
                    Leave blank to get all tasks across the CRM.
    regarding_type: the type of record — "contact", "lead", "account", "opportunity"
    status:         "open"      → incomplete tasks
                    "completed" → finished tasks
                    "all"       → everything
    limit:          max number of tasks to return (default 50)

    Returns a list of tasks with their details and due dates.
    """
    params = {
        "$top": limit,
        "$select": "activityid,subject,description,scheduledend,prioritycode,statecode,statuscode,createdon,modifiedon",
        "$orderby": "scheduledend asc",
    }

    filters = []

    if status == "open":
        filters.append("statecode eq 0")
    elif status == "completed":
        filters.append("statecode eq 1")

    if regarding_id:
        entity_map = {
            "contact":     "contact",
            "lead":        "lead",
            "account":     "account",
            "opportunity": "opportunity",
        }
        entity_name = entity_map.get(regarding_type, regarding_type)
        filters.append(f"_regardingobjectid_value eq '{regarding_id}'")

    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get("tasks", params)
    tasks = result.get("value", [])

    priority_map = {0: "Low", 1: "Normal", 2: "High"}
    status_map   = {0: "Open", 1: "Completed", 2: "Cancelled"}

    return {
        "total_found": len(tasks),
        "tasks": [
            {
                "id":          t.get("activityid"),
                "subject":     t.get("subject", "No subject"),
                "description": t.get("description", ""),
                "due_date":    t.get("scheduledend", "No due date"),
                "priority":    priority_map.get(t.get("prioritycode", 1), "Normal"),
                "status":      status_map.get(t.get("statecode", 0), "Unknown"),
                "created":     t.get("createdon", ""),
            }
            for t in tasks
        ],
    }


def create_task(subject: str, regarding_id: str, regarding_type: str = "contact",
                description: str = "", due_date: str = "", priority: str = "normal") -> dict:
    """
    Create a new task (to-do item) linked to a CRM record.

    subject:        short title for the task (e.g. "Follow up on proposal")
    regarding_id:   ID of the record to attach this task to
    regarding_type: "contact", "lead", "account", or "opportunity"
    description:    longer notes about what needs to be done
    due_date:       when this task is due — format: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SSZ"
    priority:       "low", "normal", or "high"

    Returns confirmation with the new task ID.
    """
    entity_type_map = {
        "contact":     "contacts",
        "lead":        "leads",
        "account":     "accounts",
        "opportunity": "opportunities",
    }
    priority_map = {"low": 0, "normal": 1, "high": 2}

    data = {
        "subject":      subject,
        "prioritycode": priority_map.get(priority.lower(), 1),
    }

    if description:
        data["description"] = description

    if due_date:
        if "T" not in due_date:
            due_date = due_date + "T23:59:00Z"
        data["scheduledend"] = due_date

    if regarding_id:
        entity_set = entity_type_map.get(regarding_type, "contacts")
        data[f"regardingobjectid_{regarding_type}@odata.bind"] = f"/{entity_set}({regarding_id})"

    result = crm_post("tasks", data)
    return {"created": True, "subject": subject, "record": result}


def complete_task(task_id: str) -> dict:
    """
    Mark a task as completed.

    task_id: the ID of the task to complete

    Returns confirmation that the task was marked done.
    """
    crm_patch("tasks", task_id, {"statecode": 1, "statuscode": 5})
    return {"completed": True, "task_id": task_id}


# ── PHONE CALLS ──────────────────────────────────────────────


def get_phone_calls(regarding_id: str = "", status: str = "all", limit: int = 50) -> dict:
    """
    Get phone call activity records from the CRM.

    regarding_id: ID of the record to get calls for (leave blank for all calls)
    status:       "all", "open", or "completed"
    limit:        max number of records to return (default 50)

    Returns a list of logged phone calls.
    """
    params = {
        "$top": limit,
        "$select": "activityid,subject,description,directioncode,scheduledend,statecode,createdon",
        "$orderby": "createdon desc",
    }

    filters = []
    if status == "open":
        filters.append("statecode eq 0")
    elif status == "completed":
        filters.append("statecode eq 1")
    if regarding_id:
        filters.append(f"_regardingobjectid_value eq '{regarding_id}'")
    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get("phonecalls", params)
    calls = result.get("value", [])

    return {
        "total_found": len(calls),
        "phone_calls": [
            {
                "id":          c.get("activityid"),
                "subject":     c.get("subject", "No subject"),
                "description": c.get("description", ""),
                "direction":   "Outbound" if c.get("directioncode") else "Inbound",
                "date":        c.get("scheduledend") or c.get("createdon", ""),
                "status":      "Completed" if c.get("statecode") == 1 else "Open",
            }
            for c in calls
        ],
    }


def log_phone_call(subject: str, regarding_id: str, regarding_type: str = "contact",
                   description: str = "", direction: str = "outbound",
                   call_date: str = "") -> dict:
    """
    Log a phone call against a CRM record.

    subject:        what the call was about (e.g. "Discussed Q2 renewal")
    regarding_id:   ID of the contact, lead, account, or opportunity
    regarding_type: "contact", "lead", "account", or "opportunity"
    description:    notes from the call
    direction:      "outbound" (you called them) or "inbound" (they called you)
    call_date:      when the call happened — format "YYYY-MM-DDTHH:MM:SSZ"
                    (leave blank to use now)

    Returns confirmation the call was logged.
    """
    entity_type_map = {
        "contact":     "contacts",
        "lead":        "leads",
        "account":     "accounts",
        "opportunity": "opportunities",
    }

    data = {
        "subject":      subject,
        "directioncode": direction.lower() == "outbound",
        "statecode":    1,   # log as completed immediately
        "statuscode":   2,
    }

    if description:
        data["description"] = description
    if call_date:
        data["scheduledend"] = call_date
    if regarding_id:
        entity_set = entity_type_map.get(regarding_type, "contacts")
        data[f"regardingobjectid_{regarding_type}@odata.bind"] = f"/{entity_set}({regarding_id})"

    result = crm_post("phonecalls", data)
    return {"logged": True, "subject": subject, "direction": direction, "record": result}


# ── APPOINTMENTS ─────────────────────────────────────────────


def get_appointments(regarding_id: str = "", status: str = "upcoming", limit: int = 50) -> dict:
    """
    Get appointments from the CRM.

    regarding_id: ID of the record to get appointments for (leave blank for all)
    status:       "upcoming" → scheduled future meetings
                  "completed" → past meetings
                  "all"       → everything
    limit:        max number of records to return (default 50)

    Returns a list of appointments with times and locations.
    """
    params = {
        "$top": limit,
        "$select": "activityid,subject,scheduledstart,scheduledend,location,description,statecode,createdon",
        "$orderby": "scheduledstart asc",
    }

    filters = []
    if status == "upcoming":
        filters.append("statecode eq 0")
    elif status == "completed":
        filters.append("statecode eq 1")
    if regarding_id:
        filters.append(f"_regardingobjectid_value eq '{regarding_id}'")
    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get("appointments", params)
    appts = result.get("value", [])

    return {
        "total_found": len(appts),
        "appointments": [
            {
                "id":          a.get("activityid"),
                "subject":     a.get("subject", "No subject"),
                "start":       a.get("scheduledstart", ""),
                "end":         a.get("scheduledend", ""),
                "location":    a.get("location", "No location"),
                "description": a.get("description", ""),
                "status":      "Completed" if a.get("statecode") == 1 else "Scheduled",
            }
            for a in appts
        ],
    }


def create_appointment(subject: str, start: str, end: str,
                       regarding_id: str = "", regarding_type: str = "contact",
                       location: str = "", description: str = "") -> dict:
    """
    Create a new appointment in the CRM.

    subject:        title of the meeting (e.g. "Product demo with Nike")
    start:          start time — format "YYYY-MM-DDTHH:MM:SSZ"
    end:            end time   — format "YYYY-MM-DDTHH:MM:SSZ"
    regarding_id:   ID of the record to link this to (optional)
    regarding_type: "contact", "lead", "account", or "opportunity"
    location:       where the meeting is (room name, address, or "Teams")
    description:    agenda or notes

    Returns confirmation with the new appointment ID.
    """
    entity_type_map = {
        "contact":     "contacts",
        "lead":        "leads",
        "account":     "accounts",
        "opportunity": "opportunities",
    }

    data = {
        "subject":        subject,
        "scheduledstart": start,
        "scheduledend":   end,
    }

    if location:
        data["location"] = location
    if description:
        data["description"] = description
    if regarding_id:
        entity_set = entity_type_map.get(regarding_type, "contacts")
        data[f"regardingobjectid_{regarding_type}@odata.bind"] = f"/{entity_set}({regarding_id})"

    result = crm_post("appointments", data)
    return {"created": True, "subject": subject, "start": start, "end": end, "record": result}


# ── NOTES ────────────────────────────────────────────────────


def get_notes(regarding_id: str, regarding_type: str = "contact", limit: int = 50) -> dict:
    """
    Get all notes attached to a CRM record.

    regarding_id:   ID of the record to get notes for
    regarding_type: "contact", "lead", "account", or "opportunity"
    limit:          max number of notes to return (default 50)

    Returns a list of notes with their text and timestamps.
    """
    entity_code_map = {
        "contact":     2,
        "lead":        4,
        "account":     1,
        "opportunity": 3,
    }

    params = {
        "$top": limit,
        "$select": "annotationid,subject,notetext,createdon,modifiedon,filename",
        "$orderby": "createdon desc",
        "$filter": f"_objectid_value eq '{regarding_id}'",
    }

    result = crm_get("annotations", params)
    notes = result.get("value", [])

    return {
        "total_found": len(notes),
        "regarding_id": regarding_id,
        "notes": [
            {
                "id":           n.get("annotationid"),
                "subject":      n.get("subject", "No subject"),
                "text":         n.get("notetext", ""),
                "created":      n.get("createdon", ""),
                "last_modified": n.get("modifiedon", ""),
                "has_attachment": bool(n.get("filename")),
                "attachment_name": n.get("filename", ""),
            }
            for n in notes
        ],
    }


def add_note(regarding_id: str, regarding_type: str, text: str, subject: str = "Note") -> dict:
    """
    Add a note to a CRM record.

    regarding_id:   ID of the contact, lead, account, or opportunity
    regarding_type: "contact", "lead", "account", or "opportunity"
    text:           the body of the note
    subject:        short title for the note (default "Note")

    Returns confirmation the note was saved.
    """
    entity_type_map = {
        "contact":     "contacts",
        "lead":        "leads",
        "account":     "accounts",
        "opportunity": "opportunities",
    }

    data = {
        "subject":  subject,
        "notetext": text,
    }

    entity_set = entity_type_map.get(regarding_type, "contacts")
    data[f"objectid_{regarding_type}@odata.bind"] = f"/{entity_set}({regarding_id})"

    result = crm_post("annotations", data)
    return {"saved": True, "subject": subject, "regarding_id": regarding_id, "record": result}


def get_activity_timeline(regarding_id: str, regarding_type: str = "contact", limit: int = 30) -> dict:
    """
    Get a full activity timeline for a CRM record — all tasks, calls,
    appointments, and notes in chronological order.

    regarding_id:   ID of the record
    regarding_type: "contact", "lead", "account", or "opportunity"
    limit:          max items per activity type (default 30)

    Returns a unified, time-sorted timeline of all activity.
    """
    timeline = []

    # Fetch all activity types in parallel
    task_filter   = f"_regardingobjectid_value eq '{regarding_id}'"
    call_filter   = f"_regardingobjectid_value eq '{regarding_id}'"
    appt_filter   = f"_regardingobjectid_value eq '{regarding_id}'"
    note_filter   = f"_objectid_value eq '{regarding_id}'"

    try:
        tasks = crm_get("tasks", {
            "$top": limit,
            "$select": "subject,statecode,scheduledend,createdon",
            "$filter": task_filter,
            "$orderby": "createdon desc",
        }).get("value", [])
        for t in tasks:
            timeline.append({
                "type":   "Task",
                "date":   t.get("scheduledend") or t.get("createdon", ""),
                "subject": t.get("subject", "Task"),
                "status": "Completed" if t.get("statecode") == 1 else "Open",
            })
    except Exception:
        pass

    try:
        calls = crm_get("phonecalls", {
            "$top": limit,
            "$select": "subject,directioncode,statecode,createdon",
            "$filter": call_filter,
            "$orderby": "createdon desc",
        }).get("value", [])
        for c in calls:
            timeline.append({
                "type":    "Phone Call",
                "date":    c.get("createdon", ""),
                "subject": c.get("subject", "Phone Call"),
                "status":  ("Outbound" if c.get("directioncode") else "Inbound") +
                           (" (Completed)" if c.get("statecode") == 1 else ""),
            })
    except Exception:
        pass

    try:
        appts = crm_get("appointments", {
            "$top": limit,
            "$select": "subject,scheduledstart,scheduledend,statecode",
            "$filter": appt_filter,
            "$orderby": "scheduledstart desc",
        }).get("value", [])
        for a in appts:
            timeline.append({
                "type":    "Appointment",
                "date":    a.get("scheduledstart", ""),
                "subject": a.get("subject", "Appointment"),
                "status":  "Completed" if a.get("statecode") == 1 else "Scheduled",
            })
    except Exception:
        pass

    try:
        notes = crm_get("annotations", {
            "$top": limit,
            "$select": "subject,notetext,createdon",
            "$filter": note_filter,
            "$orderby": "createdon desc",
        }).get("value", [])
        for n in notes:
            timeline.append({
                "type":    "Note",
                "date":    n.get("createdon", ""),
                "subject": n.get("subject", "Note"),
                "status":  n.get("notetext", "")[:100] + ("..." if len(n.get("notetext", "")) > 100 else ""),
            })
    except Exception:
        pass

    # Sort all activity by date descending
    timeline.sort(key=lambda x: x.get("date", ""), reverse=True)

    return {
        "regarding_id":   regarding_id,
        "regarding_type": regarding_type,
        "total_activities": len(timeline),
        "timeline": timeline,
    }
