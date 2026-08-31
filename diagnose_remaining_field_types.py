"""
Before adding "copy all field information" to the Convert to Contact
button, check the real AttributeType of every field in the native
Lead->Account map we haven't already verified -- we've been burned twice
now by custom tyr_* fields turning out to be Virtual/multiselect
(requiring string values) when their naming looked like a normal
single-value Picklist. Better to check all of them up front than hit
another crash-fix-crash cycle field by field.

Also confirms whether tyr_lead / transactioncurrencyid are real lookups
and what navigation property name to use for binding them.

Read-only. Makes no changes.

Usage:
    python diagnose_remaining_field_types.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

# Fields being considered for the "copy all field information" expansion,
# in (lead_field, account_field) pairs from the native EntityMap, minus
# originatingleadid/originatingleadidname (intentionally skipped) and the
# read-only ownerid*/transactioncurrencyidname annotation fields.
CANDIDATE_ACCOUNT_FIELDS = [
    "tyr_approvedcredit", "tyr_teamtype", "tyr_paymenttype", "tyr_creditcardonfile",
    "revenue", "transactioncurrencyid", "preferredcontactmethodcode", "sic",
    "telephone1", "telephone2", "websiteurl", "industrycode", "emailaddress1",
    "donotphone", "donotpostalmail", "fax", "numberofemployees",
    "donotbulkemail", "donotemail", "followemail", "donotfax", "description",
    "address1_stateorprovince", "address1_country", "address1_line3",
    "address1_postalcode", "address1_line1", "address1_line2", "address1_city",
    "donotsendmm", "yominame", "tyr_approvalstatus", "tyr_lead", "tyr_leadname",
]

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

print("=" * 70)
print("Account attribute types for candidate 'copy all fields' additions")
print("=" * 70)

data = get("EntityDefinitions(LogicalName='account')/Attributes", {
    "$select": "LogicalName,AttributeType,IsValidForCreate",
})
by_name = {a.get("LogicalName"): a for a in data.get("value", [])}

for field in CANDIDATE_ACCOUNT_FIELDS:
    a = by_name.get(field)
    if not a:
        print(f"  {field:30s}  ! NOT FOUND on account")
        continue
    atype = a.get("AttributeType")
    creatable = a.get("IsValidForCreate")
    flag = ""
    if atype in ("Virtual",):
        flag = "  <-- MULTISELECT, needs String()"
    elif atype == "Lookup":
        flag = "  <-- LOOKUP, needs @odata.bind"
    elif not creatable:
        flag = "  <-- NOT VALID FOR CREATE, skip"
    print(f"  {field:30s}  type={atype:12s}  IsValidForCreate={creatable}{flag}")

print()

print("=" * 70)
print("Lookup navigation property names (for @odata.bind) -- tyr_lead, transactioncurrencyid")
print("=" * 70)
for field in ("tyr_lead", "transactioncurrencyid"):
    a = by_name.get(field)
    if not a:
        print(f"  {field}: not found")
        continue
    if a.get("AttributeType") != "Lookup":
        print(f"  {field}: not a Lookup (type={a.get('AttributeType')}), skip nav lookup")
        continue
    try:
        detail = get(
            f"EntityDefinitions(LogicalName='account')/Attributes(LogicalName='{field}')/Microsoft.Dynamics.CRM.LookupAttributeMetadata",
            {"$select": "LogicalName,Targets"},
        )
        print(f"  {field}: Targets={detail.get('Targets')}")
    except RuntimeError as e:
        print(f"  {field}: lookup metadata failed: {e}")

    try:
        rel_data = get("RelationshipDefinitions", {
            "$select": "SchemaName,ReferencingEntity,ReferencingAttribute,ReferencedEntity",
            "$filter": f"ReferencingEntity eq 'account' and ReferencingAttribute eq '{field}'",
        })
        for rel in rel_data.get("value", []):
            print(f"    relationship schema name (nav property): {rel.get('SchemaName')}  -> {rel.get('ReferencedEntity')}")
    except RuntimeError as e:
        print(f"    ! relationship lookup failed: {e}")

print()
print("Done. This is read-only -- nothing was changed.")
