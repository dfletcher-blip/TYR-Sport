# ============================================================
# tools/reports.py — CRM Reports
# ============================================================
# List, run, and summarize reports stored in Dynamics 365.
# Also includes on-the-fly data quality and pipeline reports
# built directly from live CRM data.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get


def list_reports(category: str = "all") -> dict:
    """
    List reports available in the CRM.

    category: "all", "account", "contact", "lead", "opportunity", or "custom"
    """
    params = {
        "$top": 100,
        "$select": "reportid,name,description,reporttypecode,ownerid,createdon,modifiedon",
        "$orderby": "name asc",
    }

    category_map = {
        "account":     "reporttypecode eq 1",
        "contact":     "reporttypecode eq 2",
        "lead":        "reporttypecode eq 3",
        "opportunity": "reporttypecode eq 4",
        "custom":      "iscustomreport eq true",
    }
    if category.lower() in category_map:
        params["$filter"] = category_map[category.lower()]

    result = crm_get("reports", params)
    reports = result.get("value", [])

    type_labels = {1: "Account", 2: "Contact", 3: "Lead", 4: "Opportunity", 5: "Quote", 6: "Order"}

    return {
        "total_found": len(reports),
        "reports": [
            {
                "id": r.get("reportid"),
                "name": r.get("name", "Unnamed"),
                "description": r.get("description", ""),
                "type": type_labels.get(r.get("reporttypecode"), "Other"),
                "last_modified": r.get("modifiedon", ""),
            }
            for r in reports
        ],
    }


def get_data_quality_report() -> dict:
    """
    Generate a live data quality report across contacts, leads, and accounts.
    Shows missing fields, inactive records, and completeness percentages.
    """
    def pct(part, total):
        return f"{part / total * 100:.1f}%" if total else "0%"

    # Contacts
    contacts = crm_get("contacts", {"$select": "contactid,statecode,emailaddress1,telephone1", "$top": 5000}).get("value", [])
    c_total   = len(contacts)
    c_active  = sum(1 for c in contacts if c.get("statecode") == 0)
    c_no_email = sum(1 for c in contacts if not c.get("emailaddress1"))
    c_no_phone = sum(1 for c in contacts if not c.get("telephone1"))

    # Leads
    leads = crm_get("leads", {"$select": "leadid,statecode,emailaddress1,companyname", "$top": 5000}).get("value", [])
    l_total    = len(leads)
    l_open     = sum(1 for l in leads if l.get("statecode") == 0)
    l_no_email = sum(1 for l in leads if not l.get("emailaddress1"))
    l_no_co    = sum(1 for l in leads if not l.get("companyname"))

    # Accounts
    accounts = crm_get("accounts", {"$select": "accountid,statecode,emailaddress1,telephone1,websiteurl", "$top": 5000}).get("value", [])
    a_total    = len(accounts)
    a_active   = sum(1 for a in accounts if a.get("statecode") == 0)
    a_no_email = sum(1 for a in accounts if not a.get("emailaddress1"))
    a_no_phone = sum(1 for a in accounts if not a.get("telephone1"))
    a_no_web   = sum(1 for a in accounts if not a.get("websiteurl"))

    return {
        "report_name": "Data Quality Report",
        "contacts": {
            "total": c_total,
            "active": c_active,
            "missing_email": {"count": c_no_email, "percent": pct(c_no_email, c_total)},
            "missing_phone": {"count": c_no_phone, "percent": pct(c_no_phone, c_total)},
        },
        "leads": {
            "total": l_total,
            "open": l_open,
            "missing_email":   {"count": l_no_email, "percent": pct(l_no_email, l_total)},
            "missing_company": {"count": l_no_co,    "percent": pct(l_no_co, l_total)},
        },
        "accounts": {
            "total": a_total,
            "active": a_active,
            "missing_email":   {"count": a_no_email, "percent": pct(a_no_email, a_total)},
            "missing_phone":   {"count": a_no_phone, "percent": pct(a_no_phone, a_total)},
            "missing_website": {"count": a_no_web,   "percent": pct(a_no_web, a_total)},
        },
    }


