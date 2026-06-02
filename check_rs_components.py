import sys, os
sys.path.insert(0, "/home/user/TYR-Sport")
from config.crm_connection import crm_get

print("=== Checking for Run Specialty views ===")
for name in ["Run Specialty Leads", "Run Specialty Accounts", "Run Specialty Leads 2026", "Run Specialty Accounts 2026"]:
    result = crm_get("savedqueries", {
        "$filter": f"name eq '{name}' and querytype eq 0",
        "$select": "savedqueryid,name,returnedtypecode",
        "$top": 2,
    })
    rows = result.get("value", [])
    if rows:
        for r in rows:
            print(f"  FOUND: {r['name']} | entity={r.get('returnedtypecode')} | id={r['savedqueryid']}")
    else:
        print(f"  MISSING: {name}")

print()
print("=== Checking for system charts ===")
for entity, chart_name in [
    ("lead", "Leads by Owner"),
    ("lead", "Leads by Status"),
    ("account", "Accounts by Owner"),
    ("lead", "Leads by Source"),
    ("account", "Accounts by Industry"),
]:
    result = crm_get("savedqueryvisualizations", {
        "$filter": f"primaryentitytypecode eq '{entity}' and name eq '{chart_name}'",
        "$select": "savedqueryvisualizationid,name",
        "$top": 1,
    })
    rows = result.get("value", [])
    if rows:
        print(f"  FOUND: {rows[0]['name']} | id={rows[0]['savedqueryvisualizationid']}")
    else:
        print(f"  MISSING chart: {chart_name} (entity={entity})")
        # fallback
        r2 = crm_get("savedqueryvisualizations", {
            "$filter": f"primaryentitytypecode eq '{entity}'",
            "$select": "savedqueryvisualizationid,name",
            "$top": 3,
        })
        for r in r2.get("value", []):
            print(f"    Fallback chart: {r['name']} | {r['savedqueryvisualizationid']}")

print()
print("=== Checking current Run Specialty Dashboard formxml ===")
result = crm_get("systemforms", {
    "$filter": "name eq 'Run Specialty Dashboard' and type eq 0",
    "$select": "formid,formxml",
    "$top": 1,
})
rows = result.get("value", [])
if rows:
    formxml = rows[0].get("formxml", "")
    print(f"formid: {rows[0]['formid']}")
    print(f"formxml length: {len(formxml)}")
    print("formxml snippet (first 2000 chars):")
    print(formxml[:2000])
else:
    print("  No dashboard found")
