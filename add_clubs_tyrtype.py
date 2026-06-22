"""
Add "Clubs" as a TYR Type option for Leads, Accounts, Contacts, and Opportunities.

This script inserts "Clubs" into the tyr_tyrtype option set on all four entities
that use it: lead, account, contact, and opportunity.

The option set on Contact (and Leads/Opportunities if they share it) is the global
option set named 'tyr_con_tyr_type'. Account uses a separate MultiSelectPicklist
option set. We insert via InsertOptionValue for each known option set name,
auto-detecting the next available value.

Run: python add_clubs_tyrtype.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_action, get_access_token

DYNAMICS_URL = os.getenv("DYNAMICS_URL", "").rstrip("/")
NEW_LABEL = "Clubs"


def get_headers():
    token = get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def get_options_for_entity(entity: str, attr_type: str) -> list:
    """Fetch existing tyr_tyrtype options for an entity."""
    try:
        meta = crm_get(
            f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='tyr_tyrtype')"
            f"/Microsoft.Dynamics.CRM.{attr_type}",
            {"$select": "LogicalName", "$expand": "OptionSet"},
        )
        return meta.get("OptionSet", {}).get("Options", [])
    except Exception as e:
        print(f"  Warning: could not fetch options for {entity}: {e}")
        return []


def find_tyr_fields(entity: str):
    """List all tyr_ prefixed attributes on an entity to find the right field name."""
    try:
        meta = crm_get(
            f"EntityDefinitions(LogicalName='{entity}')/Attributes",
            {"$filter": "startswith(LogicalName,'tyr_')", "$select": "LogicalName,AttributeType"},
        )
        return [(a["LogicalName"], a.get("AttributeType")) for a in meta.get("value", [])]
    except Exception as e:
        return []


def get_option_set_name(entity: str, attr_type: str) -> tuple:
    """Get the global option set name and resolved attr_type for an entity's tyr_tyrtype field."""
    types_to_try = [attr_type, "MultiSelectPicklistAttributeMetadata", "PicklistAttributeMetadata"]
    seen = []
    for t in types_to_try:
        if t in seen:
            continue
        seen.append(t)
        try:
            meta = crm_get(
                f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='tyr_tyrtype')"
                f"/Microsoft.Dynamics.CRM.{t}",
                {"$select": "LogicalName", "$expand": "OptionSet"},
            )
            name = meta.get("OptionSet", {}).get("Name", "")
            if name:
                return name, t
        except Exception:
            pass
    print(f"  Warning: could not get option set name for {entity} (tried all attribute types)")
    return "", attr_type


def label_exists(options: list, label: str) -> bool:
    """Check if a label already exists in the options list."""
    for opt in options:
        lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
        if lls.get("Label", "").lower() == label.lower():
            return True
    return False


def insert_option(option_set_name: str, value: int, label: str) -> bool:
    """Insert a new option into a global option set. Returns True on success."""
    resp = requests.post(
        f"{DYNAMICS_URL}/api/data/v9.2/InsertOptionValue",
        headers=get_headers(),
        json={
            "OptionSetName": option_set_name,
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
        return True
    else:
        print(f"    FAILED ({resp.status_code}): {resp.text[:300]}")
        return False


def publish_entity(entity: str):
    """Publish an entity so changes are visible in the CRM."""
    crm_action("PublishXml", {
        "ParameterXml": f"<importexportxml><entities><entity>{entity}</entity></entities></importexportxml>"
    })


# ── Entity definitions ────────────────────────────────────────────────────────
# Each entry: (entity_logical_name, attribute_metadata_type)
# Contact, Lead, Opportunity use PicklistAttributeMetadata (single-select)
# Account uses MultiSelectPicklistAttributeMetadata (multi-select)
ENTITIES = [
    ("contact",     "PicklistAttributeMetadata"),
    ("lead",        "PicklistAttributeMetadata"),
    ("opportunity", "PicklistAttributeMetadata"),
    ("account",     "MultiSelectPicklistAttributeMetadata"),
]

print(f"=== Adding '{NEW_LABEL}' to TYR Type (tyr_tyrtype) on all entities ===\n")

# Track which option sets we've already inserted into (they may be shared/global)
inserted_option_sets = {}

for entity, attr_type in ENTITIES:
    print(f"── {entity.capitalize()} ──")

    # Get the option set name (tries fallback attr types automatically)
    optset_name, resolved_type = get_option_set_name(entity, attr_type)
    if not optset_name:
        tyr_fields = find_tyr_fields(entity)
        if tyr_fields:
            print(f"  TYR fields on {entity}: {tyr_fields}")
        print(f"  Could not determine option set name for {entity} — skipping.\n")
        continue
    print(f"  Option set: {optset_name} ({resolved_type})")

    # Get existing options
    options = get_options_for_entity(entity, resolved_type)
    print(f"  Current options: {len(options)}")

    if label_exists(options, NEW_LABEL):
        print(f"  '{NEW_LABEL}' already exists — skipping.\n")
        inserted_option_sets[optset_name] = True
        continue

    # Determine next value
    existing_values = {opt["Value"] for opt in options}
    next_value = max(existing_values) + 1 if existing_values else 935650000

    # Check if we already inserted into this option set (shared option sets)
    if optset_name in inserted_option_sets:
        print(f"  Already inserted into '{optset_name}' for another entity — skipping duplicate insert.\n")
        continue

    print(f"  Adding '{NEW_LABEL}' as value {next_value}...")
    success = insert_option(optset_name, next_value, NEW_LABEL)

    if success:
        print(f"  OK — '{NEW_LABEL}' added as value {next_value}")
        inserted_option_sets[optset_name] = True
        print(f"  Publishing {entity}...")
        publish_entity(entity)
        print(f"  Published.\n")
    else:
        print(f"  FAILED to add '{NEW_LABEL}' to {entity}.\n")

print("=== Done! ===")
print(f"\n'{NEW_LABEL}' has been added as a TYR Type option.")
print("Refresh your CRM to see the updated TYR Type dropdown on Leads, Accounts, Contacts, and Opportunities.")
