"""
Quick test: try creating a personal dashboard (userform) and report exactly what happens.
Run with: python debug_userform.py
"""
import os, json
from dotenv import load_dotenv
load_dotenv()

from config.crm_connection import crm_get, crm_post

# Step 1: Look up the user
email = os.getenv("DYNAMICS_USER_EMAIL", "")
print(f"Looking up user: {email}")

result = crm_get("systemusers", {
    "$filter": f"internalemailaddress eq '{email}' or domainname eq '{email}'",
    "$select": "systemuserid,fullname,internalemailaddress,domainname",
    "$top": 3,
})
users = result.get("value", [])
print(f"Found {len(users)} user(s):")
for u in users:
    print(f"  - {u.get('fullname')} | {u.get('internalemailaddress')} | {u.get('domainname')} | ID: {u.get('systemuserid')}")

if not users:
    print("ERROR: User not found. Check DYNAMICS_USER_EMAIL in .env")
    exit(1)

user_id = users[0]["systemuserid"]

# Step 2: Try creating a simple userform
print("\nCreating test personal dashboard (userform)...")
form_xml = """<form>
  <tabs>
    <tab name="tab_0" id="{c58ee3c2-79ba-4bcc-8dd7-b6ef3b4b6456}" locklevel="0" showlabel="false" expanded="true">
      <labels><label description="Test Dashboard" languagecode="1033"/></labels>
      <columns>
        <column width="100%">
          <sections>
            <section name="section_0" showlabel="false" showbar="false" locklevel="0" id="{0e9dd3f4-98e0-4536-a3c9-56b5e38a8b4a}" layout="varwidth" columns="1">
              <labels><label description="Section" languagecode="1033"/></labels>
              <rows>
                <row>
                  <cell showlabel="false" locklevel="0">
                    <labels><label description="Test" languagecode="1033"/></labels>
                    <control id="control0" classid="{E7A81278-8635-4d9e-8D4D-59480B391C5B}" isrequired="false"/>
                  </cell>
                </row>
              </rows>
            </section>
          </sections>
        </column>
      </columns>
    </tab>
  </tabs>
</form>"""

data = {
    "name": "Agent Test Dashboard (delete me)",
    "description": "Test dashboard created by debug script",
    "type": 0,
    "formxml": form_xml,
    "objecttypecode": "none",
    "ownerid@odata.bind": f"/systemusers({user_id})",
}

try:
    result = crm_post("userforms", data)
    print(f"SUCCESS: {result}")
    print("\nCheck your CRM under My Dashboards — 'Agent Test Dashboard (delete me)' should appear.")
except Exception as e:
    print(f"FAILED: {e}")
