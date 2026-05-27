"""
List all amount-related fields on the Opportunity entity so we can identify
what 'Deal Amount' maps to and decide what to do with it.
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
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='opportunity')/Attributes",
    headers=get_headers(),
    params={"$select": "LogicalName,DisplayName,AttributeType,IsCustomAttribute", "$top": 500},
    timeout=30,
)
fields = r.json().get("value", [])

print(f"{'Schema Name':<45} {'Display Name':<35} {'Type':<15} {'Custom'}")
print("-" * 105)
for f in fields:
    label = ((f.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
    logical = f.get("LogicalName", "")
    if "amount" in label.lower() or "amount" in logical.lower():
        print(f"  {logical:<43} {label:<35} {f.get('AttributeType',''):<15} {f.get('IsCustomAttribute')}")
