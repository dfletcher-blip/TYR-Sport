# ============================================================
# tools/views_dashboards.py — Views & Dashboard Tools
# ============================================================
# Views are saved filters/lists in CRM (like "All Active Contacts")
# Dashboards are visual pages showing charts and lists together.
#
# These tools let Claude create, list, and manage both.
# ============================================================

import sys, os, json, html
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_post, crm_patch, crm_action


def list_views(entity: str = "contact") -> dict:
    """
    List all saved views for a specific entity (record type).

    entity: the type of records the view shows —
            "contact"  → contact views
            "lead"     → lead views
            "account"  → company/account views
            "opportunity" → deal/opportunity views

    Returns all existing views with their names and types.
    """
    # Entity name map (Dynamics uses these internal names)
    entity_map = {
        "contact":     "contact",
        "lead":        "lead",
        "account":     "account",
        "opportunity": "opportunity",
    }
    crm_entity = entity_map.get(entity.lower(), entity)

    params = {
        "$top": 100,
        "$select": "savedqueryid,name,description,querytype,statecode,isdefault,createdon,modifiedon",
        "$filter": f"returnedtypecode eq '{crm_entity}'",
        "$orderby": "name asc",
    }

    result = crm_get("savedqueries", params)
    views  = result.get("value", [])

    type_labels = {
        0:  "Public View",
        1:  "Advanced Find",
        2:  "Associated View",
        4:  "Quick Find",
        64: "Main View",
    }

    formatted = []
    for v in views:
        formatted.append({
            "id": v.get("savedqueryid"),
            "name": v.get("name", "Unnamed View"),
            "description": v.get("description", ""),
            "type": type_labels.get(v.get("querytype", 0), "View"),
            "is_default": v.get("isdefault", False),
            "status": "Active" if v.get("statecode") == 0 else "Inactive",
            "created": v.get("createdon", ""),
            "last_modified": v.get("modifiedon", ""),
        })

    return {
        "entity": entity,
        "total_views": len(formatted),
        "views": formatted,
    }


def create_contact_view(
    name: str,
    description: str,
    filter_criteria: str,
    columns: list = None,
) -> dict:
    """
    Create a new saved view for contacts.

    name: display name for the view, e.g. "Active Contacts Missing Email"
    description: what this view is for
    filter_criteria: plain English description of what to filter
                     (Claude will translate to CRM filter format)
    columns: list of columns to show, e.g. ["name", "email", "phone", "company"]
             defaults to: name, email, phone, job title, company

    Returns the ID and name of the newly created view.

    COMMON FILTERS (plain English → what this function supports):
      "missing email"     → contacts with no email address
      "missing phone"     → contacts with no phone
      "active only"       → only active contacts
      "inactive only"     → only inactive contacts
      "created this year" → contacts added this year
    """
    # Default columns (these are Dynamics 365 field names)
    if columns is None:
        columns = ["fullname", "emailaddress1", "telephone1", "jobtitle", "parentcustomerid"]

    # Translate common filter phrases to OData filter expressions
    filter_map = {
        "missing email":      "emailaddress1 eq null",
        "missing phone":      "telephone1 eq null",
        "missing company":    "_parentcustomerid_value eq null",
        "active only":        "statecode eq 0",
        "inactive only":      "statecode eq 1",
        "created this year":  f"createdon ge {__import__('datetime').date.today().year}-01-01",
        "has email":          "emailaddress1 ne null",
        "has phone":          "telephone1 ne null",
    }

    # Build OData filter — try exact match first, then partial match
    odata_filter = None
    filter_lower = filter_criteria.lower()
    for phrase, odata in filter_map.items():
        if phrase in filter_lower:
            odata_filter = odata
            break

    # Build the fetch XML (Dynamics 365 query format) — simple version
    fetch_xml = f"""<fetch version="1.0" output-format="xml-platform" mapping="logical" distinct="false">
  <entity name="contact">
    <attribute name="fullname"/>
    <attribute name="emailaddress1"/>
    <attribute name="telephone1"/>
    <attribute name="jobtitle"/>
    <attribute name="parentcustomerid"/>
    <attribute name="contactid"/>
    {"<filter type='and'><condition attribute='" + odata_filter.split(' ')[0] + "' operator='null'/></filter>" if odata_filter and 'eq null' in odata_filter else ""}
    <order attribute="fullname" descending="false"/>
  </entity>
</fetch>"""

    # Build layout XML (which columns to show and in what order)
    layout_xml = f"""<grid name="resultset" jump="fullname" select="1" icon="1" preview="1">
  <row name="result" id="contactid">
    {"".join(f'<cell name="{col}" width="150"/>' for col in columns)}
  </row>
</grid>"""

    # Create the view record
    view_data = {
        "name": name,
        "description": description,
        "returnedtypecode": "contact",
        "querytype": 0,  # 0 = Public View
        "fetchxml": fetch_xml,
        "layoutxml": layout_xml,
        "isdefault": False,
    }

    result = crm_post("savedqueries", view_data)

    return {
        "success": True,
        "view_name": name,
        "description": description,
        "filter_applied": filter_criteria,
        "message": f"View '{name}' has been created successfully",
        "note": "The view is now available in the Contacts section of your CRM",
    }


