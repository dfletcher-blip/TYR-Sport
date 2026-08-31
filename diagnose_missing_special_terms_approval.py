"""
ST-202608-11456 (Account: Kimberly High School, Approval Status: Submitted)
was submitted but has zero related Special Terms Approval records -- the
"Special Terms : Submit for Approval" flow (found earlier this session)
apparently didn't create one.

1. Finds the entity logical names for "Special Terms" and "Special Terms
   Approval" (schema names weren't captured earlier).
2. Finds the ST-202608-11456 record by its name/number.
3. Looks for any related Special Terms Approval records (in case the
   subgrid view was just filtered/wrong, not actually empty).
4. Checks asyncoperations (System Jobs) regarding this record for any
   failed or skipped flow runs, especially "Special Terms : Submit for
   Approval".

Read-only. Makes no changes.

Usage:
    python diagnose_missing_special_terms_approval.py
"""
import os, time, json, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
RECORD_NAME = "ST-202608-11456"

_session = requests.Session()
_retry = Retry(total=4, backoff_factor=3,
               status_forcelist=[429, 500, 502, 503, 504],
               allowed_methods=["GET"])
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://",  HTTPAdapter(max_retries=_retry))

_token = {"value": None, "expires": 0}

def get_headers(extra=None):
    if not _token["value"] or time.time() >= _token["expires"]:
        _token["value"] = get_access_token()
        _token["expires"] = time.time() + 3000
    h = {"Authorization": f"Bearer {_token['value']}",
         "OData-MaxVersion": "4.0", "OData-Version": "4.0",
         "Accept": "application/json", "Content-Type": "application/json",
         "Prefer": "odata.include-annotations=*"}
    if extra:
        h.update(extra)
    return h

def get(path, params=None):
    r = _session.get(f"{DYNAMICS_URL}/api/data/v9.2/{path}",
                     headers=get_headers(), params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"GET {path} failed {r.status_code}: {r.text[:500]}")
    return r.json()

def truncate(val, n=600):
    s = json.dumps(val) if not isinstance(val, str) else val
    return s[:n] + ("...(truncated)" if len(s) > n else "")

print("=" * 70)
print("1. Entity logical names for 'Special Terms' / 'Special Terms Approval'")
print("=" * 70)
entity_data = get("EntityDefinitions", {
    "$select": "LogicalName,DisplayName,EntitySetName",
})
special_terms_entities = []
for e in entity_data.get("value", []):
    display = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
    if "special terms" in display.lower():
        special_terms_entities.append(e)
        print(f"  {e.get('LogicalName')}  (\"{display}\")  EntitySetName={e.get('EntitySetName')}")
print()

# Try to guess the main "Special Terms" entity (not the Approval one) --
# usually the shorter/base name.
main_entity = None
approval_entity = None
for e in special_terms_entities:
    display = ((e.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "") or ""
    if "approval" in display.lower():
        approval_entity = e
    else:
        main_entity = e

if not main_entity:
    print("! Could not identify the main Special Terms entity. Stopping here.")
    raise SystemExit(1)

main_logical = main_entity["LogicalName"]
main_set = main_entity["EntitySetName"]
print(f"Using main entity: {main_logical} (set: {main_set})")
if approval_entity:
    print(f"Using approval entity: {approval_entity['LogicalName']} (set: {approval_entity['EntitySetName']})")
print()

print("=" * 70)
print(f"2. Find record '{RECORD_NAME}'")
print("=" * 70)
# Try common name/number field logical names
record = None
primary_id_field = None
for name_field in ("tyr_name", "name", f"{main_logical}number", "tyr_specialtermsnumber"):
    try:
        data = get(main_set, {
            "$select": "*",
            "$filter": f"{name_field} eq '{RECORD_NAME}'",
            "$top": 1,
        })
        if data.get("value"):
            record = data["value"][0]
            print(f"  Found via field '{name_field}'")
            break
    except RuntimeError:
        continue

if not record:
    print(f"  ! Could not find record by common name fields. Trying a full metadata scan for the primary name attribute...")
    attr_data = get(f"EntityDefinitions(LogicalName='{main_logical}')/Attributes", {
        "$select": "LogicalName,IsPrimaryName",
    })
    primary_field = None
    for a in attr_data.get("value", []):
        if a.get("IsPrimaryName"):
            primary_field = a.get("LogicalName")
            break
    if primary_field:
        print(f"  Primary name field is '{primary_field}', retrying...")
        data = get(main_set, {
            "$select": "*",
            "$filter": f"{primary_field} eq '{RECORD_NAME}'",
            "$top": 1,
        })
        if data.get("value"):
            record = data["value"][0]
            print("  Found.")

if not record:
    print("  ! Still not found. Stopping here -- need the correct field name.")
    raise SystemExit(1)

record_id = None
for k, v in record.items():
    if k.endswith("id") and not k.startswith("_") and k == f"{main_logical}id":
        record_id = v
        break
print(f"  record id: {record_id}")
print(f"  raw record (truncated): {truncate(record, 1000)}")
print()

print("=" * 70)
print("3. Related Special Terms Approval records")
print("=" * 70)
if approval_entity and record_id:
    approval_set = approval_entity["EntitySetName"]
    try:
        # Try common lookup field names pointing back to the Special Term
        for lookup_field in ("tyr_specialterms", "tyr_specialtermsid", f"_{main_logical}_value", "regardingobjectid"):
            try:
                data = get(approval_set, {
                    "$select": "*",
                    "$filter": f"_{lookup_field}_value eq {record_id}" if not lookup_field.startswith("_") else f"{lookup_field} eq {record_id}",
                    "$top": 5,
                })
                if data.get("value"):
                    print(f"  Found {len(data['value'])} via lookup field '{lookup_field}':")
                    for r in data["value"]:
                        print(f"    {truncate(r, 400)}")
                    break
            except RuntimeError:
                continue
        else:
            print("  ! No related approval records found via common lookup field names.")
    except RuntimeError as e:
        print(f"  ! Lookup failed: {e}")
print()

print("=" * 70)
print("4. Async operations (System Jobs) regarding this record")
print("=" * 70)
try:
    jobs_data = get("asyncoperations", {
        "$select": "asyncoperationid,name,statuscode,statecode,message,createdon,completedon",
        "$filter": f"_regardingobjectid_value eq {record_id}",
        "$orderby": "createdon desc",
        "$top": 20,
    })
    jobs = jobs_data.get("value", [])
    if not jobs:
        print("  ! No async operations found regarding this record at all.")
        print("  This suggests the submit action never fired any flow/workflow trigger for this record.")
    for j in jobs:
        print(f"  {j.get('name')}")
        print(f"    statecode/statuscode: {j.get('statecode')}/{j.get('statuscode')}")
        print(f"    created: {j.get('createdon')}  completed: {j.get('completedon')}")
        if j.get("message"):
            print(f"    message: {truncate(j.get('message'), 400)}")
        print()
except RuntimeError as e:
    print(f"  ! Lookup failed: {e}")

print("Done. This is read-only -- nothing was changed.")
