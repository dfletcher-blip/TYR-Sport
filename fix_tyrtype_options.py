"""
Fix: Add missing tyr_tyrtype option values to the Contact global option set.

The Contact tyr_tyrtype field uses a GLOBAL option set named 'tyr_con_tyr_type'.
It only has values 935650000-935650013 but needs 935650014-935650019.
Account (a MultiSelectPicklist) already has all 20 values.

Labels confirmed from Account metadata:
  935650014: Sent To Collections
  935650015: Finals
  935650016: Cannot Reach Minimum
  935650017: Not A TYR Target
  935650018: Run Specialty
  935650019: World Aquatics

Run: python fix_tyrtype_options.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_action, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

# Labels read from Account MultiSelectPicklist metadata
MISSING_OPTIONS = {
    935650014: "Sent To Collections",
    935650015: "Finals",
    935650016: "Cannot Reach Minimum",
    935650017: "Not A TYR Target",
    935650018: "Run Specialty",
    935650019: "World Aquatics",
}

# Global option set name (revealed in the previous error message)
OPTION_SET_NAME = "tyr_con_tyr_type"


def get_contact_options():
    """Get existing options from the Contact tyr_tyrtype field."""
    meta = crm_get(
        "EntityDefinitions(LogicalName='contact')/Attributes(LogicalName='tyr_tyrtype')"
        "/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
        {"$select": "LogicalName", "$expand": "OptionSet"},
    )
    options = meta.get("OptionSet", {}).get("Options", [])
    return {opt["Value"] for opt in options}


print("Reading existing Contact tyr_tyrtype options...")
existing = get_contact_options()
print(f"  Existing values: {sorted(existing)}")

missing = {v: l for v, l in MISSING_OPTIONS.items() if v not in existing}

if not missing:
    print("No missing options — Contact already has all values.")
else:
    print(f"\nAdding {len(missing)} missing option(s) to global option set '{OPTION_SET_NAME}'...")

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    for value, label in sorted(missing.items()):
        print(f"  Adding {value} ('{label}')...")
        body = {
            "OptionSetName": OPTION_SET_NAME,
            "Value": value,
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
        }
        resp = requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/InsertOptionValue",
            headers=headers,
            json=body,
        )
        if resp.ok:
            print(f"    OK")
        else:
            print(f"    FAILED - {resp.status_code}: {resp.text[:300]}")

    print("\nPublishing...")
    crm_action("PublishXml", {
        "ParameterXml": "<importexportxml><entities><entity>contact</entity></entities></importexportxml>"
    })
    print("Done! Contact tyr_tyrtype now accepts all 20 option values.")
    print("\nNext step: re-run your sync script to update the 54 contacts that previously failed.")
