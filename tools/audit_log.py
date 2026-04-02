# ============================================================
# tools/audit_log.py — Audit Log Tools
# ============================================================
# The audit log records every change made to your CRM —
# who changed what, when, and what the old/new values were.
#
# This is essential for:
#   - Investigating data quality issues
#   - Tracking who made changes and when
#   - Compliance and accountability
#   - Debugging workflow or automation problems
#
# NOTE: Auditing must be enabled in your Dynamics 365 org
# (Settings → Auditing → Start Log Auditing) for records
# to appear here.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get


def get_audit_history(record_id: str, record_type: str = "contact", limit: int = 50) -> dict:
    """
    Get the full change history for a specific CRM record.

    record_id:   the ID of the record to inspect
    record_type: the type of record — "contact", "lead", "account",
                 "opportunity", or "workflow"
    limit:       max number of audit entries to return (default 50)

    Returns a timeline of every change made to the record,
    including who made it and what was changed.
    """
    entity_type_map = {
        "contact":     "contacts",
        "lead":        "leads",
        "account":     "accounts",
        "opportunity": "opportunities",
        "workflow":    "workflows",
    }

    entity_set = entity_type_map.get(record_type, record_type)

    # Dynamics 365 audit history endpoint for a specific record
    endpoint = f"{entity_set}({record_id})/Microsoft.Dynamics.CRM.RetrieveRecordChangeHistory"

    try:
        result = crm_get(endpoint, {"PagingInfo": f"PageNumber=1,Count={limit}"})
    except Exception as e:
        # Try the standard audit query as fallback
        return _get_audit_via_query(record_id, limit)

    audit_details = result.get("AuditDetailCollection", {}).get("AuditDetails", [])

    operation_map = {1: "Created", 2: "Updated", 3: "Deleted", 4: "Accessed"}

    entries = []
    for entry in audit_details:
        audit = entry.get("AuditRecord", {})
        changed_fields = []

        # Extract old/new values if available
        old_values = entry.get("OldValue", {}).get("Attributes", [])
        new_values = entry.get("NewValue", {}).get("Attributes", [])

        old_map = {a.get("key"): a.get("value") for a in old_values} if isinstance(old_values, list) else {}
        new_map = {a.get("key"): a.get("value") for a in new_values} if isinstance(new_values, list) else {}

        all_keys = set(list(old_map.keys()) + list(new_map.keys()))
        for key in all_keys:
            changed_fields.append({
                "field":     key,
                "old_value": str(old_map.get(key, ""))[:200],
                "new_value": str(new_map.get(key, ""))[:200],
            })

        entries.append({
            "date":           audit.get("createdon", ""),
            "operation":      operation_map.get(audit.get("operation"), "Unknown"),
            "changed_by":     audit.get("_userid_value@OData.Community.Display.V1.FormattedValue", "Unknown user"),
            "changed_fields": changed_fields,
        })

    return {
        "record_id":    record_id,
        "record_type":  record_type,
        "total_entries": len(entries),
        "audit_history": entries,
    }


def _get_audit_via_query(record_id: str, limit: int = 50) -> dict:
    """
    Fallback: query the audits entity directly for a record.
    """
    params = {
        "$top": limit,
        "$select": "auditid,createdon,operation,_userid_value,changedata,objecttypecode",
        "$filter": f"_objectid_value eq '{record_id}'",
        "$orderby": "createdon desc",
        "$expand": "userid($select=fullname)",
    }

    try:
        result = crm_get("audits", params)
    except Exception as e:
        return {
            "error": f"Could not retrieve audit log: {str(e)}",
            "hint": "Auditing may not be enabled. Go to Settings → Auditing → Start Log Auditing.",
        }

    audits = result.get("value", [])
    operation_map = {1: "Created", 2: "Updated", 3: "Deleted", 4: "Accessed"}

    return {
        "record_id":    record_id,
        "total_entries": len(audits),
        "audit_history": [
            {
                "date":       a.get("createdon", ""),
                "operation":  operation_map.get(a.get("operation"), "Unknown"),
                "changed_by": a.get("_userid_value@OData.Community.Display.V1.FormattedValue", "Unknown user"),
                "raw_changes": str(a.get("changedata", ""))[:500],
            }
            for a in audits
        ],
    }


