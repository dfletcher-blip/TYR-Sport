"""
Cleanup and fix for duplicate Run Specialty Dashboards.
Run locally: python cleanup_and_fix_dashboard.py
"""
import sys, os, re, uuid, html
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import crm_get, crm_patch, crm_action, get_access_token, DYNAMICS_URL
import requests as _requests

DASHBOARD_NAME = "Run Specialty Dashboard"
RUN_SPECIALTY_VALUE = 935650018

# ── 1. Find ALL Run Specialty Dashboards ─────────────────────────────────────
print("=" * 60)
print("1. ALL RUN SPECIALTY DASHBOARDS IN CRM")
print("=" * 60)

# System dashboards
sys_r = crm_get("systemforms", {
    "$filter": f"contains(name, 'Run Specialty') and type eq 0",
    "$select": "formid,name,formactivationstate",
    "$top": 20,
})
sys_dashes = sys_r.get("value", [])
print(f"\nSystem dashboards ({len(sys_dashes)} found):")
for d in sys_dashes:
    print(f"  ID: {d['formid']}")
    print(f"  Name: {d['name']}")
    print(f"  Active: {d.get('formactivationstate')} (1=active)")
    print()

if len(sys_dashes) < 2:
    print("Only one system dashboard found — no duplicates to clean up.")
