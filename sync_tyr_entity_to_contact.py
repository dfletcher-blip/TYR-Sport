"""
Agent: Find 'TYR entity' field on Account, create it on Contact if missing,
then sync values from Account to Contact.

Set TYR_ENTITY_FIELD env var to override auto-detection, e.g.:
  TYR_ENTITY_FIELD=tyr_entitytype python sync_tyr_entity_to_contact.py
"""
import os, json, requests, time, uuid
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
OVERRIDE_FIELD = os.getenv("TYR_ENTITY_FIELD", "").strip()

_token = {"value": None, "expires": 0}

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

# Step 1: Find TYR entity field on Account
print("Step 1: Searching for 'entity' field on Account...")
all_acct_fields = []
url = f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='account')/Attributes"
params = {"$select": "LogicalName,DisplayName,AttributeType,SchemaName", "$top": 500}
while url:
    r = requests.get(url, headers=get_headers(), params=params, timeout=30)
    all_acct_fields.extend(r.json().get("value", []))
    url = r.json().get("@odata.nextLink")
    params = None

def label(f):
    return ((f.get("DisplayName") or {}).get("UserLocalizedLabel") or {}).get("Label", "").lower()

# Always show all TYR fields for reference
all_tyr = [f for f in all_acct_fields if "tyr" in f.get("LogicalName","").lower()]
print(f"\n  ALL TYR fields on Account ({len(all_tyr)} total):")
for f in all_tyr:
    lbl = label(f)
    print(f"  {f['LogicalName']:45s} ({f['AttributeType']:25s}) — {lbl}")
print()

# If override specified, use that field directly
if OVERRIDE_FIELD:
    matched = [f for f in all_acct_fields if f.get("LogicalName","").lower() == OVERRIDE_FIELD.lower()]
    if not matched:
        print(f"ERROR: Field '{OVERRIDE_FIELD}' not found on Account.")
        exit(1)
    tyr_entity_fields = matched
    print(f"Using override field: {OVERRIDE_FIELD}\n")
else:
    # Auto-detect: both "tyr" AND "entit" in logical name or display label
    tyr_entity_fields = [
        f for f in all_acct_fields
        if ("tyr" in f.get("LogicalName","").lower() and "entit" in f.get("LogicalName","").lower())
        or ("tyr" in label(f) and "entit" in label(f))
    ]
    print(f"  Auto-detected {len(tyr_entity_fields)} TYR entity field(s):")
    for f in tyr_entity_fields:
        print(f"  LogicalName: {f['LogicalName']}")
        print(f"  DisplayName: {label(f)}")
        print(f"  Type:        {f['AttributeType']}")
    print()

    if not tyr_entity_fields:
        print("No field matched 'tyr'+'entit'.")
        print("Set TYR_ENTITY_FIELD=<LogicalName> to specify the field manually.")
        print("Example:")
        print("  TYR_ENTITY_FIELD=tyr_entity python sync_tyr_entity_to_contact.py")
        exit(0)

field = tyr_entity_fields[0]
field_logical = field["LogicalName"]
field_schema = field["SchemaName"]
field_type = field["AttributeType"]
print(f"Using field: {field_logical} (type: {field_type})\n")

# Step 2: Check if field already exists on Contact
print("Step 2: Checking if field exists on Contact...")
r2 = requests.get(
    f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='contact')/Attributes(LogicalName='{field_logical}')",
    headers=get_headers(),
    timeout=30,
)
if r2.ok:
    print(f"  Field '{field_logical}' already exists on Contact — skipping creation.\n")
