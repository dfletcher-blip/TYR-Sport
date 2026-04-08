"""
List all current tyr_tyrtype options on Contact, then add any missing ones.
Run: python add_tyrtype_option.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_action, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
OPTION_SET_NAME = "tyr_con_tyr_type"

# ── List current options ──────────────────────────────────────
meta = crm_get(
    "EntityDefinitions(LogicalName='contact')/Attributes(LogicalName='tyr_tyrtype')"
    "/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
    {"$select": "LogicalName", "$expand": "OptionSet"},
)
options = meta.get("OptionSet", {}).get("Options", [])
print(f"Current TYR Type options ({len(options)} total):")
for opt in sorted(options, key=lambda x: x["Value"]):
    lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
    print(f"  {opt['Value']}: {lls.get('Label', '(no label)')}")

existing_labels = {
    (lls := (opt.get("Label") or {}).get("UserLocalizedLabel") or {}) and lls.get("Label", "").lower()
    for opt in options
}
existing_values = {opt["Value"] for opt in options}
next_value = max(existing_values) + 1

# ── Add Crossfit if missing ───────────────────────────────────
to_add = [
    ("Crossfit", None),  # None = auto-assign next value
]

print()
for label, value in to_add:
    if label.lower() in existing_labels:
        print(f"'{label}' already exists — skipping.")
        continue

    use_value = value if value else next_value
    next_value += 1

    print(f"Adding '{label}' (value {use_value})...")
    token = get_access_token()
    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/InsertOptionValue",
        headers={
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={
            "OptionSetName": OPTION_SET_NAME,
            "Value": use_value,
            "Label": {
                "@odata.type": "Microsoft.Dynamics.CRM.Label",
                "LocalizedLabels": [{
                    "@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
                    "Label": label,
                    "LanguageCode": 1033,
                }],
                "UserLocalizedLabel": {
                    "@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
                    "Label": label,
                    "LanguageCode": 1033,
                },
            },
            "SolutionUniqueName": "Default",
        },
    )
    if resp.ok:
        print(f"  OK - '{label}' added as value {use_value}")
    else:
        print(f"  FAILED - {resp.status_code}: {resp.text[:300]}")

print("\nPublishing...")
crm_action("PublishXml", {
    "ParameterXml": "<importexportxml><entities><entity>contact</entity></entities></importexportxml>"
})
print("Done! Refresh your CRM to see the updated TYR Type options.")
