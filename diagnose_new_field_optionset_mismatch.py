"""
The "copy all fields" expansion just crashed with the same "picklist not
in range" error we've seen before. Following today's established pattern,
the most likely culprits are the custom tyr_* Picklist fields we just
added raw copies for -- tyr_teamtype, tyr_paymenttype, tyr_approvalstatus
-- since every tyr_* field checked so far has turned out to have a
DIFFERENT option set between Lead and Account despite the same name.

industrycode and preferredcontactmethodcode are standard OOB Dynamics
fields with a genuinely shared global option set across entities, so
they're checked too but are expected to be fine.

Read-only. Makes no changes.

Usage:
    python diagnose_new_field_optionset_mismatch.py
"""
import os, time, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")

FIELDS = ["tyr_teamtype", "tyr_paymenttype", "tyr_approvalstatus", "industrycode", "preferredcontactmethodcode"]
ENTITIES = ["lead", "account"]

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

results = {}

for field in FIELDS:
    results[field] = {}
    for entity in ENTITIES:
        print("=" * 60)
        print(f"{entity}.{field}")
        print("=" * 60)
        try:
            detail = get(
                f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='{field}')/Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
                {"$expand": "OptionSet,GlobalOptionSet"},
            )
            options = ((detail.get("OptionSet") or {}).get("Options")) or \
                      ((detail.get("GlobalOptionSet") or {}).get("Options")) or []
            is_global = bool(detail.get("GlobalOptionSet"))
            print(f"  Option set type: {'GLOBAL (shared)' if is_global else 'LOCAL (entity-specific)'}")
            value_to_label = {}
            for o in options:
                label = ((o.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
                value_to_label[o.get("Value")] = label
                print(f"    {o.get('Value')} = {label}")
            results[field][entity] = value_to_label
        except RuntimeError as e:
            print(f"  ! Lookup failed: {e}")
        print()

print("=" * 60)
print("Comparison")
print("=" * 60)
for field in FIELDS:
    lead_opts = results.get(field, {}).get("lead", {})
    acct_opts = results.get(field, {}).get("account", {})
    if not lead_opts or not acct_opts:
        print(f"  {field}: could not compare (missing data for one side)")
        continue
    same_values = set(lead_opts.keys()) == set(acct_opts.keys())
    same_labels_at_same_values = all(lead_opts.get(v) == acct_opts.get(v) for v in lead_opts if v in acct_opts)
    if same_values and same_labels_at_same_values:
        print(f"  {field}: IDENTICAL option set on both entities -- direct value copy is safe.")
    else:
        print(f"  {field}: DIFFERENT option sets -- must map by label text, not raw value.")
print()

print("Done. This is read-only -- nothing was changed.")
