"""
Diagnostic: inspect Run Specialty Dashboard formxml and all referenced views.
Run this locally to see exactly what's in CRM and why panels are blank.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config.crm_connection import crm_get, crm_patch, crm_action
import json, re

DASHBOARD_NAME = "Run Specialty Dashboard"

# ── 1. Fetch the dashboard formxml ────────────────────────────────────────
print("=" * 70)
print("1. CURRENT DASHBOARD FORMXML")
print("=" * 70)
resp = crm_get("systemforms", {
    "$filter": f"name eq '{DASHBOARD_NAME}' and type eq 0",
    "$select": "formid,name,formxml,formactivationstate",
    "$top": 1,
})
rows = resp.get("value", [])
if not rows:
    print("Dashboard not found in CRM.")
    sys.exit(1)

dash = rows[0]
formid = dash["formid"]
formxml = dash.get("formxml", "")
print(f"formid: {formid}")
print(f"formactivationstate: {dash.get('formactivationstate')}")
print(f"formxml length: {len(formxml)} chars")
print()

# Extract all ViewId values from formxml
view_ids = re.findall(r'<ViewId>\{([^}]+)\}</ViewId>', formxml)
print(f"ViewId references in formxml ({len(view_ids)} found):")
for vid in view_ids:
    print(f"  {{{vid}}}")
print()

# Extract all TargetEntityType values
entities = re.findall(r'<TargetEntityType>([^<]+)</TargetEntityType>', formxml)
print(f"TargetEntityType values: {entities}")
print()

# Extract all cell labels
labels = re.findall(r'<labels><label description="([^"]*)" languagecode="1033"/></labels>', formxml)
print(f"Cell labels found: {labels}")
print()

print("Full formxml:")
print(formxml)
print()

# ── 2. Check each referenced view ────────────────────────────────────────
print("=" * 70)
print("2. CHECKING REFERENCED VIEWS IN CRM")
print("=" * 70)
for vid in view_ids:
    r = crm_get("savedqueries", {
        "$filter": f"savedqueryid eq {vid}",
        "$select": "savedqueryid,name,returnedtypecode,statecode,statuscode,querytype,fetchxml",
        "$top": 1,
    })
    vrows = r.get("value", [])
    if vrows:
        v = vrows[0]
        print(f"  FOUND: {v['name']}")
        print(f"    entity={v.get('returnedtypecode')} statecode={v.get('statecode')} querytype={v.get('querytype')}")
        print(f"    fetchxml: {v.get('fetchxml','')[:200]}")
    else:
        print(f"  MISSING: {{{vid}}} not found in savedqueries!")
    print()

# ── 3. Check our named views exist ───────────────────────────────────────
print("=" * 70)
print("3. CHECKING NAMED VIEWS EXIST")
print("=" * 70)
for name in ["Run Specialty Leads", "Run Specialty Accounts",
             "Run Specialty Leads 2026", "Run Specialty Accounts 2026"]:
    r = crm_get("savedqueries", {
        "$filter": f"name eq '{name}' and querytype eq 0",
        "$select": "savedqueryid,name,returnedtypecode,statecode",
        "$top": 2,
    })
    vrows = r.get("value", [])
    if vrows:
        for v in vrows:
            print(f"  FOUND: {v['name']} | id={v['savedqueryid']} | entity={v.get('returnedtypecode')} | statecode={v.get('statecode')}")
    else:
        print(f"  MISSING: {name}")
print()

# ── 4. Check charts ──────────────────────────────────────────────────────
print("=" * 70)
print("4. AVAILABLE CHARTS")
print("=" * 70)
for entity in ["lead", "account"]:
    r = crm_get("savedqueryvisualizations", {
        "$filter": f"primaryentitytypecode eq '{entity}'",
        "$select": "savedqueryvisualizationid,name",
        "$top": 10,
    })
    charts = r.get("value", [])
    print(f"  Charts for {entity}:")
    for c in charts:
        print(f"    {c['name']} | {c['savedqueryvisualizationid']}")
print()
