"""
Debug: read back form XML from our created dashboards using impersonation.
Run with: python debug_dashboard_xml.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
USER_EMAIL = os.getenv("DYNAMICS_USER_EMAIL", "")

# Step 1: Get Dillon's user ID
print(f"Looking up user: {USER_EMAIL}")
result = crm_get("systemusers", {
    "$filter": f"internalemailaddress eq '{USER_EMAIL}'",
    "$select": "systemuserid,fullname",
    "$top": 1,
})
users = result.get("value", [])
if not users:
    print("ERROR: user not found")
    exit(1)
user_id = users[0]["systemuserid"]
print(f"User ID: {user_id}")

# Step 2: Query userforms WITH impersonation
token = get_access_token()
headers = {
    "Authorization": f"Bearer {token}",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Accept": "application/json",
    "MSCRMCallerID": user_id,
}

print("\n=== Personal Dashboards (as Dillon) ===")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/userforms?$select=userformid,name,formxml&$filter=type eq 0",
    headers=headers,
)
if not resp.ok:
    print(f"FAILED: {resp.status_code} {resp.text[:300]}")
else:
    dashboards = resp.json().get("value", [])
    print(f"Found {len(dashboards)} personal dashboard(s)")
    for db in dashboards:
        print(f"\nName: {db.get('name')}")
        print(f"ID:   {db.get('userformid')}")
        xml = db.get("formxml", "")
        print(f"XML (first 1000 chars):\n{xml[:1000]}")
        print("-" * 60)

# Step 3: Sample view and chart IDs
print("\n=== Sample Opportunity View IDs ===")
views = crm_get("savedqueries", {
    "$filter": "returnedtypecode eq 'opportunity' and querytype eq 0 and statecode eq 0",
    "$select": "savedqueryid,name",
    "$top": 5,
})
for v in views.get("value", []):
    print(f"  {v['name']} => {v['savedqueryid']}")

print("\n=== Sample Opportunity Chart IDs ===")
charts = crm_get("savedqueryvisualizations", {
    "$filter": "primaryentitytypecode eq 'opportunity'",
    "$select": "savedqueryvisualizationid,name",
    "$top": 5,
})
for c in charts.get("value", []):
    print(f"  {c['name']} => {c['savedqueryvisualizationid']}")

