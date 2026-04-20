# ============================================================
# tools/leads.py — Lead Management
# ============================================================

import sys, os, csv, json, uuid, time, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_patch, crm_post, crm_action, get_access_token


def search_leads(search_term: str = "", status: str = "open", limit: int = 50) -> dict:
    """
    Search for leads in the CRM.

    search_term: name, email, or company to search for (leave blank for all)
    status: "open", "qualified", "disqualified", or "all"
    limit: max results to return (default 50)
    """
    status_filter = {
        "open":           "statecode eq 0",
        "qualified":      "statecode eq 1",
        "disqualified":   "statecode eq 2",
        "all":            None,
    }.get(status.lower(), "statecode eq 0")

    params = {
        "$top": limit,
        "$select": "leadid,fullname,emailaddress1,telephone1,jobtitle,companyname,subject,statecode,leadsourcecode,createdon,modifiedon",
        "$expand": "ownerid($select=fullname)",
        "$orderby": "modifiedon desc",
    }

    filters = []
    if status_filter:
        filters.append(status_filter)
    if search_term:
        filters.append(
            f"(contains(fullname,'{search_term}') or "
            f"contains(emailaddress1,'{search_term}') or "
            f"contains(companyname,'{search_term}'))"
        )

    if filters:
        params["$filter"] = " and ".join(filters)

    result = crm_get("leads", params)
    leads = result.get("value", [])

    source_labels = {
        1: "Advertisement", 2: "Employee Referral", 3: "External Referral",
        4: "Partner", 5: "Public Relations", 6: "Seminar", 7: "Trade Show",
        8: "Web", 9: "Word of Mouth", 10: "Other",
    }
    status_labels = {0: "Open", 1: "Qualified", 2: "Disqualified"}

    return {
        "total_found": len(leads),
        "leads": [
            {
                "id": l.get("leadid"),
                "name": l.get("fullname", "No name"),
                "email": l.get("emailaddress1", ""),
                "phone": l.get("telephone1", ""),
                "job_title": l.get("jobtitle", ""),
                "company": l.get("companyname", ""),
                "subject": l.get("subject", ""),
                "source": source_labels.get(l.get("leadsourcecode"), "Unknown"),
                "status": status_labels.get(l.get("statecode"), "Unknown"),
                "owner": (l.get("ownerid") or {}).get("fullname", ""),
                "last_modified": l.get("modifiedon", ""),
            }
            for l in leads
        ],
    }


def get_lead_details(lead_id: str) -> dict:
    """
    Get all details for a specific lead.

    lead_id: the unique ID of the lead
    """
    params = {"$expand": "ownerid($select=fullname)"}
    l = crm_get(f"leads({lead_id})", params)

    status_labels = {0: "Open", 1: "Qualified", 2: "Disqualified"}

    return {
        "id": l.get("leadid"),
        "name": l.get("fullname", ""),
        "email": l.get("emailaddress1", ""),
        "phone": l.get("telephone1", ""),
        "mobile": l.get("mobilephone", ""),
        "job_title": l.get("jobtitle", ""),
        "company": l.get("companyname", ""),
        "subject": l.get("subject", ""),
        "description": l.get("description", ""),
        "status": status_labels.get(l.get("statecode"), "Unknown"),
        "owner": (l.get("ownerid") or {}).get("fullname", ""),
        "address": {
            "street": l.get("address1_line1", ""),
            "city": l.get("address1_city", ""),
            "state": l.get("address1_stateorprovince", ""),
            "zip": l.get("address1_postalcode", ""),
        },
        "created": l.get("createdon", ""),
        "last_modified": l.get("modifiedon", ""),
    }


def update_lead(lead_id: str, updates: dict) -> dict:
    """
    Update a lead's information.

    lead_id: the unique ID of the lead
    updates: fields to change, e.g.:
             {"emailaddress1": "new@email.com", "companyname": "Acme Corp"}

    Common fields:
      fullname        → full name
      emailaddress1   → email
      telephone1      → phone
      jobtitle        → job title
      companyname     → company name
      subject         → lead topic/subject
      description     → notes
    """
    crm_patch("leads", lead_id, updates)
    return {
        "success": True,
        "lead_id": lead_id,
        "fields_updated": list(updates.keys()),
        "message": f"Lead {lead_id} updated successfully",
    }


def qualify_lead(lead_id: str) -> dict:
    """
    Qualify a lead — marks it as qualified and creates a contact/opportunity.

    lead_id: the unique ID of the lead to qualify
    """
    payload = {
        "LeadId": {"leadid": lead_id, "@odata.type": "Microsoft.Dynamics.CRM.lead"},
        "Status": 3,  # Qualified
        "CreateContact": True,
        "CreateOpportunity": True,
        "CreateAccount": True,
    }
    result = crm_action("QualifyLead", payload)
    return {
        "success": True,
        "lead_id": lead_id,
        "message": "Lead qualified. Contact and opportunity created.",
        "result": result,
    }


