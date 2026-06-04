#!/usr/bin/env python3
"""
Find the JavaScript web resource on the Contact form that blocks duplicate
email creation, and patch it to remove the check.
"""

import re
import base64
import traceback
from config.crm_connection import crm_get, crm_patch, crm_action

def decode_content(b64):
    try:
        return base64.b64decode(b64).decode("utf-8", errors="replace")
    except Exception:
        return b64

def encode_content(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")

try:
    # 1. Get all JavaScript web resources
    print("Scanning JavaScript web resources for duplicate contact check...")
    js_resources = crm_get("webresourceset", {
        "$select": "webresourceid,name,content",
        "$filter": "webresourcetype eq 3",
        "$top": 500,
    }).get("value", [])

    print(f"  Found {len(js_resources)} JavaScript file(s)\n")

    patched = []

    for wr in js_resources:
        content = decode_content(wr.get("content") or "")
        if not content:
            continue

        # Look for the specific error message pattern
        if "already exists" not in content.lower() and "emailaddress" not in content.lower():
            continue

        # More specific check - look for duplicate contact error patterns
        dup_patterns = [
            r"already exists",
            r"A contact with the email",
            r"Please choose a different email",
        ]
        if not any(re.search(p, content, re.IGNORECASE) for p in dup_patterns):
            continue

        print(f"FOUND: {wr['name']}")

        # Show the suspicious lines for reference
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"already exists|A contact with|Please choose a different email",
                         line, re.IGNORECASE):
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                print("  Relevant code:")
                for l in lines[start:end]:
                    print(f"    {l[:120]}")
                print()

        # Patch: neutralize the duplicate-check block
        # Strategy 1: replace the specific error-throw/notification lines
        original = content

        # Remove Xrm.Navigation.openAlertDialog / showErrorDialog calls near "already exists"
        # and any formContext.getControl().setNotification near email duplicate logic
        # We'll target the if-block that contains "already exists" and replace it with a no-op

        # Pattern: find if-block containing the error message and comment it out
        # Handles both: throwing errors, showing alerts, and Xrm notifications
        new_content = re.sub(
            r'(if\s*\([^)]*email[^)]*\)[^{]*\{[^}]*already exists[^}]*\})',
            r'/* duplicate email check disabled */ ',
            original, flags=re.IGNORECASE | re.DOTALL
        )

        # If that didn't match, try targeting the alert/notification line directly
        if new_content == original:
            new_content = re.sub(
                r'([^\n]*(?:openAlertDialog|setNotification|showErrorDialog|alert)\s*\([^)]*(?:already exists|A contact with)[^)]*\)[^;]*;)',
                r'/* duplicate email check disabled */',
                original, flags=re.IGNORECASE | re.DOTALL
            )

        # Broader fallback: find the return/throw statement after the "already exists" check
        if new_content == original:
            # Find the line with "already exists" and disable the surrounding block
            new_lines = []
            skip_depth = 0
            i = 0
            while i < len(lines):
                line = lines[i]
                if re.search(r"already exists|A contact with|Please choose a different email",
                             line, re.IGNORECASE):
                    # Comment out this line and nearby notification/return lines
                    new_lines.append("// duplicate check disabled: " + line)
                    # Look ahead and comment out any alert/return/throw on next few lines
                    j = i + 1
                    while j < min(i + 6, len(lines)):
                        next_line = lines[j]
                        if re.search(r"alert|return|throw|setNotification|openAlert|showError",
                                     next_line, re.IGNORECASE):
                            new_lines.append("// duplicate check disabled: " + next_line)
                            j += 1
                        else:
                            break
                    i = j
                    continue
                new_lines.append(line)
                i += 1
            new_content = "\n".join(new_lines)

        if new_content == original:
            print(f"  WARNING: Could not automatically patch {wr['name']}.")
            print(f"  Manual edit required — see relevant code above.")
            continue

        # Save the patched content back
        crm_patch("webresourceset", wr["webresourceid"], {
            "content": encode_content(new_content),
        })
        patched.append(wr["webresourceid"])
        print(f"  Patched and saved: {wr['name']}")

    # 2. Publish all patched web resources
    if patched:
        print(f"\nPublishing {len(patched)} patched web resource(s)...")
        param_xml = "".join(f"<webresource>{wid}</webresource>" for wid in patched)
        crm_action("PublishXml", {
            "ParameterXml": f"<importexportxml><webresources>{param_xml}</webresources></importexportxml>"
        })
        print("Published. Users should refresh their browser — no sign-out needed.")
        print("\nDone. The duplicate email block has been removed from the Contact form.")
    elif not patched:
        print("\nNo JavaScript web resources found with the duplicate check pattern.")
        print("The block may be in a form event handler in the form XML itself.")
        print("Run: python find_contact_form_scripts.py  for full form analysis.")

    # 3. Re-disable any duplicate detection rules that crept back
    rules = crm_get("duplicaterules", {
        "$select": "duplicateruleid,name",
        "$filter": "baseentityname eq 'contact' and statecode eq 0",
    }).get("value", [])
    if rules:
        print(f"\nAlso disabling {len(rules)} re-enabled duplicate rule(s):")
        for rule in rules:
            crm_patch("duplicaterules", rule["duplicateruleid"],
                      {"statecode": 1, "statuscode": 2})
            print(f"  → {rule['name']}")

except Exception:
    traceback.print_exc()
