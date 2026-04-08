# ============================================================
# tools/views_dashboards.py — Views & Dashboard Tools
# ============================================================
# Views are saved filters/lists in CRM (like "All Active Contacts")
# Dashboards are visual pages showing charts and lists together.
#
# These tools let Claude create, list, and manage both.
# ============================================================

import sys, os, json, html, uuid
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests as _requests
from config.crm_connection import crm_get, crm_post, crm_patch, crm_action, get_access_token, DYNAMICS_URL


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
    List all dashboards available in the CRM — both system dashboards and
    the personal dashboards owned by the configured user.

    Returns all dashboards with their names and types.
    """
    formatted = []

    # System dashboards
    sys_result = crm_get("systemforms", {
        "$top": 100,
        "$select": "formid,name,description,formactivationstate",
        "$filter": "type eq 0",
        "$orderby": "name asc",
    })
    for d in sys_result.get("value", []):
        formatted.append({
            "id": d.get("formid"),
            "name": d.get("name", "Unnamed Dashboard"),
            "description": d.get("description", ""),
            "status": "Active" if d.get("formactivationstate") == 1 else "Inactive",
            "type": "system",
        })

    # Personal dashboards — query as the configured user via impersonation
    user_email = os.getenv("DYNAMICS_USER_EMAIL", "")
    owner_id = None
    if user_email:
        try:
            owner_id = _get_user_id(user_email)
        except Exception:
            pass

    if owner_id:
        try:
            token = get_access_token()
            usr_headers = {
                "Authorization": f"Bearer {token}",
                "OData-MaxVersion": "4.0",
                "OData-Version": "4.0",
                "Accept": "application/json",
                "MSCRMCallerID": owner_id,
            }
            resp = _requests.get(
                f"{DYNAMICS_URL}/api/data/v9.2/userforms",
                headers=usr_headers,
                params={"$top": 50, "$select": "userformid,name,description", "$filter": "type eq 0", "$orderby": "name asc"},
            )
            if resp.ok:
                for d in resp.json().get("value", []):
                    formatted.append({
                        "id": d.get("userformid"),
                        "name": d.get("name", "Unnamed Dashboard"),
                        "description": d.get("description", ""),
                        "status": "Active",
                        "type": "personal",
                    })
        except Exception:
            pass

    return {
        "total_dashboards": len(formatted),
        "dashboards": formatted,
    }


def _get_user_id(email: str) -> str:
    """Look up a Dynamics user's systemuserid by email address."""
    result = crm_get("systemusers", {
        "$filter": f"internalemailaddress eq '{email}' or domainname eq '{email}'",
        "$select": "systemuserid,fullname",
        "$top": 1,
    })
    users = result.get("value", [])
    if not users:
        raise RuntimeError(f"Could not find Dynamics user with email: {email}")
    return users[0]["systemuserid"]


def _get_view_id(entity: str, view_name: str) -> str:
    """Look up a saved query (view) ID by entity and name."""
    result = crm_get("savedqueries", {
        "$filter": f"returnedtypecode eq '{entity}' and name eq '{view_name}' and querytype eq 0",
        "$select": "savedqueryid,name",
        "$top": 1,
    })
    rows = result.get("value", [])
    if not rows:
        # Fallback: get any active view for this entity
        result2 = crm_get("savedqueries", {
            "$filter": f"returnedtypecode eq '{entity}' and querytype eq 0 and statecode eq 0",
            "$select": "savedqueryid,name",
            "$top": 1,
        })
        rows = result2.get("value", [])
    return rows[0]["savedqueryid"] if rows else ""


def _get_chart_id(entity: str, chart_name: str) -> str:
    """Look up a saved query visualization (chart) ID by entity and name."""
    result = crm_get("savedqueryvisualizations", {
        "$filter": f"primaryentitytypecode eq '{entity}' and name eq '{chart_name}'",
        "$select": "savedqueryvisualizationid,name",
        "$top": 1,
    })
    rows = result.get("value", [])
    if not rows:
        # Fallback: get any chart for this entity
        result2 = crm_get("savedqueryvisualizations", {
            "$filter": f"primaryentitytypecode eq '{entity}'",
            "$select": "savedqueryvisualizationid,name",
            "$top": 1,
        })
        rows = result2.get("value", [])
    return rows[0]["savedqueryvisualizationid"] if rows else ""


