#!/usr/bin/env python3
# ============================================================
# run.py — Start Here
# ============================================================
# This is the only file you need to run.
# Open your terminal, navigate to this folder, and type:
#
#   python run.py
#
# Then type your request in plain English.
# ============================================================

import sys
from config.crm_connection import test_connection
from agent import run_agent

# ── Pretty banner ────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════════╗
║          TYR Sport — Microsoft CRM Agent                 ║
║                  Powered by Claude                       ║
╠══════════════════════════════════════════════════════════╣
║  Type your request in plain English.                     ║
║  Type 'help' to see example requests.                    ║
║  Type 'quit' or 'exit' to stop.                          ║
║  Type 'dry run: [your request]' to preview without       ║
║  making any changes.                                     ║
╚══════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
─────────────────────────────────────────────────────────────
EXAMPLE REQUESTS — just copy and paste or type something similar
─────────────────────────────────────────────────────────────

CONTACT CLEANUP:
  • "Give me a summary of contact data quality"
  • "Find all contacts missing an email address"
  • "Find all contacts missing a phone number"
  • "Find duplicate contacts"
  • "Search for contacts named Smith"
  • "Show me details for contact ID abc-123"

WORKFLOW MONITORING:
  • "Check the health of all our workflows"
  • "List all active workflows"
  • "Show me recent workflow run history"
  • "Are any workflows failing?"

VIEWS & DASHBOARDS:
  • "List all contact views"
  • "Create a view showing contacts missing email"
  • "List all dashboards"
  • "Create a data quality dashboard"
  • "Show me a summary of all views"

DRY RUN (preview without making changes):
  • "dry run: fix all contacts missing email"
  • "dry run: create a contacts by region dashboard"
─────────────────────────────────────────────────────────────
"""


def check_setup() -> bool:
    """
    Check that the .env file is filled in correctly before starting.
    Returns True if everything is set up, False if there are issues.
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    missing = []
    placeholders = []

    required = {
        "ANTHROPIC_API_KEY": "sk-ant-YOUR-KEY-HERE",
        "DYNAMICS_URL":      "https://YOUR-COMPANY.crm.dynamics.com",
        "AZURE_TENANT_ID":   "YOUR-TENANT-ID-HERE",
        "AZURE_CLIENT_ID":   "YOUR-CLIENT-ID-HERE",
        "AZURE_CLIENT_SECRET": "YOUR-CLIENT-SECRET-HERE",
    }

    for key, placeholder in required.items():
        value = os.getenv(key, "")
        if not value:
            missing.append(key)
        elif value == placeholder:
            placeholders.append(key)

    if missing or placeholders:
        print("\n⚠  SETUP REQUIRED")
        print("─" * 50)
        if missing:
            print(f"Missing from .env file: {', '.join(missing)}")
        if placeholders:
            print(f"Still has placeholder values: {', '.join(placeholders)}")
        print("\nPlease open the .env file and fill in your credentials.")
        print("See SETUP_GUIDE.md for step-by-step instructions.\n")
        return False

    return True


def test_crm_connection() -> bool:
    """Test the CRM connection and tell the user the result."""
    print("\nTesting connection to Microsoft Dynamics 365...")
    result = test_connection()

    if result["connected"]:
        print(f"✓ Connected successfully!")
        return True
    else:
        print(f"✗ Could not connect to CRM")
        print(f"  Error: {result['message']}")
        print(f"\n  Check your credentials in .env and re-read SETUP_GUIDE.md")
        return False


def main():
    print(BANNER)

    # Step 1: Check that credentials are filled in
    if not check_setup():
        print("Please complete setup before running the agent.")
        print("Open SETUP_GUIDE.md for instructions.\n")
        sys.exit(1)

    # Step 2: Test the CRM connection
    if not test_crm_connection():
        sys.exit(1)

    print("\n✓ Ready! Enter your request below.\n")

    # Conversation history — carries context across turns in this session
    conversation_history = []

    # Step 3: Interactive loop — keep asking for requests
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("\nGoodbye!")
            break

        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        if user_input.lower() in ("new", "new chat", "reset", "clear"):
            conversation_history = []
            print("\n  [Conversation history cleared — starting fresh]\n")
            continue

        # Check for dry run prefix
        dry_run = False
        request = user_input

        if user_input.lower().startswith("dry run:"):
            dry_run = True
            request = user_input[8:].strip()
            print("\n  [DRY RUN MODE — no changes will be made]\n")

        # Run the agent, passing and receiving conversation history
        try:
            response, conversation_history = run_agent(
                request, dry_run=dry_run, session_messages=conversation_history
            )
            print(f"\n{'═' * 60}")
            print(f"Agent:\n{response}")
            print(f"{'═' * 60}\n")

        except Exception as e:
            print(f"\n✗ Error: {e}")
            print("  Check the logs/ folder for details.\n")


if __name__ == "__main__":
    main()