def get_recent_changes(entity_type: str = "contact", hours: int = 24, limit: int = 100) -> dict:
    """
    Get all recent changes across a record type in the last N hours.

    entity_type: "contact", "lead", "account", or "opportunity"
    hours:       how far back to look (default 24 hours)
    limit:       max records to return (default 100)

    Returns a summary of all changes made recently — useful for
    daily audits and spotting unexpected bulk changes.
    """
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    entity_code_map = {
        "contact":     2,
        "lead":        4,
        "account":     1,
        "opportunity": 3,
    }

    object_type_code = entity_code_map.get(entity_type, 2)

    params = {
        "$top": limit,
        "$select": "auditid,createdon,operation,_userid_value,_objectid_value,objecttypecode",
        "$filter": f"createdon ge {since} and objecttypecode eq {object_type_code}",
        "$orderby": "createdon desc",
    }

    try:
        result = crm_get("audits", params)
    except Exception as e:
        return {
            "error": f"Could not retrieve audit log: {str(e)}",
            "hint": "Auditing may not be enabled in this Dynamics 365 org.",
        }

    audits = result.get("value", [])
    operation_map = {1: "Created", 2: "Updated", 3: "Deleted", 4: "Accessed"}

    # Summarise by user
    by_user = {}
    for a in audits:
        user = a.get("_userid_value@OData.Community.Display.V1.FormattedValue", "Unknown")
        op   = operation_map.get(a.get("operation"), "Unknown")
        key  = f"{user}"
        if key not in by_user:
            by_user[key] = {"user": user, "creates": 0, "updates": 0, "deletes": 0, "total": 0}
        by_user[key]["total"] += 1
        if op == "Created":   by_user[key]["creates"] += 1
        elif op == "Updated": by_user[key]["updates"] += 1
        elif op == "Deleted": by_user[key]["deletes"] += 1

    return {
        "entity_type":     entity_type,
        "period_hours":    hours,
        "total_changes":   len(audits),
        "activity_by_user": list(by_user.values()),
        "recent_changes": [
            {
                "date":       a.get("createdon", ""),
                "operation":  operation_map.get(a.get("operation"), "Unknown"),
                "changed_by": a.get("_userid_value@OData.Community.Display.V1.FormattedValue", "Unknown"),
                "record_id":  a.get("_objectid_value", ""),
            }
            for a in audits[:50]
        ],
    }


def get_deleted_records(entity_type: str = "contact", limit: int = 50) -> dict:
    """
    Find recently deleted records of a given type.

    entity_type: "contact", "lead", "account", or "opportunity"
    limit:       max records to return (default 50)

    Returns a list of deleted records — useful for recovering
    accidentally deleted data.
    """
    entity_code_map = {
        "contact":     2,
        "lead":        4,
        "account":     1,
        "opportunity": 3,
    }

    object_type_code = entity_code_map.get(entity_type, 2)

    params = {
        "$top": limit,
        "$select": "auditid,createdon,_userid_value,_objectid_value",
        "$filter": f"operation eq 3 and objecttypecode eq {object_type_code}",
        "$orderby": "createdon desc",
    }

    try:
        result = crm_get("audits", params)
    except Exception as e:
        return {
            "error": f"Could not retrieve audit log: {str(e)}",
            "hint": "Auditing may not be enabled in this Dynamics 365 org.",
        }

    audits = result.get("value", [])

    return {
        "entity_type":    entity_type,
        "total_deleted":  len(audits),
        "deleted_records": [
            {
                "record_id":  a.get("_objectid_value", ""),
                "deleted_on": a.get("createdon", ""),
                "deleted_by": a.get("_userid_value@OData.Community.Display.V1.FormattedValue", "Unknown"),
            }
            for a in audits
        ],
    }


def check_audit_status() -> dict:
    """
    Check whether auditing is enabled in this Dynamics 365 organization.

    Returns the current audit configuration and what entity types
    are being tracked.
    """
    try:
        # Check org settings for audit flags
        org = crm_get("organizations", {
            "$top": 1,
            "$select": "isauditenabled,auditretentionperiodv2",
        })
        org_data = org.get("value", [{}])[0]

        return {
            "auditing_enabled": org_data.get("isauditenabled", False),
            "retention_days":   org_data.get("auditretentionperiodv2", "Unknown"),
            "message": (
                "Auditing is active — audit log tools will work correctly."
                if org_data.get("isauditenabled")
                else "Auditing is DISABLED. Go to Settings → Auditing → Start Log Auditing to enable it."
            ),
        }
    except Exception as e:
        return {"error": str(e), "hint": "Could not check audit settings."}