else:
    # Prefer the known-good ID from previous runs; otherwise keep the first active one
    KNOWN_GOOD_ID = "127b4f86-9f5e-f111-a826-00224805f22c"
    known = [d for d in sys_dashes if d["formid"] == KNOWN_GOOD_ID]
    keep = known[0] if known else sys_dashes[0]
    delete_list = [d for d in sys_dashes if d["formid"] != keep["formid"]]
    print(f"Keeping:  {keep['formid']} ({keep['name']})")
    for d in delete_list:
        print(f"Deleting: {d['formid']} ({d['name']})")
        try:
            token = get_access_token()
            resp = _requests.delete(
                f"{DYNAMICS_URL}/api/data/v9.2/systemforms({d['formid']})",
                headers={
                    "Authorization": f"Bearer {token}",
                    "OData-MaxVersion": "4.0",
                    "OData-Version": "4.0",
                },
                timeout=30,
            )
            if resp.ok:
                print(f"  ✓ Deleted")
            else:
                print(f"  ✗ Delete failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    dash_id = keep["formid"]
    print(f"\nUsing dashboard ID: {dash_id}")

if len(sys_dashes) == 0:
    print("No dashboard found — will create one.")
    dash_id = None
elif len(sys_dashes) == 1:
    dash_id = sys_dashes[0]["formid"]
    print(f"Using dashboard ID: {dash_id}")

# ── 2. Resolve view IDs ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. VIEW IDs")
print("=" * 60)

def get_view_id(name):
    r = crm_get("savedqueries", {
        "$filter": f"name eq '{name}' and querytype eq 0",
        "$select": "savedqueryid,name,returnedtypecode,statecode",
        "$top": 1,
    })
    rows = r.get("value", [])
    if rows:
        v = rows[0]
        print(f"  ✓ {name} | {v['savedqueryid']} | statecode={v.get('statecode')}")
        return v["savedqueryid"]
    print(f"  ✗ MISSING: {name}")
    return None

view1_id = get_view_id("Run Specialty Leads")
view2_id = view1_id
view3_id = get_view_id("Run Specialty Accounts")
view4_id = get_view_id("Run Specialty Leads 2026")
view5_id = get_view_id("Run Specialty Accounts 2026")

# ── 2b. Look up Dillon Fletcher's user ID and update all views ────────────────
print("\n" + "=" * 60)
print("2b. FILTERING OUT DILLON FLETCHER")
print("=" * 60)

dillon_id = None
df_r = crm_get("systemusers", {
    "$filter": "internalemailaddress eq 'dfletcher@tyr.com'",
    "$select": "systemuserid,fullname",
    "$top": 1,
})
df_rows = df_r.get("value", [])
if df_rows:
    dillon_id = df_rows[0]["systemuserid"]
    print(f"  ✓ Found: {df_rows[0]['fullname']} | {dillon_id}")
else:
    print("  ✗ dfletcher@tyr.com not found — filter will not be applied")

def add_owner_exclusion(fetchxml, exclude_userid):
    """Insert <condition attribute='ownerid' operator='ne' value='...'/>
    into every top-level <filter> block in the fetchxml."""
    condition = f'<condition attribute="ownerid" operator="ne" value="{{{exclude_userid}}}"/>'
    # Insert into the first <filter type="and"> that directly belongs to the root entity
    # (not inside a link-entity)
    return re.sub(
        r'(<filter type="and">)',
        r'\1' + condition,
        fetchxml,
        count=1,
    )

# Fetch and update each view's fetchxml
def update_view_filter(view_id, exclude_userid):
    if not view_id or not exclude_userid:
        return
    r = crm_get("savedqueries", {
        "$filter": f"savedqueryid eq {view_id}",
        "$select": "savedqueryid,name,fetchxml",
        "$top": 1,
    })
    rows = r.get("value", [])
    if not rows:
        print(f"  ✗ View {view_id} not found")
        return
    v = rows[0]
    old_fetch = v.get("fetchxml", "")
    # Don't add the filter if it's already there
    if exclude_userid in old_fetch:
        print(f"  ~ {v['name']}: filter already applied")
        return
    new_fetch = add_owner_exclusion(old_fetch, exclude_userid)
    try:
        crm_patch("savedqueries", view_id, {"fetchxml": new_fetch})
        print(f"  ✓ {v['name']}: owner exclusion added")
    except Exception as e:
        print(f"  ✗ {v['name']}: patch failed — {e}")

if dillon_id:
    update_view_filter(view1_id, dillon_id)   # Run Specialty Leads (shared with view2)
    update_view_filter(view3_id, dillon_id)   # Run Specialty Accounts
    update_view_filter(view4_id, dillon_id)   # Run Specialty Leads 2026
    update_view_filter(view5_id, dillon_id)   # Run Specialty Accounts 2026

# ── 3. Hardcoded chart IDs (confirmed from previous run) ─────────────────────
print("\n" + "=" * 60)
print("3. CHART IDs (hardcoded from confirmed CRM values)")
print("=" * 60)
chart1_id = "ad936200-375f-df11-ae90-00155d2e3002"  # Leads by Owner → Run Specialty Leads by Owner
chart2_id = "aed15f95-915e-f111-a826-00224805fad6"  # Run Specialty Leads by Status
chart3_id = "a3a9ee47-5093-de11-97d4-00155da3b01e"  # Accounts by Owner
chart4_id = "eec61ec1-3a5f-df11-ae90-00155d2e3002"  # Incoming Lead Analysis by Month → Leads Created by Month
chart5_id = "5b290fff-355f-df11-ae90-00155d2e3002"  # New Accounts By Month → Accounts Created by Month
print(f"  chart1: {chart1_id}")
print(f"  chart2: {chart2_id}")
print(f"  chart3: {chart3_id}")
print(f"  chart4: {chart4_id}")
print(f"  chart5: {chart5_id}")

# ── 3b. Rename chart records so component headers show correct titles ──────────
print("\n" + "=" * 60)
print("3b. RENAMING CHART RECORDS IN CRM")
print("=" * 60)

chart_renames = [
    (chart1_id, "Run Specialty Leads by Owner"),
    (chart4_id, "Leads Created by Month"),
    (chart5_id, "Accounts Created by Month"),
]
token = get_access_token()
rename_succeeded = {}
for cid, new_name in chart_renames:
    # First fetch current name to confirm what's there
    cur = crm_get("savedqueryvisualizations", {
        "$filter": f"savedqueryvisualizationid eq {cid}",
        "$select": "savedqueryvisualizationid,name,ismanaged",
        "$top": 1,
    })
    cur_rows = cur.get("value", [])
    cur_name = cur_rows[0].get("name", "?") if cur_rows else "NOT FOUND"
    is_managed = cur_rows[0].get("ismanaged", False) if cur_rows else True
    print(f"  Chart {cid}: current name='{cur_name}' ismanaged={is_managed}")

    if cur_name == new_name:
        print(f"    ~ Already named correctly, skipping")
        rename_succeeded[cid] = True
        continue

    try:
        resp = _requests.patch(
            f"{DYNAMICS_URL}/api/data/v9.2/savedqueryvisualizations({cid})",
            json={"name": new_name},
            headers={
                "Authorization": f"Bearer {token}",
                "OData-MaxVersion": "4.0",
                "OData-Version": "4.0",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.ok:
            # Verify the rename actually took
            ver = crm_get("savedqueryvisualizations", {
                "$filter": f"savedqueryvisualizationid eq {cid}",
                "$select": "name", "$top": 1,
            })
            actual = ver.get("value", [{}])[0].get("name", "?")
            if actual == new_name:
                print(f"    ✓ Renamed → '{new_name}'")
                rename_succeeded[cid] = True
            else:
                print(f"    ✗ PATCH returned OK but name is still '{actual}' (system chart is read-only)")
                rename_succeeded[cid] = False
        else:
            print(f"    ✗ PATCH failed ({resp.status_code}): {resp.text[:300]}")
            rename_succeeded[cid] = False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        rename_succeeded[cid] = False

# If system chart rename failed, create custom userqueryvisualization copies with correct names
# These ARE patchable and show in dashboards the same way
any_failed = any(not v for v in rename_succeeded.values())
if any_failed:
    print("\n  System charts are read-only — creating custom chart copies with correct names...")
    custom_chart_map = {}  # cid → new_custom_id
    for cid, new_name in chart_renames:
        if rename_succeeded.get(cid):
            continue
        # Fetch the chart's XML — note: datadescriptionxml is NOT exposed; only presentationdescriptionxml
        chart_r = crm_get("savedqueryvisualizations", {
            "$filter": f"savedqueryvisualizationid eq {cid}",
            "$select": "savedqueryvisualizationid,name,primaryentitytypecode,presentationdescriptionxml",
            "$top": 1,
        })
        chart_rows = chart_r.get("value", [])
        if not chart_rows:
            print(f"    ✗ Could not fetch chart data for {cid}")
            continue
        c = chart_rows[0]
        print(f"    Cloning '{c['name']}' for entity '{c['primaryentitytypecode']}'")
        # POST a new savedqueryvisualization with the renamed name
        try:
            post_resp = _requests.post(
                f"{DYNAMICS_URL}/api/data/v9.2/savedqueryvisualizations",
                json={
                    "name": new_name,
                    "primaryentitytypecode": c["primaryentitytypecode"],
                    "presentationdescriptionxml": c.get("presentationdescriptionxml", ""),
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "OData-MaxVersion": "4.0",
                    "OData-Version": "4.0",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                timeout=30,
            )
            if post_resp.ok:
                new_id = post_resp.json().get("savedqueryvisualizationid")
                if not new_id:
                    loc = post_resp.headers.get("OData-EntityId", "")
                    new_id = loc.split("(")[-1].rstrip(")") if "(" in loc else None
                if new_id:
                    custom_chart_map[cid] = new_id
                    print(f"    ✓ Created '{new_name}' as new chart {new_id}")
                else:
                    print(f"    ✗ Created but could not parse new ID")
            else:
                print(f"    ✗ POST failed ({post_resp.status_code}): {post_resp.text[:300]}")
        except Exception as e:
            print(f"    ✗ POST error: {e}")

    # Remap chart IDs to custom copies
    if chart1_id in custom_chart_map:
        chart1_id = custom_chart_map[chart1_id]
        print(f"  Using custom chart1: {chart1_id}")
    if chart4_id in custom_chart_map:
        chart4_id = custom_chart_map[chart4_id]
        print(f"  Using custom chart4: {chart4_id}")
    if chart5_id in custom_chart_map:
        chart5_id = custom_chart_map[chart5_id]
        print(f"  Using custom chart5: {chart5_id}")

# ── 4. Build formxml ─────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. BUILDING FORMXML")
print("=" * 60)

def make_cell(ctrl_idx, entity, view_id, chart_id, label):
    safe_label = html.escape(label)
    grid_mode = "Chart" if chart_id else "Grid"
    viz = f"<VisualizationId>{{{chart_id}}}</VisualizationId>" if chart_id else "<VisualizationId/>"
    chart_picker = "true" if chart_id else "false"
    cell_id = "{" + str(uuid.uuid4()) + "}"
    ctrl_uid = "{" + str(uuid.uuid4()) + "}"
    return (
        f'<cell colspan="1" rowspan="12" showlabel="true" id="{cell_id}" auto="false">'
        f'<labels><label description="{safe_label}" languagecode="1033"/></labels>'
        f'<control id="RS_{ctrl_idx}" uniqueid="{ctrl_uid}"'
        f' classid="{{E7A81278-8635-4d9e-8D4D-59480B391C5B}}" isrequired="false">'
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

def make_col(comps, sec_name):
    sec_id = "{" + str(uuid.uuid4()) + "}"
    rows_xml = ""
    for (ctrl_idx, entity, view_id, chart_id, label) in comps:
        if not view_id:
            print(f"  SKIPPING '{label}' — no view ID")
            continue
        rows_xml += f"<row>{make_cell(ctrl_idx, entity, view_id, chart_id, label)}</row>"
        rows_xml += "<row/>" * 11  # 11 continuation rows for rowspan=12
        print(f"  + {label}")
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
    (0, "lead",    view1_id, chart1_id, "Run Specialty Leads by Owner"),
    (1, "lead",    view2_id, chart2_id, "Leads by Status"),
    (2, "account", view3_id, chart3_id, "Accounts by Owner"),
]
right_comps = [
    (3, "lead",    view4_id, chart4_id, "Leads Created by Month"),
    (4, "account", view5_id, chart5_id, "Accounts Created by Month"),
]

print("Left column:")
left_xml = make_col(left_comps, "section_left")
print("Right column:")
right_xml = make_col(right_comps, "section_right")

new_formxml = (
    '<form>'
    '<tabs>'
    f'<tab name="tab" showlabel="false" locklevel="0" id="{tab_id}" expanded="true">'
    '<labels><label description="Summary" languagecode="1033"/></labels>'
    f'<columns>{left_xml}{right_xml}</columns>'
    '</tab>'
    '</tabs>'
    '</form>'
)
print(f"\nGenerated formxml length: {len(new_formxml)}")

# ── 5. PATCH the dashboard ────────────────────────────────────────────────────
if not dash_id:
    print("\nNo dashboard to patch — run 'Create the Run Specialty Dashboard' via the agent first.")
    sys.exit(1)

print("\n" + "=" * 60)
print("5. PATCHING DASHBOARD")
print("=" * 60)
try:
    crm_patch("systemforms", dash_id, {
        "formxml": new_formxml,
        "name": DASHBOARD_NAME,
        "formactivationstate": 1,
    })
    print(f"  ✓ PATCH succeeded for {dash_id}")
except Exception as e:
    print(f"  ✗ PATCH failed: {e}")
    sys.exit(1)

# ── 6. Verify stored formxml ──────────────────────────────────────────────────
print("\n" + "=" * 60)
print("6. VERIFYING STORED FORMXML")
print("=" * 60)
v_r = crm_get("systemforms", {
    "$filter": f"formid eq {dash_id}",
    "$select": "formxml,name,formactivationstate",
    "$top": 1,
})
stored = v_r.get("value", [{}])[0]
stored_xml = stored.get("formxml", "")
viz_ids = re.findall(r'<VisualizationId>\{([^}]+)\}</VisualizationId>', stored_xml)
view_ids_stored = re.findall(r'<ViewId>\{([^}]+)\}</ViewId>', stored_xml)
labels = [l for l in re.findall(r'description="([^"]*)"', stored_xml) if l and l != "Summary"]
print(f"  Name: {stored.get('name')}")
print(f"  Active: {stored.get('formactivationstate')}")
print(f"  Stored formxml length: {len(stored_xml)}")
print(f"  ViewIds stored:          {view_ids_stored}")
print(f"  VisualizationIds stored: {viz_ids}")
print(f"  Labels: {labels[:10]}")

# ── 7. Publish ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("7. PUBLISHING")
print("=" * 60)
try:
    publish_xml = (
        "<importexportxml>"
        "<dashboards>"
        f"<dashboard>{dash_id}</dashboard>"
        "</dashboards>"
        "</importexportxml>"
    )
    crm_action("PublishXml", {"ParameterXml": publish_xml})
    print("  ✓ PublishXml targeted")
except Exception as e:
    print(f"  ~ Targeted publish failed ({e}), trying PublishAllXml...")
    try:
        crm_action("PublishAllXml", {})
        print("  ✓ PublishAllXml")
    except Exception as e2:
        print(f"  ✗ Failed: {e2}")

print(f"""
Done.
Dashboard ID: {dash_id}
URL to verify in browser (replace ORG with your org name):
  https://[ORG].crm.dynamics.com/main.aspx?pagetype=dashboard&id={dash_id}

After refreshing CRM, confirm you see ONE Run Specialty Dashboard.
""")
