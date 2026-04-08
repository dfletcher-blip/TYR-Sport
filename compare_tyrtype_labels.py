"""
Compare tyr_tyrtype labels between Account and Contact side by side.
Run: python compare_tyrtype_labels.py
"""
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import crm_get

def get_options(entity, attr_type):
    meta = crm_get(
        f"EntityDefinitions(LogicalName='{entity}')/Attributes(LogicalName='tyr_tyrtype')"
        f"/Microsoft.Dynamics.CRM.{attr_type}",
        {"$select": "LogicalName", "$expand": "OptionSet"},
    )
    options = meta.get("OptionSet", {}).get("Options", [])
    return {
        opt["Value"]: ((opt.get("Label") or {}).get("UserLocalizedLabel") or {}).get("Label", "")
        for opt in options
    }

acct = get_options("account", "MultiSelectPicklistAttributeMetadata")
cont = get_options("contact", "PicklistAttributeMetadata")

all_values = sorted(set(list(acct.keys()) + list(cont.keys())))

print(f"{'Value':<15} {'Account Label':<35} {'Contact Label':<35} {'Match?'}")
print("-" * 95)
mismatches = 0
for v in all_values:
    a = acct.get(v, "(missing)")
    c = cont.get(v, "(missing)")
    match = "OK" if a == c else "MISMATCH"
    if match == "MISMATCH":
        mismatches += 1
    print(f"{v:<15} {a:<35} {c:<35} {match}")

print(f"\nTotal mismatches: {mismatches}")
