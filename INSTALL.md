# Installation guide

Read [`REQUIREMENTS.md`](REQUIREMENTS.md) first if you are not sure whether your
machine has Python 3.10+ and tkinter.

## 1. Get the code

```bash
git clone https://github.com/Meteoryte/local-files-mcp.git
cd local-files-mcp
```

Or download the ZIP from the GitHub **Code** button and extract it.

## 2. Run the installer for your OS

### Windows

Double-click:

```text
INSTALL.bat
```

Or from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALL.ps1
```

### macOS

Double-click:

```text
INSTALL.command
```

If macOS blocks it, right-click the file and choose **Open**. If it is not
executable, run `chmod +x INSTALL.command` first.

### Linux

```bash
chmod +x install.sh
./install.sh
```

## What the installer does

1. Creates a local virtual environment at `.venv/`
2. Upgrades `pip`
3. Installs this package in editable mode (`pip install -e .`)
4. Writes launcher shortcuts next to the installer
5. Opens the GUI Control Panel

The launchers it creates:

| OS | GUI launcher | Server launcher |
|---|---|---|
| Windows | `Start Local Files MCP GUI.bat` | `Start Local Files MCP Server.bat` |
| macOS | `Start Local Files MCP GUI.command` | `Start Local Files MCP Server.command` |
| Linux | `start-gui.sh` | `start-server.sh` |

These are generated locally and are intentionally not tracked in git.

## Manual install

If you would rather not use the installer scripts:

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

`run.sh` and `run.ps1` are one-shot convenience wrappers around exactly that
sequence.

## 3. First-run setup

Open the GUI:

```bash
local-files-mcp gui
```

or:

```bash
python start_gui.py
```

Then:

1. On the **Quick Setup** tab, choose **Safe Inbox** or **Project Folder**.
   Start narrow. You can widen scope later.
2. Click **Start MCP Server**.
3. Go to **Server + ChatGPT** and click **Start Tunnel**.
4. Click **Copy ChatGPT Settings**.
5. Follow [`docs/CHATGPT_DEVELOPER_MODE.md`](docs/CHATGPT_DEVELOPER_MODE.md) to
   paste them into ChatGPT.

CLI equivalent, if you are skipping the GUI:

```bash
local-files-mcp setup --preset safe
local-files-mcp start
```

## Upgrading

```bash
git pull
source .venv/bin/activate          # .\.venv\Scripts\Activate.ps1 on Windows
python -m pip install -e .
```

Your configuration in `~/.local-files-mcp/` is preserved across upgrades.

## Uninstalling

1. Delete the cloned folder (this removes `.venv` and the launchers).
2. Delete `~/.local-files-mcp/` to remove config, audit log, and any pending
   write operations.
3. Remove the connector from ChatGPT's **Apps & Connectors** settings.

## Trouble?

See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
