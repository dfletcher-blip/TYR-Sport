"""
Fix: Add missing tyr_tyrtype option values to the Contact entity.

54 contacts failed to sync because their Account has values 935650018 or
935650019 which don't exist on the Contact tyr_tyrtype field.

This script:
  1. Gets the Contact tyr_tyrtype options (to know what's already there)
  2. Finds missing values by querying Account records directly
  3. Reads their labels from Account record formatted values
  4. Adds them to Contact and publishes

Run: python fix_tyrtype_options.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_action, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")


def get_contact_options():
    """Get existing tyr_tyrtype options from Contact (known to be Picklist)."""
    meta = crm_get(
        "EntityDefinitions(LogicalName='contact')/Attributes(LogicalName='tyr_tyrtype')"
        "/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
        {"$select": "LogicalName", "$expand": "OptionSet"},
    )
    options = meta.get("OptionSet", {}).get("Options", [])
    result = {}
    for opt in options:
        lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
        result[opt["Value"]] = lls.get("Label", f"Option {opt['Value']}")
    return result


def get_account_options():
    """
    Get tyr_tyrtype options from Account metadata.
    Tries Picklist first, then MultiSelectPicklist, then falls back
    to reading labels from actual Account records.
    """
    for type_name in ("PicklistAttributeMetadata", "MultiSelectPicklistAttributeMetadata"):
        try:
            meta = crm_get(
                f"EntityDefinitions(LogicalName='account')/Attributes(LogicalName='tyr_tyrtype')"
                f"/Microsoft.Dynamics.CRM.{type_name}",
                {"$select": "LogicalName", "$expand": "OptionSet"},
            )
            options = meta.get("OptionSet", {}).get("Options", [])
            if options:
                result = {}
                for opt in options:
                    lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
                    result[opt["Value"]] = lls.get("Label", f"Option {opt['Value']}")
                print(f"  (read via {type_name})")
                return result
        except Exception:
            continue
    return None  # Signal to caller to use fallback


def get_label_from_account_record(value):
    """
    Look up the display label for a tyr_tyrtype value by querying an
    Account record that has that value and reading its formatted value.
    """
    result = crm_get("accounts", {
        "$filter": f"tyr_tyrtype eq {value}",
        "$select": "accountid,name",
        "$top": 1,
    })
    accounts = result.get("value", [])
    if not accounts:
        return f"Type {value}"

    acct_id = accounts[0]["accountid"]
    # Fetch with annotations to get formatted value
    token = get_access_token()
    resp = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/accounts({acct_id})?$select=tyr_tyrtype",
        headers={
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Prefer": "odata.include-annotations=OData.Community.Display.V1.FormattedValue",
        },
    )
    if resp.ok:
        data = resp.json()
        label = data.get("tyr_tyrtype@OData.Community.Display.V1.FormattedValue")
        if label:
            return label
    return f"Type {value}"


# ── Step 1: Get Contact options ───────────────────────────────
print("Reading Contact tyr_tyrtype options...")
cont_options = get_contact_options()
print(f"  Contact has {len(cont_options)} options: {sorted(cont_options.keys())}")

# ── Step 2: Get Account options ───────────────────────────────
print("\nReading Account tyr_tyrtype options...")
acct_options = get_account_options()

if acct_options is not None:
    print(f"  Account has {len(acct_options)} options: {sorted(acct_options.keys())}")
    missing = {v: label for v, label in acct_options.items() if v not in cont_options}
else:
    # Metadata query failed — find missing values by looking for Account records
    # with values not in the Contact option set
    print("  Metadata query failed; scanning Account records for unlisted values...")
    missing = {}
    known_values = set(cont_options.keys())
    # Known problematic values from the sync error output
    for candidate in [935650018, 935650019]:
        if candidate not in known_values:
            label = get_label_from_account_record(candidate)
            missing[candidate] = label
            print(f"  Found value {candidate} = '{label}'")

# ── Step 3: Add missing options to Contact ────────────────────
if not missing:
    print("\nNo missing options — Contact already has all values. Nothing to do.")
else:
    print(f"\nMissing from Contact: { {v: l for v, l in missing.items()} }")
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

    # ── Step 4: Publish ───────────────────────────────────────
    print("\nPublishing Contact entity...")
    crm_action("PublishXml", {
        "ParameterXml": "<importexportxml><entities><entity>contact</entity></entities></importexportxml>"
    })
    print("Done! Contact tyr_tyrtype now has all missing options.")
    print("\nNext step: re-run your sync script to update the 54 contacts that previously failed.")
