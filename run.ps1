python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -e .
local-files-mcp setup
local-files-mcp start
