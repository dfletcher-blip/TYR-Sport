"""
Reassign accounts listed in Gianluca_Ricci_customers.xlsx to be owned
by Gianluca Ricci in Dynamics CRM.

Accounts are matched by accountnumber (the numeric ID in column A).

Usage:
    python reassign_gianluca_ricci_accounts.py --dry-run   # preview
    python reassign_gianluca_ricci_accounts.py             # apply
"""
import sys, os, time, requests, openpyxl
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
DRY_RUN = "--dry-run" in sys.argv

XLSX = os.path.join(os.path.dirname(__file__),
                    "Gianluca_Ricci_customers.xlsx")

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET", "POST", "PATCH"])
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {"Authorization": f"Bearer {_token['value']}",
         "OData-MaxVersion": "4.0", "OData-Version": "4.0",
         "Accept": "application/json", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h

def get(path, params=None, extra_headers=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(extra_headers), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:400]}")
    return r.json()

def patch(path, body):
    r = _session.patch(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                       headers=get_headers({"If-Match": "*"}), json=body, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PATCH {path} failed {r.status_code}: {r.text[:400]}")
    return r

def find_user(name):
    first, *rest = name.strip().split()
    last = " ".join(rest)
    data = get("systemusers", {
        "$select": "systemuserid,fullname,internalemailaddress",
        "$filter": f"firstname eq '{first}' and lastname eq '{last}' and isdisabled eq false",
    })
    users = data.get("value", [])
    if not users:
        data2 = get("systemusers", {
            "$select": "systemuserid,fullname,internalemailaddress",
            "$filter": f"contains(fullname,'{name}') and isdisabled eq false",
        })
        users = data2.get("value", [])
    return users

# ── Load spreadsheet ──────────────────────────────────────────────────────────
wb = openpyxl.load_workbook(XLSX)
ws = wb.active
accounts_in_sheet = []
for row in ws.iter_rows(values_only=True):
    acct_num, acct_name = row[0], row[1]
    if acct_num:
        accounts_in_sheet.append((str(acct_num).strip(), str(acct_name).strip()))

print(f"Accounts in spreadsheet: {len(accounts_in_sheet)}")
print()

# ── Look up Gianluca Ricci ────────────────────────────────────────────────────
print("Looking up Gianluca Ricci...")
matches = find_user("Gianluca Ricci")
if not matches:
    print("ERROR: Gianluca Ricci not found in Dynamics"); exit(1)
gianluca = matches[0]
print(f"  Found: {gianluca['fullname']} — {gianluca['systemuserid']}")
print()

# ── Process each account ──────────────────────────────────────────────────────
print(f"{'DRY RUN — ' if DRY_RUN else ''}Reassigning accounts to {gianluca['fullname']}...")
print()

ok, skipped, errors = [], [], []

for acct_num, acct_name in accounts_in_sheet:
    try:
        data = get("accounts", {
            "$select": "accountid,name,tyr_as400,_ownerid_value",
            "$filter": f"tyr_as400 eq '{acct_num}'",
        }, extra_headers={"Prefer": "odata.include-annotations=OData.Community.Display.V1.FormattedValue"})
        results = data.get("value", [])
        if not results:
            print(f"  NOT FOUND  [{acct_num}] {acct_name}")
            errors.append((acct_num, acct_name, "not found"))
            continue

        acct = results[0]
        acct_id = acct["accountid"]
        current_owner = acct.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", acct.get("_ownerid_value", "unknown"))

        if acct.get("_ownerid_value") == gianluca["systemuserid"]:
            print(f"  SKIP (already owned)  [{acct_num}] {acct_name}")
            skipped.append((acct_num, acct_name))
            continue

        print(f"  {'WOULD UPDATE' if DRY_RUN else 'UPDATING'}  [{acct_num}] {acct_name}  ({current_owner} -> {gianluca['fullname']})")

        if not DRY_RUN:
            patch(f"accounts({acct_id})",
                  {"ownerid@odata.bind": f"/systemusers({gianluca['systemuserid']})"})
        ok.append((acct_num, acct_name))

    except RuntimeError as e:
        print(f"  ERROR  [{acct_num}] {acct_name}: {e}")
        errors.append((acct_num, acct_name, str(e)))

print()
print("=" * 60)
print(f"{'Would update' if DRY_RUN else 'Updated'} : {len(ok)}")
print(f"Already owned  : {len(skipped)}")
print(f"Errors/missing : {len(errors)}")
if errors:
    print()
    print("Accounts not processed:")
    for num, name, reason in errors:
        print(f"  [{num}] {name} — {reason}")