def get_pipeline_report() -> dict:
    """
    Generate a live pipeline report showing opportunities by stage, owner, and value.
    """
    params = {
        "$select": "opportunityid,name,estimatedvalue,closeprobability,statecode,estimatedclosedate",
        "$expand": "ownerid($select=fullname)",
        "$filter": "statecode eq 0",
        "$top": 500,
    }
    opps = crm_get("opportunities", params).get("value", [])

    total_value = sum(o.get("estimatedvalue") or 0 for o in opps)
    weighted    = sum((o.get("estimatedvalue") or 0) * (o.get("closeprobability") or 0) / 100 for o in opps)

    # By owner
    owner_map: dict = {}
    for o in opps:
        owner = (o.get("ownerid") or {}).get("fullname", "Unassigned")
        if owner not in owner_map:
            owner_map[owner] = {"count": 0, "value": 0}
        owner_map[owner]["count"] += 1
        owner_map[owner]["value"] += o.get("estimatedvalue") or 0
    by_owner = sorted(owner_map.items(), key=lambda x: x[1]["value"], reverse=True)

    # By probability bucket
    buckets = {"0-25%": 0, "26-50%": 0, "51-75%": 0, "76-100%": 0}
    for o in opps:
        p = o.get("closeprobability") or 0
        if p <= 25:   buckets["0-25%"] += 1
        elif p <= 50: buckets["26-50%"] += 1
        elif p <= 75: buckets["51-75%"] += 1
        else:         buckets["76-100%"] += 1

    return {
        "report_name": "Pipeline Report",
        "open_opportunities": len(opps),
        "total_pipeline_value": round(total_value, 2),
        "weighted_pipeline_value": round(weighted, 2),
        "by_owner": [{"owner": o, "count": d["count"], "value": round(d["value"], 2)} for o, d in by_owner],
        "by_probability": buckets,
    }


def get_lead_source_report() -> dict:
    """
    Report showing lead volume and conversion rates broken down by source.
    """
    params = {"$select": "leadid,statecode,leadsourcecode", "$top": 5000}
    leads = crm_get("leads", params).get("value", [])

    source_labels = {
        1: "Advertisement", 2: "Employee Referral", 3: "External Referral",
        4: "Partner", 5: "Public Relations", 6: "Seminar", 7: "Trade Show",
        8: "Web", 9: "Word of Mouth", 10: "Other",
    }

    source_data: dict = {}
    for l in leads:
        src = source_labels.get(l.get("leadsourcecode"), "Unknown")
        if src not in source_data:
            source_data[src] = {"total": 0, "qualified": 0, "disqualified": 0, "open": 0}
        source_data[src]["total"] += 1
        state = l.get("statecode")
        if state == 0:   source_data[src]["open"] += 1
        elif state == 1: source_data[src]["qualified"] += 1
        elif state == 2: source_data[src]["disqualified"] += 1

    rows = []
    for src, d in sorted(source_data.items(), key=lambda x: x[1]["total"], reverse=True):
        conv = f"{d['qualified'] / d['total'] * 100:.1f}%" if d["total"] else "0%"
        rows.append({"source": src, "conversion_rate": conv, **d})

    return {
        "report_name": "Lead Source Report",
        "total_leads": len(leads),
        "by_source": rows,
    }


def get_activity_report(days: int = 30) -> dict:
    """
    Show recent CRM activity: emails, calls, and tasks in the last N days.

    days: how far back to look (default 30)
    """
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def fetch(entity, label):
        r = crm_get(entity, {
            "$select": "activityid,subject,statecode,createdon",
            "$filter": f"createdon ge {since}",
            "$top": 500,
        })
        items = r.get("value", [])
        return {"entity": label, "count": len(items), "completed": sum(1 for i in items if i.get("statecode") == 1)}

    emails = fetch("emails", "Emails")
    calls  = fetch("phonecalls", "Phone Calls")
    tasks  = fetch("tasks", "Tasks")

    return {
        "report_name": f"Activity Report — Last {days} Days",
        "period_days": days,
        "activities": [emails, calls, tasks],
        "total_activities": emails["count"] + calls["count"] + tasks["count"],
    }
