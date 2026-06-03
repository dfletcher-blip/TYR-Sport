"""
Direct fix for Run Specialty Dashboard blank panels.

Fetches the current dashboard formxml, inspects the working component,
then rebuilds formxml using an EXISTING working system dashboard as
the structural template — replacing only the control parameters.

Run locally: python fix_dashboard_direct.py
"""
import sys, os, re, uuid, html
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import crm_get, crm_patch, crm_action, get_access_token, DYNAMICS_URL
import requests as _requests

DASHBOARD_NAME = "Run Specialty Dashboard"
RUN_SPECIALTY_VALUE = 935650018

# ── Step 1: Resolve view IDs ──────────────────────────────────────────────────
print("Resolving view IDs...")

def get_view_id(name, entity):
    r = crm_get("savedqueries", {
        "$filter": f"name eq '{name}' and querytype eq 0",
        "$select": "savedqueryid,name,returnedtypecode",
        "$top": 1,
    })
    rows = r.get("value", [])
    if rows:
        v = rows[0]
        print(f"  ✓ {name} → {v['savedqueryid']} (entity={v.get('returnedtypecode')})")
        return v["savedqueryid"]
    print(f"  ✗ MISSING: {name}")
    return None

view1_id = get_view_id("Run Specialty Leads", "lead")
view3_id = get_view_id("Run Specialty Accounts", "account")
view4_id = get_view_id("Run Specialty Leads 2026", "lead")
view5_id = get_view_id("Run Specialty Accounts 2026", "account")
view2_id = view1_id  # Leads by Status uses same data set as Leads by Owner

# ── Step 2: Resolve chart IDs ─────────────────────────────────────────────────
print("\nResolving chart IDs...")

def get_chart_id(entity, preferred_name):
    r = crm_get("savedqueryvisualizations", {
        "$filter": f"primaryentitytypecode eq '{entity}' and name eq '{preferred_name}'",
        "$select": "savedqueryvisualizationid,name",
        "$top": 1,
    })
    rows = r.get("value", [])
    if rows:
        print(f"  ✓ {rows[0]['name']} → {rows[0]['savedqueryvisualizationid']}")
        return rows[0]["savedqueryvisualizationid"]
    # Fallback: any chart for this entity
    r2 = crm_get("savedqueryvisualizations", {
        "$filter": f"primaryentitytypecode eq '{entity}'",
        "$select": "savedqueryvisualizationid,name",
        "$top": 1,
    })
    rows2 = r2.get("value", [])
    if rows2:
        print(f"  ~ fallback {rows2[0]['name']} → {rows2[0]['savedqueryvisualizationid']}")
        return rows2[0]["savedqueryvisualizationid"]
    print(f"  ✗ No chart found for {entity}")
    return ""

# First print ALL available charts so we know what exists in this CRM
print("\nAll available lead charts:")
all_lead = crm_get("savedqueryvisualizations", {
    "$filter": "primaryentitytypecode eq 'lead'",
    "$select": "savedqueryvisualizationid,name", "$top": 50,
})
for c in all_lead.get("value", []):
    print(f"  {c['name']} | {c['savedqueryvisualizationid']}")

print("\nAll available account charts:")
all_acct = crm_get("savedqueryvisualizations", {
    "$filter": "primaryentitytypecode eq 'account'",
    "$select": "savedqueryvisualizationid,name", "$top": 50,
})
for c in all_acct.get("value", []):
    print(f"  {c['name']} | {c['savedqueryvisualizationid']}")

# Use exact names — no fallback to wrong charts
def get_chart_id(entity, preferred_name):
    r = crm_get("savedqueryvisualizations", {
        "$filter": f"primaryentitytypecode eq '{entity}' and name eq '{preferred_name}'",
        "$select": "savedqueryvisualizationid,name", "$top": 1,
    })
    rows = r.get("value", [])
    if rows:
        print(f"  ✓ chart '{rows[0]['name']}' → {rows[0]['savedqueryvisualizationid']}")
        return rows[0]["savedqueryvisualizationid"]
    print(f"  ~ no chart named '{preferred_name}' — will show as list view")
    return ""