def get_lead_summary() -> dict:
    """
    Get a high-level summary of all leads: counts by status and source.
    """
    params = {"$select": "leadid,statecode,leadsourcecode", "$top": 5000}
    leads = crm_get("leads", params).get("value", [])

    total        = len(leads)
    open_leads   = sum(1 for l in leads if l.get("statecode") == 0)
    qualified    = sum(1 for l in leads if l.get("statecode") == 1)
    disqualified = sum(1 for l in leads if l.get("statecode") == 2)

    source_labels = {
        1: "Advertisement", 2: "Employee Referral", 3: "External Referral",
        4: "Partner", 5: "Public Relations", 6: "Seminar", 7: "Trade Show",
        8: "Web", 9: "Word of Mouth", 10: "Other",
    }
    source_counts: dict = {}
    for l in leads:
        src = source_labels.get(l.get("leadsourcecode"), "Unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    top_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_leads": total,
        "open": open_leads,
        "qualified": qualified,
        "disqualified": disqualified,
        "top_sources": [{"source": s, "count": c} for s, c in top_sources],
    }


def bulk_import_leads(file_path: str, preview_only: bool = True) -> dict:
    """
    Import leads from a CSV file into the CRM.

    file_path:    absolute or relative path to the CSV file
    preview_only: if True (default), show what would be imported without
                  creating anything. Set to False to actually create the leads.

    Supported CSV columns (case-insensitive, spaces/underscores flexible):
      First Name / Last Name / Full Name
      Email / Email Address
      Phone / Phone Number
      Company / Company Name / Account
      Job Title / Title
      Subject / Topic  (defaults to "Lead - <company>" if omitted)
      Website
      City / State / Zip / Postal Code / Country
      Description / Notes
      Lead Source  (Advertisement, Web, Trade Show, Referral, etc.)
    """
    DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

    # Column name normaliser → Dynamics 365 field
    COLUMN_MAP = {
        "firstname":       "firstname",
        "first name":      "firstname",
        "first_name":      "firstname",
        "lastname":        "lastname",
        "last name":       "lastname",
        "last_name":       "lastname",
        "fullname":        "fullname",
        "full name":       "fullname",
        "full_name":       "fullname",
        "name":            "fullname",
        "email":           "emailaddress1",
        "email address":   "emailaddress1",
        "emailaddress":    "emailaddress1",
        "emailaddress1":   "emailaddress1",
        "phone":           "telephone1",
        "phone number":    "telephone1",
        "telephone":       "telephone1",
        "mobile":          "mobilephone",
        "cell":            "mobilephone",
        "company":         "companyname",
        "company name":    "companyname",
        "companyname":     "companyname",
        "account":         "companyname",
        "organization":    "companyname",
        "jobtitle":        "jobtitle",
        "job title":       "jobtitle",
        "title":           "jobtitle",
        "subject":         "subject",
        "topic":           "subject",
        "lead topic":      "subject",
        "website":         "websiteurl",
        "websiteurl":      "websiteurl",
        "url":             "websiteurl",
        "city":            "address1_city",
        "state":           "address1_stateorprovince",
        "province":        "address1_stateorprovince",
        "zip":             "address1_postalcode",
        "postal code":     "address1_postalcode",
        "postalcode":      "address1_postalcode",
        "zip code":        "address1_postalcode",
        "country":         "address1_country",
        "description":     "description",
        "notes":           "description",
        "note":            "description",
        "leadsource":      "leadsourcecode",
        "lead source":     "leadsourcecode",
        "source":          "leadsourcecode",
    }

    LEAD_SOURCE_MAP = {
        "advertisement": 1, "ad": 1,
        "employee referral": 2,
        "external referral": 3, "referral": 3,
        "partner": 4,
        "public relations": 5, "pr": 5,
        "seminar": 6,
        "trade show": 7, "tradeshow": 7,
        "web": 8, "website": 8, "online": 8,
        "word of mouth": 9,
        "other": 10,
    }

    if not os.path.isfile(file_path):
        return {"success": False, "error": f"File not found: {file_path}"}

    # Read CSV
    rows = []
    try:
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            raw_headers = reader.fieldnames or []
            for row in reader:
                rows.append(dict(row))
    except Exception as e:
        return {"success": False, "error": f"Could not read CSV: {e}"}

    if not rows:
        return {"success": False, "error": "CSV file is empty."}

    # Map CSV headers to CRM fields
    header_to_field = {}
    unmapped = []
    for h in raw_headers:
        key = h.strip().lower().replace("_", " ")
        crm_field = COLUMN_MAP.get(key) or COLUMN_MAP.get(h.strip().lower())
        if crm_field:
            header_to_field[h] = crm_field
        else:
            unmapped.append(h)

    # Build lead payloads
    leads_to_create = []
    skipped = []
    for i, row in enumerate(rows, 1):
        payload = {}
        for csv_col, crm_field in header_to_field.items():
            val = (row.get(csv_col) or "").strip()
            if not val:
                continue
            if crm_field == "leadsourcecode":
                val = LEAD_SOURCE_MAP.get(val.lower(), 10)
            payload[crm_field] = val

        # Build fullname from parts if not provided
        if "fullname" not in payload:
            first = payload.get("firstname", "")
            last  = payload.get("lastname", "")
            if first or last:
                payload["fullname"] = f"{first} {last}".strip()

        # subject is required in Dynamics 365
        if "subject" not in payload:
            company = payload.get("companyname", "")
            name    = payload.get("fullname", f"Row {i}")
            payload["subject"] = f"Lead - {company}" if company else f"Lead - {name}"

        if not payload.get("fullname") and not payload.get("firstname"):
            skipped.append({"row": i, "reason": "No name found"})
            continue

        leads_to_create.append(payload)

    if preview_only:
        sample = leads_to_create[:5]
        return {
            "mode": "PREVIEW — no records created",
            "file": file_path,
            "total_rows": len(rows),
            "leads_to_create": len(leads_to_create),
            "skipped_rows": len(skipped),
            "column_mapping": header_to_field,
            "unmapped_columns": unmapped,
            "sample_records": sample,
            "next_step": "Call bulk_import_leads again with preview_only=False to create the leads.",
        }

    # Batch create via OData $batch
    BATCH_SIZE = 20
    token_cache = {"value": None, "expires": 0}

    def get_hdrs():
        if not token_cache["value"] or time.time() >= token_cache["expires"]:
            token_cache["value"] = get_access_token()
            token_cache["expires"] = time.time() + 3000
        return {
            "Authorization": f"Bearer {token_cache['value']}",
            "OData-MaxVersion": "4.0", "OData-Version": "4.0",
            "Accept": "application/json", "Content-Type": "application/json",
        }

    session = requests.Session()
    created = errors = 0
    error_samples = []
    total_batches = (len(leads_to_create) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, start in enumerate(range(0, len(leads_to_create), BATCH_SIZE), 1):
        batch = leads_to_create[start:start + BATCH_SIZE]
        boundary = f"batch_{uuid.uuid4().hex}"
        parts = []
        for lead in batch:
            body = json.dumps(lead)
            parts.append(
                f"--{boundary}\r\nContent-Type: application/http\r\n"
                f"Content-Transfer-Encoding: binary\r\n\r\n"
                f"POST {DYNAMICS_URL}/api/data/v9.2/leads HTTP/1.1\r\n"
                f"Content-Type: application/json\r\n\r\n{body}\r\n"
            )
        batch_body = "".join(parts) + f"--{boundary}--\r\n"
        hdrs = get_hdrs()
        hdrs["Content-Type"] = f"multipart/mixed; boundary={boundary}"
        resp = session.post(
            f"{DYNAMICS_URL}/api/data/v9.2/$batch",
            headers=hdrs,
            data=batch_body.encode("utf-8"),
            timeout=120,
        )
        if resp.ok:
            ok   = resp.text.count("HTTP/1.1 204") + resp.text.count("HTTP/1.1 201")
            fail = len(batch) - ok
            created += ok
            errors  += fail
            if fail and len(error_samples) < 3:
                for line in resp.text.splitlines():
                    if '"message"' in line:
                        error_samples.append(line.strip())
                        break
        else:
            errors += len(batch)
            if len(error_samples) < 3:
                error_samples.append(f"Batch {batch_num} failed: {resp.status_code} {resp.text[:200]}")
        time.sleep(0.5)

    return {
        "success": errors == 0,
        "file": file_path,
        "total_rows": len(rows),
        "leads_created": created,
        "errors": errors,
        "skipped_rows": len(skipped),
        "error_samples": error_samples,
        "message": f"Import complete: {created} leads created, {errors} errors, {len(skipped)} rows skipped.",
    }


def find_stale_leads(days_inactive: int = 14) -> dict:
    """
    Find open leads that haven't been touched recently.

    days_inactive: days without activity to flag as stale (default 14)
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_inactive)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "$top": 100,
        "$select": "leadid,fullname,emailaddress1,companyname,modifiedon",
        "$filter": f"statecode eq 0 and modifiedon le {cutoff}",
        "$orderby": "modifiedon asc",
        "$expand": "ownerid($select=fullname)",
    }

    result = crm_get("leads", params)
    leads = result.get("value", [])

    return {
        "days_inactive_threshold": days_inactive,
        "total_stale": len(leads),
        "message": f"Found {len(leads)} open leads not updated in {days_inactive}+ days",
        "leads": [
            {
                "id": l.get("leadid"),
                "name": l.get("fullname", ""),
                "email": l.get("emailaddress1", ""),
                "company": l.get("companyname", ""),
                "last_modified": l.get("modifiedon", ""),
                "owner": (l.get("ownerid") or {}).get("fullname", ""),
            }
            for l in leads
        ],
    }
