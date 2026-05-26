#!/usr/bin/env python3
"""
Disables all duplicate detection rules for contacts in Dynamics 365.
"""

import traceback
from tools.contacts import disable_duplicate_detection_rules

try:
    result = disable_duplicate_detection_rules("contact")
    print(result["message"])
except Exception:
    traceback.print_exc()
