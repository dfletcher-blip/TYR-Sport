"""
Fix: Align Contact tyr_tyrtype labels with Account labels.

The Contact global option set 'tyr_con_tyr_type' has wrong labels for
values 935650003-935650013. They are shifted/different from Account.
The sync copies the right numeric values but Contact shows wrong labels.

This script:
  1. Updates Contact labels to match Account for all mismatched values
  2. Deletes incorrectly added value 935650020 (Crossfit) from Contact
     (real CrossFit = 935650004, which will be fixed by label update)
  3. Publishes the Contact entity

Run: python fix_tyrtype_labels.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_action, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
OPTION_SET_NAME = "tyr_con_tyr_type"

# Correct label mapping from Account (source of truth)
# Only includes values that need to be fixed on Contact
CORRECT_LABELS = {
    935650003: "Direct To Consumer Teams",
    935650004: "CrossFit",
    935650005: "Athlete/Promotion",
    935650006: "TYR Endurance Sport",
    935650007: "Discounter",
    935650008: "International",
    935650009: "TYR EU",
    935650010: "TYR Web",
    935650011: "TYR Internal",
    935650012: "Inactive",
    935650013: "Out of Business",
}

def get_headers():
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

# ── Step 1: Fix mismatched labels ────────────────────────────
print("Updating Contact tyr_tyrtype labels to match Account...\n")
for value, label in sorted(CORRECT_LABELS.items()):
    print(f"  Setting {value} = '{label}'...")
    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/UpdateOptionValue",
        headers=get_headers(),
        json={
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
        },
    )
    if resp.ok:
        print(f"    OK")
    else:
        print(f"    FAILED - {resp.status_code}: {resp.text[:300]}")

# ── Step 2: Delete incorrectly added 935650020 (Crossfit) ────
print("\nRemoving incorrectly added value 935650020 (Crossfit)...")
resp = requests.post(
    f"{DYNAMICS_URL}/api/data/v9.2/DeleteOptionValue",
    headers=get_headers(),
    json={
        "OptionSetName": OPTION_SET_NAME,
        "Value": 935650020,
    },
)
if resp.ok:
    print("  OK - Removed 935650020")
else:
    print(f"  FAILED - {resp.status_code}: {resp.text[:300]}")

# ── Step 3: Publish ───────────────────────────────────────────
print("\nPublishing Contact entity...")
crm_action("PublishXml", {
    "ParameterXml": "<importexportxml><entities><entity>contact</entity></entities></importexportxml>"
})
print("Done!")
print("\nRefresh your CRM. Contact TYR Type labels now match Account.")
print("CrossFit contacts will now correctly show as 'CrossFit' (value 935650004).")
print("\nRe-run compare_tyrtype_labels.py to verify everything matches.")
