"""
Diagnose: Compare CrossFit count between Accounts and Contacts.
Also shows what tyr_tyrtype value gets synced from CrossFit accounts to their contacts.
Run: python diagnose_crossfit_sync.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

def get_headers():
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Prefer": "odata.include-annotations=OData.Community.Display.V1.FormattedValue",
    }

# ── Count Accounts with CrossFit ──────────────────────────────
print("Counting Accounts with CrossFit (935650004)...")
resp = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/accounts",
    headers=get_headers(),
    params={
        "$select": "accountid,name,tyr_tyrtype",
        "$filter": "Microsoft.Dynamics.CRM.ContainValues(PropertyName='tyr_tyrtype',PropertyValues=['935650004'])",
        "$top": 5000,
    },
)
if not resp.ok:
    # Fallback: try simple string contains
    resp = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/accounts",
        headers=get_headers(),
        params={
            "$select": "accountid,name,tyr_tyrtype",
            "$top": 5000,
        },
    )
    all_accounts = resp.json().get("value", [])
    crossfit_accounts = [
        a for a in all_accounts
        if str(CROSSFIT_VALUE) in str(a.get("tyr_tyrtype") or "")
    ]
else:
    crossfit_accounts = resp.json().get("value", [])

print(f"  Accounts with CrossFit: {len(crossfit_accounts)}")

# Show sample raw tyr_tyrtype values from CrossFit accounts
print("\nSample CrossFit account tyr_tyrtype raw values:")
for a in crossfit_accounts[:5]:
    raw = a.get("tyr_tyrtype")
    fmt = a.get("tyr_tyrtype@OData.Community.Display.V1.FormattedValue", "")
    print(f"  {a.get('name','?')[:40]}: raw={raw!r}  display='{fmt}'")

# ── Count Contacts with CrossFit ──────────────────────────────
print(f"\nCounting Contacts with tyr_tyrtype = {CROSSFIT_VALUE}...")
resp2 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/contacts",
    headers=get_headers(),
    params={
        "$select": "contactid,fullname,tyr_tyrtype,_parentcustomerid_value",
        "$filter": f"tyr_tyrtype eq {CROSSFIT_VALUE}",
        "$top": 5000,
    },
)
crossfit_contacts = resp2.json().get("value", []) if resp2.ok else []
print(f"  Contacts with CrossFit: {len(crossfit_contacts)}")

# ── Sample: what value do contacts of CrossFit accounts have? ─
if crossfit_accounts:
    print("\nChecking what tyr_tyrtype value contacts of CrossFit accounts actually have...")
    sample_acct = crossfit_accounts[0]
    acct_id = sample_acct["accountid"]
    resp3 = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/contacts",
        headers=get_headers(),
        params={
            "$select": "fullname,tyr_tyrtype",
            "$filter": f"_parentcustomerid_value eq {acct_id}",
            "$top": 5,
        },
    )
    if resp3.ok:
        contacts = resp3.json().get("value", [])
        print(f"  Account: {sample_acct.get('name')} (raw tyr_tyrtype={sample_acct.get('tyr_tyrtype')!r})")
        for c in contacts:
            fmt = c.get("tyr_tyrtype@OData.Community.Display.V1.FormattedValue", "")
            print(f"    Contact {c.get('fullname','?')}: tyr_tyrtype={c.get('tyr_tyrtype')!r} ('{fmt}')")