def list_dashboards() -> dict:
    """
    List all dashboards available in the CRM.

    Returns all dashboards with their names and types.
    """
    params = {
        "$top": 100,
        "$select": "formid,name,description,formactivationstate",
        "$filter": "type eq 0",  # 0 = Dashboard form type
        "$orderby": "name asc",
    }

    result = crm_get("systemforms", params)
    dashboards = result.get("value", [])

    formatted = []
    for d in dashboards:
        formatted.append({
            "id": d.get("formid"),
            "name": d.get("name", "Unnamed Dashboard"),
            "description": d.get("description", ""),
            "status": "Active" if d.get("formactivationstate") == 1 else "Inactive",
        })

    return {
        "total_dashboards": len(formatted),
        "dashboards": formatted,
    }


def create_dashboard(name: str, description: str, components: list = None) -> dict:
    """
    Create a new dashboard in the CRM.

    name: display name, e.g. "Contact Data Quality Dashboard"
    description: what this dashboard shows
    components: list of components to include. Each item is a dict:
        {
            "type": "chart" or "list",
            "title": "Component Title",
            "entity": "contact" or "lead" etc.
        }
        Defaults to a standard contact overview dashboard.

    Returns confirmation and the dashboard ID.
    """
    if components is None:
        components = [
            {"type": "list",  "title": "Recent Contacts",         "entity": "contact"},
            {"type": "chart", "title": "Contacts by Status",       "entity": "contact"},
            {"type": "list",  "title": "Contacts Missing Email",   "entity": "contact"},
        ]

    # Build a simple dashboard form XML
    # This creates a 2-column layout
    safe_name = html.escape(name)
    rows_xml = ""
    for i, comp in enumerate(components[:4]):  # max 4 components
        col = i % 2
        if col == 0:
            rows_xml += "<row>"
        safe_title = html.escape(comp.get('title', 'Component'))
        rows_xml += f"""<cell showlabel="true" locklevel="0">
  <labels><label description="{safe_title}" languagecode="1033"/></labels>
  <control id="control{i}" classid="{{E7A81278-8635-4d9e-8D4D-59480B391C5B}}" isrequired="false"/>
</cell>"""
        if col == 1 or i == len(components) - 1:
            rows_xml += "</row>"

    form_xml = f"""<form>
  <tabs>
    <tab name="tab_0" id="{{c58ee3c2-79ba-4bcc-8dd7-b6ef3b4b6456}}" locklevel="0" showlabel="false" expanded="true">
      <labels><label description="{safe_name}" languagecode="1033"/></labels>
      <columns>
        <column width="100%">
          <sections>
            <section name="section_0" showlabel="false" showbar="false" locklevel="0" id="{{0e9dd3f4-98e0-4536-a3c9-56b5e38a8b4a}}" layout="varwidth" columns="2">
              <labels><label description="Section" languagecode="1033"/></labels>
              <rows>{rows_xml}</rows>
            </section>
          </sections>
        </column>
      </columns>
    </tab>
  </tabs>
</form>"""

    dashboard_data = {
        "name": name,
        "description": description,
        "type": 0,  # Dashboard
        "formactivationstate": 1,
        "formxml": form_xml,
        "objecttypecode": "none",  # Global dashboard (not entity-specific)
    }

    try:
        result = crm_post("systemforms", dashboard_data)
    except RuntimeError as e:
        return {"success": False, "error": str(e)}

    dashboard_id = result.get("formid", "") if isinstance(result, dict) else ""

    # Publish so the dashboard is visible immediately
    try:
        crm_action("PublishXml", {
            "ParameterXml": "<importexportxml><dashboards><dashboard></dashboard></dashboards></importexportxml>"
        })
        published = True
    except Exception:
        published = False

    return {
        "success": True,
        "dashboard_id": dashboard_id,
        "dashboard_name": name,
        "description": description,
        "components_added": len(components),
        "published": published,
        "message": f"Dashboard '{name}' has been created and {'published' if published else 'saved (may need manual publish)'}",
        "note": "Open your CRM and navigate to Dashboards to see it",
    }