else:
    print(f"  Field '{field_logical}' not on Contact — creating it...")

    # 2a. Fetch attribute metadata
    r_meta = requests.get(
        f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='account')/Attributes(LogicalName='{field_logical}')",
        headers=get_headers(),
        timeout=30,
    )
    meta = r_meta.json()
    field_odata_type = meta.get("@odata.type", "")
    print(f"  odata.type: {field_odata_type}")
    # Show all non-system keys for debugging
    user_keys = {k: v for k, v in meta.items() if not k.startswith("@") and v is not None}
    print(f"  Meta properties: {list(user_keys.keys())}")

    # 2b. Base payload
    payload = {
        "@odata.type": field_odata_type,
        "LogicalName": field_logical,
        "SchemaName": field_schema,
        "DisplayName": meta.get("DisplayName"),
        "RequiredLevel": {
            "Value": "None",
            "CanBeChanged": True,
            "ManagedPropertyLogicalName": "canmodifyrequirementlevelsettings",
        },
    }

    # 2c. Resolve option set for Picklist / MultiSelectPicklist
    if "Picklist" in field_odata_type or "MultiSelectPicklist" in field_odata_type:
        os_resolved = False
        cast = (
            "Microsoft.Dynamics.CRM.MultiSelectPicklistAttributeMetadata"
            if "MultiSelectPicklist" in field_odata_type
            else "Microsoft.Dynamics.CRM.PicklistAttributeMetadata"
        )

        # Use $expand=OptionSet via collection-level cast — confirmed working in diagnostic
        r_os = requests.get(
            f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='account')/Attributes/{cast}",
            headers=get_headers(),
            params={"$filter": f"LogicalName eq '{field_logical}'", "$expand": "OptionSet"},
            timeout=30,
        )
        print(f"  OptionSet $expand fetch: {r_os.status_code}")
        if r_os.ok:
            items = r_os.json().get("value", [])
            if items and items[0].get("OptionSet"):
                os_data = items[0]["OptionSet"]
                is_global = os_data.get("IsGlobal", False)
                os_name = os_data.get("Name", "")
                print(f"  IsGlobal={is_global}, Name={os_name!r}")
                if is_global and os_name:
                    metadata_id = os_data.get("MetadataId", "")
                    print(f"  MetadataId: {metadata_id}")
                    # Use @odata.bind to reference existing global option set
                    # (cannot pass IsGlobal=True via OptionSet key — API rejects it)
                    payload["GlobalOptionSet@odata.bind"] = f"/GlobalOptionSetDefinitions({metadata_id})"
                    os_resolved = True
                    print(f"  -> Bound to global OptionSet: {os_name} ({metadata_id})")
                else:
                    # Local option set — copy definition, strip read-only fields
                    strip = {"MetadataId", "@odata.context", "@odata.type", "HasChanged",
                             "IsCustomOptionSet", "IsManaged", "IsCustomizable"}
                    os_copy = {k: v for k, v in os_data.items() if k not in strip}
                    os_copy["@odata.type"] = "Microsoft.Dynamics.CRM.OptionSetMetadata"
                    payload["OptionSet"] = os_copy
                    os_resolved = True
                    print(f"  -> Local OptionSet copied ({len(os_data.get('Options',[]))} options)")
            else:
                print(f"  No OptionSet in $expand response: {r_os.text[:200]}")
        else:
            print(f"  $expand fetch failed: {r_os.text[:200]}")

        # Fallback: GlobalOptionSetDefinitions filtered by name
        if not os_resolved:
            gos_name = field_logical
            r_gos = requests.get(
                f"{DYNAMICS_URL}/api/data/v9.2/GlobalOptionSetDefinitions",
                headers=get_headers(),
                params={"$filter": f"Name eq '{gos_name}'", "$select": "Name,MetadataId"},
                timeout=30,
            )
            print(f"  GlobalOptionSetDefinitions filter '{gos_name}': {r_gos.status_code}")
            if r_gos.ok and r_gos.json().get("value"):
                mid = r_gos.json()["value"][0]["MetadataId"]
                payload["GlobalOptionSet@odata.bind"] = f"/GlobalOptionSetDefinitions({mid})"
                os_resolved = True
                print(f"  -> Bound to global OptionSet: {gos_name} ({mid})")

        if not os_resolved:
            print("  ERROR: Could not resolve OptionSet by any method. Cannot create Picklist field.")
            print("  Options:")
            print("    1. Add the field manually in Dynamics 365 customisation UI.")
            print("    2. Check the global option set name and set TYR_ENTITY_FIELD or hardcode.")
            exit(1)

    print(f"  Payload keys: {list(payload.keys())}")

    r_create = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/EntityDefinitions(LogicalName='contact')/Attributes",
        headers=get_headers(),
        json=payload,
        timeout=30,
    )
    if r_create.ok or r_create.status_code == 204:
        print(f"  Created '{field_logical}' on Contact.\n")
        print("  Publishing customizations...")
        r_pub = requests.post(
            f"{DYNAMICS_URL}/api/data/v9.2/PublishXml",
            headers=get_headers(),
            json={"ParameterXml": "<importexportxml><entities><entity>contact</entity></entities></importexportxml>"},
            timeout=60,
        )
        print(f"  Publish response: {r_pub.status_code}\n")
    else:
        print(f"  FAILED to create: {r_create.status_code} {r_create.text[:800]}")
        exit(1)

