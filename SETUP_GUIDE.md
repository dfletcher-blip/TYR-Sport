# Setup Guide — TYR Sport CRM Agent
# No coding experience needed. Follow each step in order.

---

## STEP 1 — Get Your Anthropic API Key

1. Go to https://console.anthropic.com
2. Sign in or create an account
3. Click "API Keys" in the left sidebar
4. Click "Create Key", give it a name like "TYR CRM Agent"
5. Copy the key (starts with sk-ant-)
6. Open the `.env` file and paste it after `ANTHROPIC_API_KEY=`

---

## STEP 2 — Register Your App in Microsoft Azure
(This gives Claude permission to talk to your CRM)

1. Go to https://portal.azure.com
2. Search for "App registrations" in the top search bar
3. Click "New registration"
4. Fill in:
   - Name: "TYR CRM Agent"
   - Supported account types: "Accounts in this organizational directory only"
   - Leave Redirect URI blank
5. Click "Register"

**After registering, you'll see a page with:**
- Application (client) ID → copy this → paste into `.env` as `AZURE_CLIENT_ID`
- Directory (tenant) ID → copy this → paste into `.env` as `AZURE_TENANT_ID`

---

## STEP 3 — Create a Client Secret

Still on your App Registration page:
1. Click "Certificates & secrets" in the left menu
2. Click "New client secret"
3. Description: "CRM Agent Secret"
4. Expiry: 24 months
5. Click "Add"
6. **IMPORTANT: Copy the VALUE immediately** (you can't see it again)
7. Paste it into `.env` as `AZURE_CLIENT_SECRET`

---

## STEP 4 — Give the App Permission to Access Dynamics 365

Still on your App Registration page:
1. Click "API permissions" in the left menu
2. Click "Add a permission"
3. Click "Dynamics CRM"
4. Check "user_impersonation"
5. Click "Add permissions"
6. Click "Grant admin consent for [your company]"
7. Click "Yes"

---

## STEP 5 — Add the App User to Dynamics 365

In Dynamics 365:
1. Go to Settings → Security → Users
2. Switch the view to "Application Users"
3. Click "New"
4. Set User type to "Application User"
5. Paste your Client ID in the "Application ID" field
6. Assign the "System Administrator" or "System Customizer" role
7. Click Save

---

## STEP 6 — Fill in Your Dynamics URL

Your Dynamics 365 URL looks like:
  https://yourcompany.crm.dynamics.com

Paste it into `.env` as `DYNAMICS_URL`

---

## STEP 7 — Install Required Packages

Open your terminal and run:

```
pip install anthropic msal requests python-dotenv
```

---

## STEP 8 — Run the Agent

```
python run.py
```

Then type your request in plain English. Examples:
- "Show me all contacts missing an email address"
- "Find duplicate contacts"
- "List all active workflows"
- "Give me a summary of data quality issues"
