"""
Swap opportunity amount field display names:
  budgetamount   → "Amount"      (this is the actual deal value on the form)
  estimatedvalue → "Est. Revenue" (unused, restore to original)

Run with --dry-run to preview without making changes.
"""
import os, sys, requests, time
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

RENAMES = [
    ("budgetamount",   "Amount"),
    ("estimatedvalue", "Est. Revenue"),
]

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

def get_current_label(field):
    r = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='opportunity')/Attributes(LogicalName='{field}')",
        headers=get_headers(),
        params={"$select": "LogicalName,DisplayName,AttributeType"},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    meta = r.json()
    label = ((meta.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "unknown")
    odata_type = meta.get("@odata.type", "Microsoft.Dynamics.CRM.MoneyAttributeMetadata")
    return label, odata_type

def rename_field(field, new_label, odata_type):
    payload = {
        "@odata.type": odata_type,
        "DisplayName": {
            "LocalizedLabels": [{"Label": new_label, "LanguageCode": 1033}],
            "UserLocalizedLabel": {"Label": new_label, "LanguageCode": 1033},
        },
    }
    for attempt in range(1, 5):
        try:
            r = requests.put(
                f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='opportunity')/Attributes(LogicalName='{field}')",
                headers=get_headers({"If-Match": "*", "MSCRM.MergeLabels": "true"}),
                json=payload,
                timeout=120,
            )
            return r
        except requests.exceptions.Timeout:
            wait = 2 ** attempt
            print(f"    Timeout on attempt {attempt}/4 — retrying in {wait}s...")
            time.sleep(wait)
    return None

# --- Preview or apply ---
for field, new_label in RENAMES:
    current_label, odata_type = get_current_label(field)
    if current_label == new_label:
        print(f"  {field}: already '{new_label}' — skipping")
        continue
    if DRY_RUN:
        print(f"  DRY RUN: {field} '{current_label}' → '{new_label}'")
        continue
    print(f"  Renaming {field}: '{current_label}' → '{new_label}'...")
    r = rename_field(field, new_label, odata_type)
    if r is None:
        print(f"    ERROR: all attempts timed out.")
    elif r.ok or r.status_code == 204:
        print(f"    Done.")
    else:
        print(f"    ERROR: {r.status_code} {r.text[:200]}")

if not DRY_RUN:
    print("\nPublishing Opportunity entity...")
    r = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/PublishXml",
        headers=get_headers(),
        json={"ParameterXml": "<importexportxml><entities><entity>opportunity</entity></entities></importexportxml>"},
        timeout=60,
    )
    if r.ok or r.status_code == 204:
        print("  Published. Refresh your browser to see the changes.")
    else:
        print(f"  Publish warning: {r.status_code} {r.text[:200]}")
