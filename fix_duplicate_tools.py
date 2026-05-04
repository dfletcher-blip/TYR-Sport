"""
Run once to remove duplicate tool definitions from agent.py.
Usage: python fix_duplicate_tools.py
"""
import re

with open("agent.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the TOOL_DEFINITIONS list boundaries
start = content.index("TOOL_DEFINITIONS = [")
end = content.index("\n]\n", start) + 3
header = content[:start + len("TOOL_DEFINITIONS = [\n")]
footer = content[end - 1:]

block = content[start + len("TOOL_DEFINITIONS = [\n"):end - 2]

# Split into individual tool definition blocks by finding each { "name": "..." entry
tool_blocks = re.split(r'\n(?=\s*\{)', block)

seen_names = set()
kept = []
removed = []

for tb in tool_blocks:
    m = re.search(r'"name":\s*"([^"]+)"', tb)
    if not m:
        kept.append(tb)
        continue
    name = m.group(1)
    if name in seen_names:
        removed.append(name)
    else:
        seen_names.add(name)
        kept.append(tb)

new_content = header + "\n".join(kept) + footer

with open("agent.py", "w", encoding="utf-8") as f:
    f.write(new_content)

if removed:
    print(f"Removed {len(removed)} duplicate tool(s): {', '.join(removed)}")
else:
    print("No duplicates found.")
print("Done — run python run.py to start the agent.")