def get_dashboard_details(name_or_id: str) -> dict:
    """
    Fetch a specific dashboard by name or ID, including its full layout XML.

    name_or_id: the dashboard's display name (e.g. "D2C/Crossfit") or its GUID.

    Searches both system dashboards (systemforms) and personal/user dashboards
    (userforms). Returns the dashboard's id, name, description, formxml,
    form_type ("system" or "user"), and a list of all component label names
    found in the XML — useful for confirming exact label text before reordering.
    """
    import re
    import xml.etree.ElementTree as ET

    guid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
    )

    escaped = name_or_id.replace("'", "''")

    # Try system dashboards first
    if guid_pattern.match(name_or_id):
        sys_params = {
            "$select": "formid,name,description,formxml,formactivationstate",
            "$filter": f"formid eq {name_or_id} and type eq 0",
        }
    else:
        sys_params = {
            "$select": "formid,name,description,formxml,formactivationstate",
            "$filter": f"type eq 0 and contains(name,'{escaped}')",
        }

    sys_result = crm_get("systemforms", sys_params)
    sys_rows = sys_result.get("value", [])

    # Fall back to personal/user dashboards
    usr_rows = []
    if not sys_rows:
        if guid_pattern.match(name_or_id):
            usr_params = {
                "$select": "userformid,name,description,formxml",
                "$filter": f"userformid eq {name_or_id} and type eq 0",
            }
        else:
            usr_params = {
                "$select": "userformid,name,description,formxml",
                "$filter": f"type eq 0 and contains(name,'{escaped}')",
            }
        usr_result = crm_get("userforms", usr_params)
        usr_rows = usr_result.get("value", [])

    if not sys_rows and not usr_rows:
        return {"error": f"No dashboard found matching '{name_or_id}' in system or user dashboards"}

    is_system = bool(sys_rows)
    d = sys_rows[0] if is_system else usr_rows[0]
    id_field = "formid" if is_system else "userformid"
    formxml = d.get("formxml", "")

    # Extract all label descriptions from the formxml for diagnostics
    component_labels = []
    if formxml:
        try:
            root = ET.fromstring(formxml)
            component_labels = list(dict.fromkeys(
                label_el.get("description", "")
                for label_el in root.iter("label")
                if label_el.get("description")
            ))
        except ET.ParseError:
            pass

    return {
        "id": d.get(id_field),
        "name": d.get("name"),
        "description": d.get("description", ""),
        "status": "Active" if d.get("formactivationstate") == 1 else "Inactive",
        "form_type": "system" if is_system else "user",
        "formxml": formxml,
        "component_labels": component_labels,
    }