def _build_component_xml(i: int, comp: dict) -> str:
    """
    Build XML for a single dashboard component (list or chart).
    Looks up real view/chart GUIDs so the component renders properly.

    comp keys:
      type       : "list" or "chart"
      title      : display label
      entity     : CRM entity logical name (e.g. "opportunity")
      view_name  : (optional) name of the saved view to show
      chart_name : (optional) name of the chart to show
    """
    entity = comp.get("entity", "opportunity")
    comp_type = comp.get("type", "list")
    safe_title = html.escape(comp.get("title", "Component"))

    view_id = _get_view_id(entity, comp.get("view_name", ""))
    if not view_id:
        return ""  # Can't build component without a view

    chart_id = ""
    if comp_type == "chart":
        chart_id = _get_chart_id(entity, comp.get("chart_name", ""))

    grid_mode = "Chart" if (comp_type == "chart" and chart_id) else "Grid"
    enable_chart_picker = "true" if (comp_type == "chart" and chart_id) else "false"
    enable_quick_find = "false" if comp_type == "chart" else "true"
    viz_tag = f"<VisualizationId>{{{chart_id}}}</VisualizationId>" if chart_id else "<VisualizationId/>"

    return f"""<cell showlabel="true" locklevel="0">
  <labels><label description="{safe_title}" languagecode="1033"/></labels>
  <control id="Cust_ListViewControl_{i}" classid="{{E7A81278-8635-4d9e-8D4D-59480B391C5B}}" isrequired="false">
    <parameters>
      <ViewId>{{{view_id}}}</ViewId>
      <IsUserView>false</IsUserView>
      <RelationshipName/>
      <TargetEntityType>{entity}</TargetEntityType>
      <AutoExpand>Fixed</AutoExpand>
      <EnableQuickFind>{enable_quick_find}</EnableQuickFind>
      <EnableViewPicker>true</EnableViewPicker>
      <EnableJumpBar>false</EnableJumpBar>
      <ChartGridMode>{grid_mode}</ChartGridMode>
      {viz_tag}
      <EnableChartPicker>{enable_chart_picker}</EnableChartPicker>
      <RecordsPerPage>6</RecordsPerPage>
    </parameters>
  </control>
</cell>"""


