"""
Debug: read back form XML from our created dashboards and from a working one.
Run with: python debug_dashboard_xml.py
"""
import os, json, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

# Step 1: List all personal dashboards (userforms)
print("=== Personal Dashboards (userforms) ===")
result = crm_get("userforms", {
    "$select": "userformid,name,formxml",
    "$filter": "type eq 0",
    "$top": 10,
})
userforms = result.get("value", [])
for uf in userforms:
    print(f"\nName: {uf.get('name')}")
    print(f"ID:   {uf.get('userformid')}")
    xml = uf.get("formxml", "")
    print(f"XML (first 800 chars):\n{xml[:800]}")
    print("-" * 60)

# Step 2: Look up a real view ID for opportunity
print("\n=== Sample Opportunity View IDs ===")
views = crm_get("savedqueries", {
    "$filter": "returnedtypecode eq 'opportunity' and querytype eq 0 and statecode eq 0",
    "$select": "savedqueryid,name",
    "$top": 5,
})
for v in views.get("value", []):
    print(f"  {v['name']} => {v['savedqueryid']}")

# Step 3: Look up a real chart ID for opportunity
print("\n=== Sample Opportunity Chart IDs ===")
charts = crm_get("savedqueryvisualizations", {
    "$filter": "primaryentitytypecode eq 'opportunity'",
    "$select": "savedqueryvisualizationid,name",
    "$top": 5,
})
for c in charts.get("value", []):
    print(f"  {c['name']} => {c['savedqueryvisualizationid']}")
