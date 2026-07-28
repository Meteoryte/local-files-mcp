#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"

echo "Local Files MCP Installer"
echo "========================="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install Python 3.10+ and run this again."
  exit 1
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

cat > start-gui.sh <<'EOF'
#!/usr/bin/env sh
cd "$(dirname "$0")"
. .venv/bin/activate
python -m local_files_mcp.admin_gui
EOF
chmod +x start-gui.sh

cat > start-server.sh <<'EOF'
#!/usr/bin/env sh
cd "$(dirname "$0")"
. .venv/bin/activate
local-files-mcp start
EOF
chmod +x start-server.sh

echo "Install complete. Opening the GUI Control Panel..."
python -m local_files_mcp.admin_gui