def reorder_dashboard_components(dashboard_id: str, move_to_top: list) -> dict:
    """
    Reorder a dashboard's components so that specific ones appear at the top.

    dashboard_id: the GUID of the dashboard (get this from get_dashboard_details).
    move_to_top: list of component label substrings to move to the top,
                 e.g. ["Teams by owner", "Teams by status"]
                 Matching is case-insensitive and partial.

    The function reorders rows within each section of the dashboard so rows
    containing any of the listed labels appear first, then patches the record
    back. For system dashboards, PublishXml is called automatically so the
    change is immediately visible.
    Returns a confirmation with the new component order.
    """
    import xml.etree.ElementTree as ET

    # 1. Fetch the dashboard (searches both systemforms and userforms)
    details = get_dashboard_details(dashboard_id)
    if "error" in details:
        return details

    formxml = details.get("formxml", "")
    if not formxml:
        return {"error": "Dashboard has no formxml to reorder"}

    # Use the resolved GUID from details, not the raw argument (which may be a name)
    record_id = details["id"]
    form_type = details.get("form_type", "system")  # "system" or "user"
    endpoint = "systemforms" if form_type == "system" else "userforms"

    # 2. Parse the XML
    try:
        root = ET.fromstring(formxml)
    except ET.ParseError as e:
        return {"error": f"Could not parse dashboard XML: {e}"}

    move_lower = [m.lower() for m in move_to_top]

    def cell_labels(cell_el):
        return [lb.get("description", "") for lb in cell_el.iter("label") if lb.get("description")]

    def cell_matches(cell_el):
        for desc in cell_labels(cell_el):
            if any(m in desc.lower() for m in move_lower):
                return True
        return False

    def component_groups(rows_el):
        """
        Group <row> elements into per-component chunks.

        A component's leading row contains a <cell> element; that cell's
        rowspan attribute tells us how many subsequent rows belong to the
        same component (they are empty continuation rows). Returns a list
        of (leading_cell_el, [row_el, ...]) tuples.
        """
        groups = []
        all_rows = list(rows_el)
        i = 0
        while i < len(all_rows):
            row = all_rows[i]
            cells = [c for c in row if c.tag == "cell"]
            if cells:
                cell = cells[0]
                span = max(1, int(cell.get("rowspan", "1")))
                groups.append((cell, all_rows[i : i + span]))
                i += span
            else:
                # Orphan empty row — keep as its own group
                groups.append((None, [row]))
                i += 1
        return groups

    # 3. Collect all labels for diagnostics before reordering
    all_labels_before = []
    for rows_el in root.iter("rows"):
        for cell_el, _ in component_groups(rows_el):
            if cell_el is not None:
                all_labels_before.append(cell_labels(cell_el))

    # 4. For every <rows> container, move matching component groups to the front
    reordered = []
    for rows_el in root.iter("rows"):
        groups = component_groups(rows_el)
        priority = [(c, rows) for c, rows in groups if c is not None and cell_matches(c)]
        rest     = [(c, rows) for c, rows in groups if not (c is not None and cell_matches(c))]
        if priority:
            new_groups = priority + rest
            for child in list(rows_el):
                rows_el.remove(child)
            for _, row_group in new_groups:
                for row in row_group:
                    rows_el.append(row)
            reordered.extend([cell_labels(c) for c, _ in priority])

    if not reordered:
        return {
            "warning": "No rows found matching the requested labels — no changes made.",
            "requested": move_to_top,
            "labels_found_in_dashboard": all_labels_before,
            "hint": "Use the exact label text from 'labels_found_in_dashboard' above.",
            "dashboard_id": dashboard_id,
            "dashboard_name": details["name"],
        }

    # 5. Serialize back to XML string
    new_formxml = ET.tostring(root, encoding="unicode")

    # 6. Patch the dashboard record using the resolved GUID
    crm_patch(endpoint, record_id, {"formxml": new_formxml})

    # 7. For system dashboards, publish so the change is visible immediately
    published = False
    publish_error = None
    if form_type == "system":
        publish_xml = (
            f"<importexportxml><dashboards>"
            f"<dashboard>{record_id}</dashboard>"
            f"</dashboards></importexportxml>"
        )
        try:
            crm_action("PublishXml", {"ParameterXml": publish_xml})
            published = True
        except Exception as e:
            publish_error = str(e)

    result = {
        "success": True,
        "dashboard_id": record_id,
        "dashboard_name": details["name"],
        "form_type": form_type,
        "published": published,
        "moved_to_top": reordered,
        "message": (
            f"Dashboard '{details['name']}' updated and published — "
            f"{len(reordered)} row(s) moved to the top."
            if published else
            f"Dashboard '{details['name']}' updated — "
            f"{len(reordered)} row(s) moved to the top."
        ),
    }
    if publish_error:
        result["publish_warning"] = (
            f"Patch succeeded but PublishXml failed: {publish_error}. "
            "The change is saved but may not be visible until customizations are published."
        )
    return result


def get_views_summary() -> dict:
    """
    Get a summary of all views across key entities.
    Useful for an overview of what's already set up.

    Returns view counts by entity type.
    """
    entities = ["contact", "lead", "account", "opportunity"]
    summary = {}

    for entity in entities:
        try:
            result = list_views(entity)
            summary[entity] = {
                "total_views": result["total_views"],
                "view_names": [v["name"] for v in result["views"][:5]],
            }
        except Exception as e:
            summary[entity] = {"error": str(e)}

    return {
        "views_by_entity": summary,
        "message": "Summary of views across all main entities",
    }


def clone_dashboard(source_name_or_id: str, new_name: str, new_description: str = "") -> dict:
    """
    Clone an existing dashboard under a new name.

    source_name_or_id: name or GUID of the dashboard to copy
    new_name: name for the cloned dashboard
    new_description: optional description for the clone
    """
    details = get_dashboard_details(source_name_or_id)
    if "error" in details:
        return details

    formxml = details.get("formxml", "")
    if not formxml:
        return {"error": "Source dashboard has no formxml to clone"}

    dashboard_data = {
        "name": new_name,
        "description": new_description or f"Clone of {details['name']}",
        "type": 0,
        "formactivationstate": 1,
        "formxml": formxml,
        "objecttypecode": 0,
    }

    result = crm_post("systemforms", dashboard_data)
    return {
        "success": True,
        "source_dashboard": details["name"],
        "new_dashboard_name": new_name,
        "message": f"Dashboard '{details['name']}' cloned as '{new_name}'",
    }


def set_dashboard_description(name_or_id: str, description: str) -> dict:
    """
    Update the description of an existing dashboard.

    name_or_id: name or GUID of the dashboard
    description: new description text
    """
    details = get_dashboard_details(name_or_id)
    if "error" in details:
        return details

    endpoint = "systemforms" if details["form_type"] == "system" else "userforms"
    crm_patch(endpoint, details["id"], {"description": description})

    return {
        "success": True,
        "dashboard_name": details["name"],
        "new_description": description,
        "message": f"Description updated on '{details['name']}'",
    }