def create_dashboard(name: str, description: str, components: list = None) -> dict:
    """
    Create a new personal dashboard in the CRM, visible immediately in My Dashboards.

    name: display name, e.g. "Opportunity Pipeline Dashboard"
    description: what this dashboard shows
    components: list of components. Each item:
        {
            "type": "chart" or "list",
            "title": "Display Title",
            "entity": "opportunity",
            "view_name": "Open Opportunities",   # name of view to show
            "chart_name": "Pipeline by Stage",   # name of chart (for type=chart)
        }

    Returns confirmation and the dashboard ID.
    """
    if components is None:
        components = [
            {"type": "list",  "title": "Open Opportunities",  "entity": "opportunity", "view_name": "Open Opportunities"},
            {"type": "chart", "title": "Pipeline by Stage",   "entity": "opportunity", "view_name": "Open Opportunities", "chart_name": "Relationship Pipeline"},
        ]

    # Look up the dashboard owner from .env
    user_email = os.getenv("DYNAMICS_USER_EMAIL", "")
    owner_id = None
    if user_email:
        try:
            owner_id = _get_user_id(user_email)
        except Exception:
            owner_id = None

    # Build component cells, splitting evenly into left and right columns
    safe_name = html.escape(name)
    left_cells = []
    right_cells = []
    ctrl_idx = 0
    for comp in components[:6]:
        cell_xml = _build_component_xml(ctrl_idx, comp)
        if not cell_xml:
            continue
        if len(left_cells) <= len(right_cells):
            left_cells.append(cell_xml)
        else:
            right_cells.append(cell_xml)
        ctrl_idx += 1

    if not left_cells and not right_cells:
        return {"success": False, "error": "Could not find any views for the requested components. Check entity names and view names."}

    def _col_xml(cells, section_name, section_id):
        rows = "".join(f"<row>{c}</row>" for c in cells)
        return (
            f'<column width="50%">'
            f'<sections>'
            f'<section name="{section_name}" showlabel="false" showbar="false" locklevel="0"'
            f' id="{{{section_id}}}" columns="1">'
            f'<labels><label description="" languagecode="1033"/></labels>'
            f'<rows>{rows}</rows>'
            f'</section>'
            f'</sections>'
            f'</column>'
        )

    tab_id       = str(uuid.uuid4())
    left_sec_id  = str(uuid.uuid4())
    right_sec_id = str(uuid.uuid4())

    form_xml = (
        f'<form><tabs>'
        f'<tab name="tab_0" id="{{{tab_id}}}" locklevel="0" showlabel="false" expanded="true">'
        f'<labels><label description="{safe_name}" languagecode="1033"/></labels>'
        f'<columns>'
        f'{_col_xml(left_cells,  "section_0", left_sec_id)}'
        f'{_col_xml(right_cells, "section_1", right_sec_id)}'
        f'</columns>'
        f'</tab>'
        f'</tabs></form>'
    )

    dashboard_data = {
        "name": name,
        "description": description,
        "type": 0,
        "formxml": form_xml,
        "objecttypecode": "none",
    }

    # Create as personal dashboard (userform) using impersonation so it is
    # owned by and visible to the configured user (not the app service account)
    try:
        token = get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if owner_id:
            headers["MSCRMCallerID"] = owner_id

        response = _requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/userforms",
            headers=headers,
            json=dashboard_data,
        )
        if not response.ok:
            return {"success": False, "error": f"CRM error ({response.status_code}): {response.text[:400]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    total_built = len(left_cells) + len(right_cells)
    return {
        "success": True,
        "dashboard_name": name,
        "description": description,
        "components_added": total_built,
        "owner": user_email or "service account",
        "message": f"Dashboard '{name}' created with {total_built} component(s). Refresh your CRM and look under My Dashboards.",
    }


def delete_dashboard(name_or_id: str) -> dict:
    """
    Delete a personal dashboard (userform) by name or ID.
    Only deletes dashboards owned by the configured user — will not delete system dashboards.

    name_or_id: the dashboard name (e.g. "Opportunities Dashboard") or its GUID.
    """
    import re
    guid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
    )

    user_email = os.getenv("DYNAMICS_USER_EMAIL", "")
    owner_id = None
    if user_email:
        try:
            owner_id = _get_user_id(user_email)
        except Exception:
            pass

    escaped = name_or_id.replace("'", "''")

    if guid_pattern.match(name_or_id):
        filter_str = f"userformid eq {name_or_id}"
    else:
        filter_str = f"contains(name,'{escaped}')"

    # Query WITH impersonation so we can see the user's own dashboards
    try:
        token = get_access_token()
        q_headers = {
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
        }
        if owner_id:
            q_headers["MSCRMCallerID"] = owner_id
        resp = _requests.get(
            f"{DYNAMICS_URL}/api/data/v9.2/userforms",
            headers=q_headers,
            params={"$filter": filter_str, "$select": "userformid,name"},
        )
        if not resp.ok:
            return {"success": False, "error": f"Query failed ({resp.status_code}): {resp.text[:300]}"}
        dashboards = resp.json().get("value", [])
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not dashboards:
        return {"success": False, "error": f"No personal dashboard found matching '{name_or_id}'."}

    deleted = []
    errors = []
    for db in dashboards:
        db_id = db.get("userformid")
        db_name = db.get("name")
        try:
            token = get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "OData-MaxVersion": "4.0",
                "OData-Version": "4.0",
            }
            if owner_id:
                headers["MSCRMCallerID"] = owner_id
            response = _requests.delete(
                f"{DYNAMICS_URL}/api/data/v9.2/userforms({db_id})",
                headers=headers,
            )
            if response.ok:
                deleted.append(db_name)
            else:
                errors.append(f"{db_name}: {response.text[:200]}")
        except Exception as e:
            errors.append(f"{db_name}: {str(e)}")

    return {
        "success": len(deleted) > 0,
        "deleted": deleted,
        "errors": errors,
        "message": f"Deleted {len(deleted)} dashboard(s): {', '.join(deleted)}" if deleted else "Nothing deleted.",
    }


def publish_all_dashboards() -> dict:
    """
    Publish all dashboards and customizations so they become visible in the CRM.
    Use this if dashboards exist in the list but are not showing up in the UI.
    """
    try:
        crm_action("PublishAllXml", {})
        return {"success": True, "message": "All dashboards published. Refresh your CRM browser tab to see them."}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
