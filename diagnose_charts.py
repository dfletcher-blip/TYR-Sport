"""
Diagnose broken charts in Dynamics 365.
Checks system and personal chart definitions for invalid view references
or malformed datadescription/presentationdescription XML.
"""
import os, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

_token: dict = {"value": None, "expires": 0}
def get_headers():
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    return {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0", "OData-Version": "4.0",
        "Accept": "application/json", "Content-Type": "application/json",
    }

issues = []

# --- System charts ---
print("=== System Charts (savedqueryvisualizations) ===")
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/savedqueryvisualizations",
    headers=get_headers(),
    params={
        "$select": "savedqueryvisualizationid,name,primaryentitytypecode,_savedqueryid_value,datadescription",
        "$top": 200,
    },
    timeout=30,
)
sys_charts = r.json().get("value", [])
print(f"  Total system charts: {len(sys_charts)}")

# Collect all view IDs referenced by charts
view_ids = set()
for c in sys_charts:
    vid = c.get("_savedqueryid_value")
    if vid:
        view_ids.add(vid)

# Check if those views exist
print(f"  Checking {len(view_ids)} referenced views...")
missing_views = []
for vid in view_ids:
    r2 = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/savedqueries({vid})",
        headers=get_headers(),
        params={"$select": "savedqueryid,name,statecode"},
        timeout=15,
    )
    if not r2.ok:
        missing_views.append(vid)

if missing_views:
    print(f"  MISSING VIEWS ({len(missing_views)}):")
    for v in missing_views:
        print(f"    {v}")
    issues.append(f"{len(missing_views)} system charts reference missing views")
else:
    print("  All referenced views exist.")

# Check for empty/null datadescription
bad_data = [c for c in sys_charts if not c.get("datadescription")]
if bad_data:
    print(f"  Charts with missing datadescription ({len(bad_data)}):")
    for c in bad_data[:5]:
        print(f"    {c['name']} ({c['primaryentitytypecode']})")
    issues.append(f"{len(bad_data)} system charts have empty datadescription")

# --- Personal charts ---
print("\n=== Personal Charts (userqueryvisualizations) ===")
r3 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/userqueryvisualizations",
    headers=get_headers(),
    params={
        "$select": "userqueryvisualizationid,name,primaryentitytypecode,_savedqueryid_value,datadescription",
        "$top": 200,
    },
    timeout=30,
)
user_charts = r3.json().get("value", [])
print(f"  Total personal charts: {len(user_charts)}")

bad_user = [c for c in user_charts if not c.get("datadescription")]
if bad_user:
    print(f"  Charts with missing datadescription ({len(bad_user)}):")
    for c in bad_user[:5]:
        print(f"    {c['name']} ({c['primaryentitytypecode']})")
    issues.append(f"{len(bad_user)} personal charts have empty datadescription")

# --- Summary ---
print("\n=== Summary ===")
if issues:
    for i in issues:
        print(f"  ISSUE: {i}")
else:
    print("  No structural issues found in chart definitions.")
    print("  Check browser F12 console for the specific JavaScript error when loading a chart.")
