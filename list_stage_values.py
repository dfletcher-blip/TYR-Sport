"""
List all option values for the tyr_stage field on Opportunity.
These are the values to use when filtering opportunities by stage.
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

r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='opportunity')"
    f"/Attributes(LogicalName='tyr_stage')/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
    headers=get_headers(),
    params={"$select": "LogicalName", "$expand": "OptionSet"},
    timeout=30,
)
if not r.ok:
    print(f"ERROR: {r.status_code} {r.text[:300]}")
    exit(1)

options = r.json().get("OptionSet", {}).get("Options", [])
print(f"{'Integer Value':<20} Label")
print("-" * 50)
for o in options:
    label = (o.get("Label", {}).get("UserLocalizedLabel") or {}).get("Label", "")
    print(f"  {o.get('Value'):<18} {label}")

print(f"\nFilter example: tyr_stage eq <integer value>")
