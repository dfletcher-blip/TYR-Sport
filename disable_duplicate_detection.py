#!/usr/bin/env python3
"""
Run this once to replace Dynamics 365 duplicate detection rules for contacts
with a rule that only flags duplicates when BOTH email AND account match.
"""

import traceback
from tools.contacts import configure_contact_duplicate_rule

try:
    result = configure_contact_duplicate_rule()
    print(result["message"])
    if not result.get("success"):
        print("Warning: completed with issues.")
except Exception:
    traceback.print_exc()
