"""
Fix: update the 'estimatedvalue' field's global display name on Opportunity
     from whatever it currently is (e.g. "Est. Revenue") to "Amount",
     so it matches the form label and shows correctly in view filters.

Run with --dry-run to preview without making changes.
"""
import os, sys, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv
FIELD = "estimatedvalue"
ENTITY = "opportunity"
NEW_LABEL = "Amount"

_token: dict = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {
        "Authorization": f"Bearer {_token['value']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

# Step 1: Fetch current metadata
print(f"Fetching current metadata for '{FIELD}' on {ENTITY}...")
r = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='{ENTITY}')/Attributes(LogicalName='{FIELD}')",
    headers=get_headers({"Prefer": "odata.include-annotations=*"}),
    params={"$select": "LogicalName,DisplayName,AttributeType"},
    timeout=30,
)
if not r.ok:
    print(f"  ERROR: {r.status_code} {r.text[:300]}")
    exit(1)

meta = r.json()
current_label = (
    (meta.get("DisplayName") or {})
    .get("UserLocalizedLabel", {})
    .get("Label", "unknown")
)
attr_type = meta.get("AttributeType", "")
odata_type = meta.get("@odata.type", "")

print(f"  Current display name : '{current_label}'")
print(f"  Attribute type       : {attr_type}")
print(f"  OData type           : {odata_type}\n")

if current_label == NEW_LABEL:
    print(f"Display name is already '{NEW_LABEL}'. Nothing to do.")
    exit(0)

if DRY_RUN:
    print(f"DRY RUN — would rename '{current_label}' → '{NEW_LABEL}' on {ENTITY}.{FIELD}")
    exit(0)

# Step 2: Patch display name
print(f"Updating display name: '{current_label}' → '{NEW_LABEL}'...")
payload = {
    "@odata.type": odata_type or "Microsoft.Dynamics.CRM.MoneyAttributeMetadata",
    "DisplayName": {
        "LocalizedLabels": [{"Label": NEW_LABEL, "LanguageCode": 1033}],
        "UserLocalizedLabel": {"Label": NEW_LABEL, "LanguageCode": 1033},
    },
}
r2 = requests.put(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='{ENTITY}')/Attributes(LogicalName='{FIELD}')",
    headers=get_headers({"If-Match": "*", "MSCRM.MergeLabels": "true"}),
    json=payload,
    timeout=30,
)
if not (r2.ok or r2.status_code == 204):
    print(f"  ERROR: {r2.status_code} {r2.text[:300]}")
    exit(1)
print(f"  Field metadata updated.\n")

# Step 3: Publish the entity so the change takes effect
print("Publishing Opportunity entity...")
r3 = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/PublishXml",
    headers=get_headers(),
    json={"ParameterXml": "<importexportxml><entities><entity>opportunity</entity></entities></importexportxml>"},
    timeout=60,
)
if r3.ok or r3.status_code == 204:
    print("  Published successfully.\n")
else:
    print(f"  Publish warning: {r3.status_code} {r3.text[:200]}\n")

print(f"Done. '{FIELD}' on Opportunity now displays as '{NEW_LABEL}' in view filters and column headers.")
print("Refresh your browser to see the change.")
