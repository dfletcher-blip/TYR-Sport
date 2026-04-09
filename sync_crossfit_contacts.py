"""
Targeted sync: Set tyr_tyrtype = CrossFit (935650004) on all contacts
whose parent account has CrossFit selected AND who currently have null tyr_tyrtype.

Uses FetchXML (inner join) to get contacts efficiently, then batch PATCH.
"""
import os, time, uuid, requests
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
CROSSFIT_VALUE = 935650004

_token_cache = {"token": None, "expires_at": 0}

def get_token():
    now = time.time()
    if not _token_cache["token"] or now >= _token_cache["expires_at"]:
        print("  Fetching auth token...")
        _token_cache["token"] = get_access_token()
        _token_cache["expires_at"] = now + 3000
    return _token_cache["token"]

def get_headers(extra=None):
    h = {
        "Authorization": f"Bearer {get_token()}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

# FetchXML: contacts with null tyr_tyrtype whose parent account has CrossFit
FETCH_XML = """
<fetch>
  <entity name="contact">
    <attribute name="contactid"/>
    <attribute name="tyr_tyrtype"/>
    <filter>
      <condition attribute="tyr_tyrtype" operator="null"/>
    </filter>
    <link-entity name="account" from="accountid" to="parentcustomerid" link-type="inner">
      <filter>
        <condition attribute="tyr_tyrtype" operator="contain-values">
          <value>935650004</value>
        </condition>
      </filter>
    </link-entity>
  </entity>
</fetch>
"""

# --- Step 1: Collect all matching contacts via FetchXML paging ---
print("Step 1: Finding contacts with null tyr_tyrtype from CrossFit accounts...")
all_contacts = []
page = 1
paging_cookie = None

while True:
    fetch = FETCH_XML.strip()
    # Insert paging attributes
    if paging_cookie:
        import xml.sax.saxutils as saxutils
        cookie_escaped = saxutils.escape(paging_cookie)
        fetch = fetch.replace(
            "<fetch>",
            f'<fetch page="{page}" paging-cookie="{cookie_escaped}">'
        )
    else:
        fetch = fetch.replace("<fetch>", f'<fetch page="{page}" count="500">')

    print(f"  Page {page}...", end=" ", flush=True)
    resp = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/contacts",
        headers=get_headers({"Prefer": "odata.include-annotations=Microsoft.Dynamics.CRM.fetchxmlpagingcookie"}),
        params={"fetchXml": fetch},
        timeout=60,
    )

    if not resp.ok:
        print(f"\nFAILED: {resp.status_code} {resp.text[:500]}")
        exit(1)

    data = resp.json()
    batch = data.get("value", [])
    all_contacts.extend(batch)
    print(f"{len(batch)} contacts (total: {len(all_contacts)})")

    # Check for next page
    paging_annotation = data.get("@Microsoft.Dynamics.CRM.fetchxmlpagingcookie")
    if not paging_annotation or len(batch) == 0:
        break

    # Extract raw cookie from annotation
    import urllib.parse
    paging_cookie = urllib.parse.unquote(paging_annotation)
    page += 1

print(f"\nContacts to update: {len(all_contacts)}")
if not all_contacts:
    print("Nothing to update!")
    exit(0)

# --- Step 2: Batch PATCH (50 per request) ---
print("\nStep 2: Updating via batch API...")
BATCH_SIZE = 50
updated = 0
errors = 0
total_batches = (len(all_contacts) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, batch_start in enumerate(range(0, len(all_contacts), BATCH_SIZE), 1):
    batch = all_contacts[batch_start:batch_start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"

    parts = []
    for c in batch:
        parts.append(
            f"--{boundary}\r\n"
            f"Content-Type: application/http\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({c['contactid']}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\n"
            f"If-Match: *\r\n\r\n"
            f'{{"tyr_tyrtype": {CROSSFIT_VALUE}}}\r\n'
        )
    body = "".join(parts) + f"--{boundary}--\r\n"

    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
        data=body.encode("utf-8"),
        timeout=120,
    )

    if resp.ok:
        ok_count = resp.text.count("HTTP/1.1 204")
        fail_count = len(batch) - ok_count
        updated += ok_count
        errors += fail_count
        print(f"  Batch {batch_num}/{total_batches}: {ok_count} updated, {fail_count} errors")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code} {resp.text[:200]}")

print(f"\nDone.")
print(f"  Updated: {updated}")
print(f"  Errors:  {errors}")
