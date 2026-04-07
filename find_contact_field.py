# Quick diagnostic — find the TYR Type field name on Contact
from dotenv import load_dotenv
load_dotenv()
from config.crm_connection import crm_get

# Get one contact with all fields to find the tyr_type field
result = crm_get("contacts", {"$top": 1, "$select": "*"})
contacts = result.get("value", [])
if contacts:
    c = contacts[0]
    print("Fields on Contact that contain 'tyr':")
    for k, v in c.items():
        if "tyr" in k.lower():
            print(f"  {k} = {v}")
    print("\nAll custom fields (tyr_ or new_ prefix):")
    for k, v in c.items():
        if k.startswith("tyr_") or k.startswith("new_") or k.startswith("cr"):
            print(f"  {k} = {v}")
