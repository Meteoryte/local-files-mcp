#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Local Files MCP Installer"
echo "========================="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install Python 3.10+ and run this again."
  read -r -p "Press Enter to exit..."
  exit 1
fi

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

cat > "Start Local Files MCP GUI.command" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
python -m local_files_mcp.admin_gui
EOF
chmod +x "Start Local Files MCP GUI.command"

cat > "Start Local Files MCP Server.command" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
source .venv/bin/activate
local-files-mcp start
EOF
chmod +x "Start Local Files MCP Server.command"

echo
echo "Install complete. Opening the GUI Control Panel..."
echo
python -m local_files_mcp.admin_gui
