"""
Targeted sync: Set tyr_tyrtype = CrossFit (935650004) on all contacts
whose parent account has CrossFit selected.

Run: python sync_crossfit_contacts.py
"""
import os, time, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

# Cache token — fetch once, refresh only on 401
_token_cache = {"token": None, "expires_at": 0}

def get_headers():
    now = time.time()
    if not _token_cache["token"] or now >= _token_cache["expires_at"]:
        _token_cache["token"] = get_access_token()
        _token_cache["expires_at"] = now + 3000  # refresh after 50 minutes
    return {
        "Authorization": f"Bearer {_token_cache['token']}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def request_with_retry(method, url, **kwargs):
    """Make a request, retry up to 3 times on network errors or 401."""
    kwargs.setdefault("timeout", 30)
    for attempt in range(4):
        try:
            resp = method(url, **kwargs)
            if resp.status_code == 401:
                # Force token refresh
                _token_cache["token"] = None
                kwargs["headers"] = get_headers()
                continue
            return resp
        except Exception as e:
            if attempt == 3:
                raise
            wait = 2 ** attempt
            print(f"  Network error (attempt {attempt+1}): {e} — retrying in {wait}s")
            time.sleep(wait)

# Step 1: Get all CrossFit account IDs
print("Getting all CrossFit accounts...")
resp = request_with_retry(
    requests.get,
    f"{DYNAMICS_URL}/api/data/v9.2/accounts",
    headers=get_headers(),
    params={
        "$select": "accountid,name",
        "$filter": "Microsoft.Dynamics.CRM.ContainValues(PropertyName='tyr_tyrtype',PropertyValues=['935650004'])",
        "$top": 5000,
    },
)
if not resp.ok:
    print(f"FAILED to get accounts: {resp.status_code} {resp.text[:200]}")
    exit(1)

crossfit_accounts = resp.json().get("value", [])
print(f"Found {len(crossfit_accounts)} CrossFit accounts\n")

# Step 2: For each account, update its contacts
updated = 0
already_correct = 0
errors = 0

for i, acct in enumerate(crossfit_accounts):
    acct_id = acct["accountid"]

    try:
        resp2 = request_with_retry(
            requests.get,
            f"{DYNAMICS_URL}/api/data/v9.2/contacts",
            headers=get_headers(),
            params={
                "$select": "contactid,fullname,tyr_tyrtype",
                "$filter": f"_parentcustomerid_value eq {acct_id}",
                "$top": 500,
            },
        )
    except Exception as e:
        print(f"  Skipping account {acct_id}: {e}")
        errors += 1
        continue

    if not resp2.ok:
        continue

    for contact in resp2.json().get("value", []):
        if contact.get("tyr_tyrtype") == CROSSFIT_VALUE:
            already_correct += 1
            continue

        try:
            patch = request_with_retry(
                requests.patch,
                f"{DYNAMICS_URL}/api/data/v9.2/contacts({contact['contactid']})",
                headers={**get_headers(), "If-Match": "*"},
                json={"tyr_tyrtype": CROSSFIT_VALUE},
            )
            if patch.ok:
                updated += 1
            else:
                errors += 1
                print(f"  Error on {contact.get('fullname')}: {patch.text[:150]}")
        except Exception as e:
            errors += 1
            print(f"  Network error patching {contact.get('fullname')}: {e}")

    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(crossfit_accounts)} accounts processed — {updated} updated, {errors} errors")

print(f"\nDone.")
print(f"  Updated:         {updated}")
print(f"  Already correct: {already_correct}")
print(f"  Errors:          {errors}")
