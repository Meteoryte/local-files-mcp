# Local Files MCP

A local filesystem MCP server for ChatGPT Developer Mode.

Local Files MCP lets you expose only the folders you choose to ChatGPT through an MCP endpoint. It includes a desktop GUI for setup, folder allowlists, server/tunnel settings, pairing-code auth, and local write approvals.

## What it does

- Runs a local MCP-compatible HTTP endpoint at `http://127.0.0.1:8765/mcp`
- Lets ChatGPT list, search, and read files inside configured local roots
- Supports Safe Inbox, Project Folder, Home Read-Only, and Full Access profiles
- Uses deny rules, extension filters, hidden/binary file blocking, file size limits, and secret redaction
- Provides a local write workflow: prepare write → approve in GUI → commit operation
- Optionally exposes Dangerous Mode direct writes for trusted private development machines
- Generates ChatGPT Developer Mode connector settings
- Can detect and launch ngrok from the GUI
- Includes optional shadcn CLI wrapper tools for allowlisted project folders

## Safety first

Start with **Safe Inbox** or a single **Project Folder**. Full Access and Dangerous Mode are intentionally powerful and should only be used on a private machine you control.

Files read through this server are untrusted local data. Do not ask a model to blindly follow instructions from arbitrary files.

## Requirements

- Python 3.10 or newer
- `pip` and `venv`
- `tkinter` for the GUI
- A public HTTPS tunnel for ChatGPT Developer Mode, such as ngrok or Cloudflare Tunnel
- Optional: Node.js/npm for shadcn tools

Python package dependencies are listed in [`requirements.txt`](requirements.txt) and [`pyproject.toml`](pyproject.toml):

- `mcp>=1.9.0`
- `uvicorn>=0.29.0`
- `starlette>=0.37.2`
- `pydantic>=2.7.0`

See [`REQUIREMENTS.md`](REQUIREMENTS.md) for operating-system details.

## Quick install

### macOS

Double-click:

```text
INSTALL.command
```

If macOS blocks it, right-click the file and choose **Open**.

### Linux

```bash
chmod +x install.sh
./install.sh
```

### Windows

Double-click:

```text
INSTALL.bat
```

or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALL.ps1
```

The installer creates `.venv`, installs the package in editable mode, creates launch shortcuts, and opens the GUI.

## Manual install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
local-files-mcp setup
local-files-mcp start
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
local-files-mcp setup
local-files-mcp start
```

## Using the GUI

After installation, open the GUI:

```bash
local-files-mcp gui
```

or:

```bash
python start_gui.py
```

Recommended flow:

1. Choose **Safe Inbox** or **Project Folder** on the Quick Setup tab.
2. Click **Start MCP Server**.
3. Start or detect an HTTPS tunnel.
4. Click **Copy ChatGPT Settings**.
5. Paste the settings into ChatGPT Developer Mode.

## ChatGPT Developer Mode settings

The MCP URL must be public HTTPS and end with `/mcp`.

Example:

```text
Name: Local Files MCP
Description: Safely read/search selected local folders; optionally prepare locally approved writes.
MCP URL / Connector URL: https://abc123.ngrok-free.app/mcp
Authentication: No authentication
```

In ChatGPT:

```text
Settings → Apps & Connectors → Advanced settings → Developer mode: ON
Settings → Apps & Connectors → Create
```

Paste the values from the GUI.

See [`docs/CHATGPT_DEVELOPER_MODE.md`](docs/CHATGPT_DEVELOPER_MODE.md) for the complete setup.

## CLI examples

```bash
local-files-mcp setup --preset safe
local-files-mcp setup --preset project --path ~/Projects/my-app --write
local-files-mcp set-public-url https://abc123.ngrok-free.app
local-files-mcp settings
local-files-mcp start
```

Full access requires an explicit dangerous flag:

```bash
local-files-mcp full-access --i-understand-this-is-dangerous
```

## Included MCP tools

Tool exposure depends on the configured safety profile.

Common tools:

- `get_mcp_app_settings`
- `list_roots`
- `list_directory`
- `search_files`
- `read_file`
- `prepare_write`
- `commit_operation`

Dangerous Mode only:

- `write_file`

Optional project tools:

- `shadcn_info`
- `shadcn_search`
- `shadcn_view`
- `shadcn_add`
- `shadcn_init`

## Documentation

- [`INSTALL.md`](INSTALL.md): full installation guide
- [`REQUIREMENTS.md`](REQUIREMENTS.md): platform requirements and dependencies
- [`SECURITY.md`](SECURITY.md): safety model and risk guidance
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md): config files, profiles, roots, and env vars
- [`docs/CHATGPT_DEVELOPER_MODE.md`](docs/CHATGPT_DEVELOPER_MODE.md): ChatGPT connector setup
- [`docs/TUNNELS.md`](docs/TUNNELS.md): ngrok and HTTPS tunnel setup
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md): common fixes

## License

No license has been selected in this repository yet. Add a license before publishing or accepting external contributions.