print("\nUsing confirmed chart IDs from CRM:")
# Exact IDs from CRM — no lookup needed
chart1_id = "ad936200-375f-df11-ae90-00155d2e3002"  # Leads by Owner
chart2_id = "aed15f95-915e-f111-a826-00224805fad6"  # Run Specialty Leads by Status
chart3_id = "a3a9ee47-5093-de11-97d4-00155da3b01e"  # Accounts by Owner
chart4_id = "eec61ec1-3a5f-df11-ae90-00155d2e3002"  # Incoming Lead Analysis by Month
chart5_id = "5b290fff-355f-df11-ae90-00155d2e3002"  # New Accounts By Month
print(f"  chart1 Leads by Owner:                    {chart1_id}")
print(f"  chart2 Run Specialty Leads by Status:     {chart2_id}")
print(f"  chart3 Accounts by Owner:                 {chart3_id}")
print(f"  chart4 Incoming Lead Analysis by Month:   {chart4_id}")
print(f"  chart5 New Accounts By Month:             {chart5_id}")

# ── Step 3: Fetch an existing working system dashboard as structure template ───
print("\nFetching source dashboard template...")
source_r = crm_get("systemforms", {
    "$filter": "type eq 0 and name ne 'Run Specialty Dashboard'",
    "$select": "formid,name,formxml",
    "$top": 1,
})
source_rows = source_r.get("value", [])
if not source_rows:
    print("ERROR: No source dashboard found to use as template")
    sys.exit(1)

source_formxml = source_rows[0]["formxml"]
print(f"  Using template: {source_rows[0]['name']}")
print(f"  Template XML length: {len(source_formxml)}")

# Print the first <cell> element from the template to understand structure
first_cell = re.search(r'<cell[^>]*>.*?</cell>', source_formxml, re.DOTALL)
if first_cell:
    print(f"\n  Template cell structure (first 600 chars):\n  {first_cell.group()[:600]}")

# ── Step 4: Build component XML using template cell structure ─────────────────
print("\nBuilding dashboard components...")

def make_cell(ctrl_idx, entity, view_id, chart_id, label):
    """Build a component cell using exact structure from template."""
    safe_label = html.escape(label)
    grid_mode = "Chart" if chart_id else "Grid"
    viz = f"<VisualizationId>{{{chart_id}}}</VisualizationId>" if chart_id else "<VisualizationId/>"
    chart_picker = "true" if chart_id else "false"

    # Extract cell attributes from template (rowspan, colspan, etc.)
    cell_attrs = 'showlabel="true" locklevel="0" rowspan="9" colspan="1" auto="false"'
    if first_cell:
        m = re.search(r'<cell([^>]*)>', first_cell.group())
        if m:
            cell_attrs = m.group(1).strip()
            # Remove id — we supply our own unique id per cell
            cell_attrs = re.sub(r'\s*id="[^"]*"', '', cell_attrs)
            # Ensure showlabel=true
            cell_attrs = re.sub(r'showlabel="[^"]*"', 'showlabel="true"', cell_attrs)
            if 'showlabel' not in cell_attrs:
                cell_attrs += ' showlabel="true"'

    cell_id = "{" + str(uuid.uuid4()) + "}"
    ctrl_uid = "{" + str(uuid.uuid4()) + "}"
    return (
        f'<cell {cell_attrs} id="{cell_id}">'
        f'<labels><label description="{safe_label}" languagecode="1033"/></labels>'
        f'<control id="RS_ctrl_{ctrl_idx}" uniqueid="{ctrl_uid}" classid="{{E7A81278-8635-4d9e-8D4D-59480B391C5B}}" isrequired="false">'
        f'<parameters>'
        f'<ViewId>{{{view_id}}}</ViewId>'
        f'<IsUserView>false</IsUserView>'
        f'<RelationshipName/>'
        f'<TargetEntityType>{entity}</TargetEntityType>'
        f'<AutoExpand>Fixed</AutoExpand>'
        f'<EnableQuickFind>false</EnableQuickFind>'
        f'<EnableViewPicker>true</EnableViewPicker>'
        f'<EnableJumpBar>false</EnableJumpBar>'
        f'<ChartGridMode>{grid_mode}</ChartGridMode>'
        f'{viz}'
        f'<EnableChartPicker>{chart_picker}</EnableChartPicker>'
        f'<RecordsPerPage>12</RecordsPerPage>'
        f'</parameters></control></cell>'
    )

# Determine rowspan from template
rowspan = 10
if first_cell:
    m = re.search(r'rowspan="(\d+)"', first_cell.group())
    if m:
        rowspan = int(m.group(1))
        print(f"  Template rowspan: {rowspan}")
    else:
        print(f"  No rowspan in template, using default {rowspan}")

