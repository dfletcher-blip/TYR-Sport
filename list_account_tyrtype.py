"""
List all tyr_tyrtype options on Account (MultiSelectPicklist).
Run: python list_account_tyrtype.py
"""
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import crm_get

meta = crm_get(
    "EntityDefinitions(LogicalName='account')/Attributes(LogicalName='tyr_tyrtype')"
    "/Microsoft.Dynamics.CRM.MultiSelectPicklistAttributeMetadata",
    {"$select": "LogicalName", "$expand": "OptionSet"},
)
options = meta.get("OptionSet", {}).get("Options", [])
optset_name = meta.get("OptionSet", {}).get("Name", "unknown")
print(f"Option set name: {optset_name}")
print(f"Total options: {len(options)}\n")
for opt in sorted(options, key=lambda x: x["Value"]):
    lls = (opt.get("Label") or {}).get("UserLocalizedLabel") or {}
    print(f"  {opt['Value']}: {lls.get('Label', '(no label)')}")
