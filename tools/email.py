# ============================================================
# tools/email.py — Email Sending via Dynamics 365
# ============================================================
# Send emails to contacts, leads, or accounts through the CRM.
# All sent emails are logged as activities on the record.
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
from config.crm_connection import crm_get, crm_post, crm_action, crm_patch

_LAST_ACTIVITY_FIELD = "tyr_lastactivitydate"

def _stamp_last_activity(entity_collection: str, record_id: str):
    """Silently update tyr_lastactivitydate on a record. Swallows errors so it never blocks sends."""
    try:
        crm_patch(entity_collection, record_id, {_LAST_ACTIVITY_FIELD: date.today().isoformat()})
    except Exception:
        pass


def send_email_to_contact(contact_id: str, subject: str, body: str) -> dict:
    """
    Send an email to a single contact and log it in the CRM.

    contact_id: the unique ID of the contact to email
    subject: email subject line
    body: email body text (plain text)

    The email is sent from the CRM user and logged as an activity on the contact record.
    """
    # Fetch the contact to get their email address
    contact = crm_get(f"contacts({contact_id})", {"$select": "fullname,emailaddress1"})
    email_address = contact.get("emailaddress1")
    name = contact.get("fullname", "Contact")

    if not email_address:
        return {"error": f"Contact '{name}' has no email address on file"}

    # Build the email activity payload
    email_data = {
        "subject": subject,
        "description": body,
        "email_activity_parties": [
            {
                "participationtypemask": 2,  # 2 = To
                "partyid_contact@odata.bind": f"/contacts({contact_id})",
            }
        ],
    }

    result = crm_post("emails", email_data)

    # Send the email via SendEmail action
    email_id = result.get("activityid") or result.get("emailid")
    if email_id:
        try:
            crm_action("SendEmail", {
                "EmailId": email_id,
                "IssueSend": True,
                "TrackingToken": "",
            })
        except Exception as e:
            return {
                "success": False,
                "warning": f"Email created but send failed: {e}",
                "email_id": email_id,
                "recipient": name,
                "email_address": email_address,
            }

    _stamp_last_activity("contacts", contact_id)
    return {
        "success": True,
        "recipient": name,
        "email_address": email_address,
        "subject": subject,
        "email_id": email_id,
        "message": f"Email sent to {name} ({email_address})",
    }


def send_email_to_lead(lead_id: str, subject: str, body: str) -> dict:
    """
    Send an email to a lead and log it in the CRM.

    lead_id: the unique ID of the lead
    subject: email subject line
    body: email body text
    """
    lead = crm_get(f"leads({lead_id})", {"$select": "fullname,emailaddress1"})
    email_address = lead.get("emailaddress1")
    name = lead.get("fullname", "Lead")

    if not email_address:
        return {"error": f"Lead '{name}' has no email address on file"}

    email_data = {
        "subject": subject,
        "description": body,
        "email_activity_parties": [
            {
                "participationtypemask": 2,
                "partyid_lead@odata.bind": f"/leads({lead_id})",
            }
        ],
    }

    result = crm_post("emails", email_data)
    email_id = result.get("activityid") or result.get("emailid")

    if email_id:
        try:
            crm_action("SendEmail", {
                "EmailId": email_id,
                "IssueSend": True,
                "TrackingToken": "",
            })
        except Exception as e:
            return {
                "success": False,
                "warning": f"Email created but send failed: {e}",
                "email_id": email_id,
                "recipient": name,
            }

    _stamp_last_activity("leads", lead_id)
    return {
        "success": True,
        "recipient": name,
        "email_address": email_address,
        "subject": subject,
        "email_id": email_id,
        "message": f"Email sent to lead {name} ({email_address})",
    }


