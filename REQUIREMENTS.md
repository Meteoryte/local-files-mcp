# Requirements

## All platforms

| Requirement | Notes |
|---|---|
| Python **3.10 or newer** | Enforced by `pyproject.toml` (`requires-python = ">=3.10"`) |
| `pip` and `venv` | The installers create a local `.venv` |
| `tkinter` | Required for the GUI Control Panel. Ships with most Python builds, but **not all** — see below |
| A public HTTPS tunnel | ChatGPT Developer Mode rejects `localhost`. See [`docs/TUNNELS.md`](docs/TUNNELS.md) |
| Node.js / npm | **Optional.** Only for the `shadcn_*` project tools |

Python dependencies are installed automatically:

```text
mcp>=1.9.0
uvicorn>=0.29.0
starlette>=0.37.2
pydantic>=2.7.0
```

## Check your Python

```bash
python3 --version     # macOS / Linux
py -3 --version       # Windows
```

If this reports anything below 3.10, install a newer Python before continuing.

## Check tkinter

The GUI will not start without it. Verify with:

```bash
python3 -c "import tkinter; print(tkinter.TkVersion)"
```

If that raises `ModuleNotFoundError`, install it:

### Windows

Re-run the official Python installer from python.org and make sure
**tcl/tk and IDLE** is checked in the optional features screen. The Microsoft
Store build of Python also includes tkinter.

### macOS

The python.org installer includes tkinter. If you installed Python via
Homebrew:

```bash
brew install python-tk
```

### Linux

tkinter is packaged separately on most distributions:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora / RHEL
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

You can still run the server without tkinter — use the CLI (`local-files-mcp setup`,
`local-files-mcp start`) instead of the GUI.

## Platform notes

### Windows

- `INSTALL.bat` calls `INSTALL.ps1` with `-ExecutionPolicy Bypass`, so you do not
  need to change your system execution policy.
- The installer prefers the `py` launcher and falls back to `python` on PATH.

### macOS

- Gatekeeper may block `INSTALL.command` on first run. Right-click the file and
  choose **Open**, then confirm.
- If the file is not executable: `chmod +x INSTALL.command`.

### Linux

- Make the installer executable first: `chmod +x install.sh`.
- The GUI needs a running display server (X11 or Wayland). On a headless box,
  use the CLI instead.

## Where runtime files go

Nothing is written into the repository. All state lives in:

```text
~/.local-files-mcp/
```

Override that location with the `LOCAL_FILES_MCP_HOME` environment variable.
See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
