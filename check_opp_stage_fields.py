"""
Check what stage-related fields exist on the Opportunity entity
and whether stageid / processid are present and filterable.
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

# 1. Find stage/process fields in metadata
print("=== Stage-related fields on Opportunity ===")
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='opportunity')/Attributes",
    headers=get_headers(),
    params={"$select": "LogicalName,DisplayName,AttributeType,IsValidForAdvancedFind", "$top": 500},
    timeout=30,
)
fields = r.json().get("value", [])
print(f"{'Schema Name':<35} {'Display Name':<30} {'Type':<15} {'AdvFind'}")
print("-" * 90)
for f in fields:
    label = ((f.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
    logical = f.get("LogicalName", "")
    if any(x in logical.lower() for x in ["stage", "process", "tyr_stage"]):
        print(f"  {logical:<33} {label:<30} {f.get('AttributeType',''):<15} {f.get('IsValidForAdvancedFind')}")

# 2. Sample opportunity — what do stage fields actually contain?
print("\n=== Sample opportunity stage field values ===")
r2 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/opportunities",
    headers=get_headers(),
    params={"$select": "opportunityid,name,stageid,processid,tyr_stage", "$top": 5, "$filter": "statecode eq 0"},
    timeout=30,
)
for o in r2.json().get("value", []):
    print(f"  {(o.get('name') or 'Unnamed')[:40]}")
    print(f"    stageid:    {o.get('stageid')}")
    print(f"    processid:  {o.get('processid')}")
    print(f"    tyr_stage:  {o.get('tyr_stage')}")
