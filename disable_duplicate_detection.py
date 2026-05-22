#!/usr/bin/env python3
"""
Run this once to replace Dynamics 365 duplicate detection rules for contacts
with a rule that only flags duplicates when BOTH email AND account match.
"""

from tools.contacts import configure_contact_duplicate_rule

result = configure_contact_duplicate_rule()
print(result["message"])