def make_col(comps, sec_name):
    sec_id = "{" + str(uuid.uuid4()) + "}"
    rows_xml = ""
    for (ctrl_idx, entity, view_id, chart_id, label) in comps:
        if not view_id:
            print(f"  SKIPPING {label} — no view ID")
            continue
        rows_xml += f"<row>{make_cell(ctrl_idx, entity, view_id, chart_id, label)}</row>"
        rows_xml += "<row/>" * (rowspan - 1)
    return (
        f'<column width="50%"><sections>'
        f'<section name="{sec_name}" showlabel="false" showbar="false"'
        f' locklevel="0" id="{sec_id}" columns="1">'
        f'<labels><label description="" languagecode="1033"/></labels>'
        f'<rows>{rows_xml}</rows>'
        f'</section></sections></column>'
    )

tab_id = "{" + str(uuid.uuid4()) + "}"
left_comps = [
    (0, "lead",    view1_id, chart1_id, "Leads by Owner"),
    (1, "lead",    view2_id, chart2_id, "Leads by Status"),
    (2, "account", view3_id, chart3_id, "Accounts by Owner"),
]
right_comps = [
    (3, "lead",    view4_id, chart4_id, "Leads Created by Owner by Month (2026)"),
    (4, "account", view5_id, chart5_id, "Accounts Created by Month (2026)"),
]

new_formxml = (
    '<form>'
    '<tabs>'
    f'<tab name="tab" showlabel="false" locklevel="0" id="{tab_id}" expanded="true">'
    '<labels><label description="Summary" languagecode="1033"/></labels>'
    f'<columns>{make_col(left_comps, "section_left")}{make_col(right_comps, "section_right")}</columns>'
    '</tab>'
    '</tabs>'
    '</form>'
)

print(f"\n  Generated formxml length: {len(new_formxml)}")

# ── Step 5: Find or create the dashboard record ───────────────────────────────
print("\nFinding Run Specialty Dashboard...")
dash_r = crm_get("systemforms", {
    "$filter": f"name eq '{DASHBOARD_NAME}' and type eq 0",
    "$select": "formid,name",
    "$top": 1,
})
dash_rows = dash_r.get("value", [])

if dash_rows:
    dash_id = dash_rows[0]["formid"]
    print(f"  Found: {dash_id}")
else:
    print("  Not found — creating via clone...")
    post_r = crm_post_raw = None
    try:
        from config.crm_connection import crm_post
        post_result = crm_post("systemforms", {
            "name": DASHBOARD_NAME,
            "type": 0,
            "formactivationstate": 1,
            "formxml": source_formxml,
            "objecttypecode": source_rows[0].get("objecttypecode", "none"),
        })
        record_url = post_result.get("record_url", "")
        dash_id = record_url.split("(")[-1].rstrip(")") if "(" in record_url else None
        if not dash_id:
            r2 = crm_get("systemforms", {
                "$filter": f"name eq '{DASHBOARD_NAME}' and type eq 0",
                "$select": "formid", "$top": 1,
            })
            dash_id = r2.get("value", [{}])[0].get("formid")
        print(f"  Created: {dash_id}")
    except Exception as e:
        print(f"  ERROR creating dashboard: {e}")
        sys.exit(1)

# ── Step 6: PATCH the formxml ─────────────────────────────────────────────────
print("\nPatching dashboard formxml...")
try:
    crm_patch("systemforms", dash_id, {
        "formxml": new_formxml,
        "name": DASHBOARD_NAME,
        "formactivationstate": 1,
    })
    print("  ✓ PATCH succeeded")
except Exception as e:
    print(f"  ✗ PATCH failed: {e}")
    sys.exit(1)

# ── Step 7: Publish ────────────────────────────────────────────────────────────
print("\nPublishing dashboard specifically by ID...")
try:
    # Target the specific dashboard — PublishAllXml misses direct Web API PATCHes
    publish_xml = (
        "<importexportxml>"
        "<dashboards>"
        f"<dashboard>{dash_id}</dashboard>"
        "</dashboards>"
        "</importexportxml>"
    )
    crm_action("PublishXml", {"ParameterXml": publish_xml})
    print("  ✓ PublishXml (targeted) succeeded")
except Exception as e:
    print(f"  ~ PublishXml targeted failed ({e}), trying PublishAllXml...")
    try:
        crm_action("PublishAllXml", {})
        print("  ✓ PublishAllXml succeeded")
    except Exception as e2:
        print(f"  ✗ Both publish attempts failed: {e2}")

print(f"""
Done. Dashboard ID: {dash_id}
Refresh the Run Specialty Dashboard in CRM.
If panels still collapse, run: python debug_rs_dashboard.py
to inspect what's in the formxml.
""")
