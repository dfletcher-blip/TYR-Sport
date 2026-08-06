"""
Add "HYROX" and "Run Club" as business type options on the tyr_tyrtype
field for both the Lead and Account entities.

Run: python add_hyrox_runclub_business_type.py
"""
from dotenv import load_dotenv
load_dotenv()

from tools.form_customization import add_optionset_value

FIELD = "tyr_tyrtype"
NEW_LABELS = ["HYROX", "Run Club"]
ENTITIES = ["lead", "account"]

for entity in ENTITIES:
    print(f"\n{entity.upper()} — {FIELD}")
    result = add_optionset_value(entity, FIELD, NEW_LABELS)

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        continue

    for item in result["added"]:
        print(f"  OK - added '{item['label']}' (value {item['value']})")
    for label in result["skipped_existing"]:
        print(f"  skipped '{label}' — already exists")
    for item in result["failed"]:
        print(f"  FAILED - '{item['label']}': {item['error']}")

print("\nDone.")