def send_bulk_email(entity: str, filter_criteria: str, subject: str, body: str, preview_only: bool = False) -> dict:
    """
    Send the same email to multiple contacts or leads matching a filter.

    entity: "contact" or "lead"
    filter_criteria: OData filter, e.g. "statecode eq 0 and contains(companyname,'Acme')"
    subject: email subject
    body: email body text
    preview_only: if True, show who would receive the email WITHOUT sending

    Always use preview_only=True first to confirm the recipient list.
    """
    if entity.lower() == "contact":
        params = {
            "$select": "contactid,fullname,emailaddress1",
            "$filter": f"({filter_criteria}) and emailaddress1 ne null",
            "$top": 200,
        }
        records = crm_get("contacts", params).get("value", [])
        id_field = "contactid"
        send_fn_name = "send_email_to_contact"
    elif entity.lower() == "lead":
        params = {
            "$select": "leadid,fullname,emailaddress1",
            "$filter": f"({filter_criteria}) and emailaddress1 ne null",
            "$top": 200,
        }
        records = crm_get("leads", params).get("value", [])
        id_field = "leadid"
        send_fn_name = "send_email_to_lead"
    else:
        return {"error": "entity must be 'contact' or 'lead'"}

    if not records:
        return {"message": "No records matched the filter (or none have email addresses)", "count": 0}

    recipients = [
        {"id": r.get(id_field), "name": r.get("fullname", ""), "email": r.get("emailaddress1", "")}
        for r in records
    ]

    if preview_only:
        return {
            "preview_only": True,
            "entity": entity,
            "recipient_count": len(recipients),
            "subject": subject,
            "recipients": recipients,
            "message": f"Would send to {len(recipients)} {entity}(s). Set preview_only=False to send.",
        }

    # Send to each recipient
    sent = []
    failed = []
    for r in records:
        try:
            if entity.lower() == "contact":
                result = send_email_to_contact(r[id_field], subject, body)
            else:
                result = send_email_to_lead(r[id_field], subject, body)

            if result.get("success"):
                sent.append({"name": r.get("fullname", ""), "email": r.get("emailaddress1", "")})
            else:
                failed.append({"name": r.get("fullname", ""), "error": result.get("error") or result.get("warning", "Unknown")})
        except Exception as e:
            failed.append({"name": r.get("fullname", ""), "error": str(e)})

    return {
        "success": True,
        "entity": entity,
        "total_recipients": len(records),
        "sent": len(sent),
        "failed": len(failed),
        "failed_details": failed,
        "subject": subject,
        "message": f"Sent {len(sent)} emails, {len(failed)} failed",
    }


def get_email_history(contact_id: str = None, lead_id: str = None, limit: int = 20) -> dict:
    """
    Get the email history for a contact or lead.

    contact_id: the contact's ID (provide either this or lead_id)
    lead_id: the lead's ID
    limit: max emails to return (default 20)
    """
    if contact_id:
        params = {
            "$select": "activityid,subject,statecode,createdon,modifiedon",
            "$filter": f"statecode ne 2",
            "$top": limit,
            "$orderby": "createdon desc",
        }
        result = crm_get(f"contacts({contact_id})/Contact_Emails", params)
        record_type = "contact"
        record_id = contact_id
    elif lead_id:
        params = {
            "$select": "activityid,subject,statecode,createdon",
            "$filter": "statecode ne 2",
            "$top": limit,
            "$orderby": "createdon desc",
        }
        result = crm_get(f"leads({lead_id})/Lead_Emails", params)
        record_type = "lead"
        record_id = lead_id
    else:
        return {"error": "Provide either contact_id or lead_id"}

    emails = result.get("value", [])
    status_labels = {0: "Open", 1: "Completed", 2: "Canceled", 3: "Pending Send"}

    return {
        "record_type": record_type,
        "record_id": record_id,
        "total_emails": len(emails),
        "emails": [
            {
                "id": e.get("activityid"),
                "subject": e.get("subject", "(no subject)"),
                "status": status_labels.get(e.get("statecode"), "Unknown"),
                "sent_on": e.get("createdon", ""),
            }
            for e in emails
        ],
    }