# Step 3: Sync values from Account to Contact
print("Step 3: Syncing values from Account to Contact...")
all_contacts = []
url = f"{DYNAMICS_URL}/api/data/v9.2/contacts"
params = {
    "$select": f"contactid,{field_logical}",
    "$expand": f"parentcustomerid_account($select={field_logical})",
    "$filter": "parentcustomerid_account ne null",
    "$top": 1000,
}
while url:
    r = requests.get(url, headers=get_headers(), params=params, timeout=60)
    data = r.json()
    if not r.ok:
        print(f"  ERROR fetching contacts: {r.status_code} {r.text[:300]}")
        exit(1)
    all_contacts.extend(data.get("value", []))
    url = data.get("@odata.nextLink")
    params = None
    time.sleep(0.5)

print(f"  Found {len(all_contacts)} contacts with parent accounts\n")

to_update = []
for c in all_contacts:
    acct = c.get("parentcustomerid_account") or {}
    acct_val = acct.get(field_logical)
    contact_val = c.get(field_logical)
    if acct_val is not None and acct_val != contact_val:
        to_update.append({"contactid": c["contactid"], field_logical: acct_val})

print(f"  Contacts needing sync: {len(to_update)}\n")

if not to_update:
    print("All contacts already in sync.")
    exit(0)

# Batch update
BATCH_SIZE = 50
updated = errors = 0
total_batches = (len(to_update) + BATCH_SIZE - 1) // BATCH_SIZE

for batch_num, start in enumerate(range(0, len(to_update), BATCH_SIZE), 1):
    batch = to_update[start:start + BATCH_SIZE]
    boundary = f"batch_{uuid.uuid4().hex}"
    parts = []
    for c in batch:
        cid = c["contactid"]
        val = c[field_logical]
        payload = json.dumps({field_logical: val})
        parts.append(
            f"--{boundary}\r\nContent-Type: application/http\r\nContent-Transfer-Encoding: binary\r\n\r\n"
            f"PATCH {DYNAMICS_URL}/api/data/v9.2/contacts({cid}) HTTP/1.1\r\n"
            f"Content-Type: application/json\r\nIf-Match: *\r\n\r\n{payload}\r\n"
        )
    body = "".join(parts) + f"--{boundary}--\r\n"
    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/$batch",
        headers=get_headers({"Content-Type": f"multipart/mixed; boundary={boundary}"}),
        data=body.encode("utf-8"),
        timeout=120,
    )
    if resp.ok:
        ok = resp.text.count("HTTP/1.1 204")
        updated += ok
        errors += len(batch) - ok
        print(f"  Batch {batch_num}/{total_batches}: {ok} updated")
    else:
        errors += len(batch)
        print(f"  Batch {batch_num}/{total_batches} FAILED: {resp.status_code}")
    time.sleep(1)

print(f"\nDone. Updated: {updated}, Errors: {errors}")
