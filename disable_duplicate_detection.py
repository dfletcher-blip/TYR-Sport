#!/usr/bin/env python3
"""
Run this once to disable Dynamics 365 duplicate detection rules
for contacts and accounts.
"""

from tools.contacts import disable_duplicate_detection_rules

for entity in ("contact", "account"):
    result = disable_duplicate_detection_rules(entity)
    print(result["message"])
