"""
Fix: Add missing tyr_tyrtype option values to the Contact entity.

The Account tyr_tyrtype field has more options than the Contact version.
54 contacts failed to sync because their Account has values 935650018 or
935650019 which don't exist on the Contact field.

This script:
  1. Reads all tyr_tyrtype options from Account
  2. Reads all tyr_tyrtype options from Contact
  3. Adds any missing ones to Contact (using the same label as Account)
  4. Publishes the Contact entity

Run: python fix_tyrtype_options.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_action, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")


def get_picklist_options(entity):
    meta = crm_get(
        f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='tyr_tyrtype')"
        f"/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
        {"$select": "LogicalName", "$expand": "OptionSet"},
    )
    options = meta.get("OptionSet", {}).get("Options", [])
    result = {}
    for opt in options:
        lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
        result[opt["Value"]] = lls.get("Label", f"Option {opt['Value']}")
    return result


print("Reading Account tyr_tyrtype options...")
acct_options = get_picklist_options("account")
print(f"  Account has {len(acct_options)} options: {sorted(acct_options.keys())}")

print("Reading Contact tyr_tyrtype options...")
cont_options = get_picklist_options("contact")
print(f"  Contact has {len(cont_options)} options: {sorted(cont_options.keys())}")

missing = {v: label for v, label in acct_options.items() if v not in cont_options}

if not missing:
    print("\nNo missing options — Contact already has all Account options.")
else:
    print(f"\nMissing from Contact: {missing}")
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    for value, label in sorted(missing.items()):
        print(f"Adding value {value} ('{label}') to Contact tyr_tyrtype...")
        body = {
            "AttributeLogicalName": "tyr_tyrtype",
            "EntityLogicalName": "contact",
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
            print(f"  OK - Added {value} ('{label}')")
        else:
            print(f"  FAILED - {resp.status_code}: {resp.text[:300]}")

    print("\nPublishing Contact entity...")
    crm_action("PublishXml", {
        "ParameterXml": "<importexportxml><entities><entity>contact</entity></entities></importexportxml>"
    })
    print("Done! Contact tyr_tyrtype now has all missing options.")
    print("\nNext step: re-run your sync script to pick up the 54 contacts that previously failed.")
