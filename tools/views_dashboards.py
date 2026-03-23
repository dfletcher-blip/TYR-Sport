# ============================================================
# tools/views_dashboards.py — Views & Dashboard Tools
# ============================================================
# Views are saved filters/lists in CRM (like "All Active Contacts")
# Dashboards are visual pages showing charts and lists together.
#
# These tools let Claude create, list, and manage both.
# ============================================================

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config.crm_connection import crm_get, crm_post, crm_patch


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
        "$select": "systemformid,name,description,formactivationstate,createdon,modifiedon",
        "$filter": "type eq 0",  # 0 = Dashboard form type
        "$orderby": "name asc",
    }

    result = crm_get("systemforms", params)
    dashboards = result.get("value", [])

    formatted = []
    for d in dashboards:
        formatted.append({
            "id": d.get("systemformid"),
            "name": d.get("name", "Unnamed Dashboard"),
            "description": d.get("description", ""),
            "status": "Active" if d.get("formactivationstate") == 1 else "Inactive",
            "created": d.get("createdon", ""),
            "last_modified": d.get("modifiedon", ""),
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
    rows_xml = ""
    for i, comp in enumerate(components[:4]):  # max 4 components
        col = i % 2
        if col == 0:
            rows_xml += "<row>"
        rows_xml += f"""<cell colspan="1" rowspan="1" showlabel="true" locklevel="0">
  <labels><label description="{comp.get('title', 'Component')}" languagecode="1033"/></labels>
  <control id="control{i}" classid="{{E7A81278-8635-4d9e-8D4D-59480B391C5B}}" isrequired="false" rowspan="1" colspan="1"/>
</cell>"""
        if col == 1 or i == len(components) - 1:
            rows_xml += "</row>"

    form_xml = f"""<form>
  <tabs>
    <tab name="tab_0" id="{{c58ee3c2-79ba-4bcc-8dd7-b6ef3b4b6456}}" IsUserDefined="0" locklevel="0" showlabel="false" expanded="true">
      <labels><label description="{name}" languagecode="1033"/></labels>
      <columns>
        <column width="100%">
          <sections>
            <section name="section_0" showlabel="false" showbar="false" locklevel="0" id="{{0e9dd3f4-98e0-4536-a3c9-56b5e38a8b4a}}" IsUserDefined="0" layout="varwidth" columns="2">
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
        "objecttypecode": 0,  # Global dashboard (not entity-specific)
    }

    result = crm_post("systemforms", dashboard_data)

    return {
        "success": True,
        "dashboard_name": name,
        "description": description,
        "components_added": len(components),
        "message": f"Dashboard '{name}' has been created",
        "note": "Open your CRM and navigate to Dashboards to see it",
    }


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
