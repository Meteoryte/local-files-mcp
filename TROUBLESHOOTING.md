# Troubleshooting

## Install

### "Python 3 is required" / installer exits immediately

You have no Python 3.10+ on PATH. Check with `python3 --version` (macOS/Linux)
or `py -3 --version` (Windows). See [`REQUIREMENTS.md`](REQUIREMENTS.md).

### The GUI never opens after install

Almost always missing tkinter. Test it:

```bash
python3 -c "import tkinter"
```

`ModuleNotFoundError` means you need the platform package — `python3-tk` on
Debian/Ubuntu, `python3-tkinter` on Fedora, `brew install python-tk` on
Homebrew Python. Full list in [`REQUIREMENTS.md`](REQUIREMENTS.md).

Everything works without the GUI; use the CLI instead:

```bash
local-files-mcp setup --preset safe
local-files-mcp start
```

### macOS refuses to open INSTALL.command

Gatekeeper. Right-click the file → **Open** → confirm. If it is not executable:

```bash
chmod +x INSTALL.command
```

### PowerShell blocks INSTALL.ps1

Use `INSTALL.bat`, which already passes `-ExecutionPolicy Bypass`. Or run it
directly:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALL.ps1
```

### `local-files-mcp: command not found`

The virtual environment is not active:

```bash
source .venv/bin/activate          # macOS / Linux
.\.venv\Scripts\Activate.ps1       # Windows PowerShell
```

Or use the generated launcher, or `python -m local_files_mcp.cli`.

## Server

### Port 8765 already in use

Something else has the port, often an earlier server that did not exit.

```bash
local-files-mcp start --port 8790
```

Then update the tunnel to match the new port.

### Server starts but exposes nothing

No roots are configured. `local-files-mcp show` will list `"roots": []`. Run a
preset or add a root:

```bash
local-files-mcp setup --preset safe
local-files-mcp add-root ~/Projects/my-app --id my-app --access read
```

### A file exists but the server will not read it

Work through the filters in order:

1. Is it inside a configured root?
2. Does its extension appear in that root's `allow_extensions`?
3. Does it match a deny glob — `.env*`, `secrets/**`, `.git/**`, `node_modules/**`?
4. Is it hidden, and is `block_hidden_files` still `true`?
5. Is it binary, and is `block_binary_files` still `true`?
6. Is it over `max_file_bytes` (1 MB by default)?

`~/.local-files-mcp/audit.jsonl` records denials with the reason, which is
usually faster than guessing.

## ChatGPT connection

### "Unsafe URL"

The URL must be public HTTPS ending in exactly one `/mcp`. Not `localhost`, not
`127.0.0.1`, not a private LAN IP, not `http://`, not `/mcp/mcp`, not the bare
domain.

```text
https://abc123.ngrok-free.app/mcp
```

Remember the two fields differ: the GUI's **Public HTTPS URL** takes the base
URL, ChatGPT takes the full URL with `/mcp`. Validate first:

```bash
local-files-mcp validate-url https://abc123.ngrok-free.app
```

If a hostname is rejected no matter what, the tunnel domain itself may be
flagged. Try a different ngrok domain or Cloudflare Tunnel.

### Connector added, but no tools appear

Open your tunnel's `/tools` URL in a browser. If the tool list renders, the
server and tunnel are fine and ChatGPT is holding a stale action list:

```text
Settings → Apps & Connectors → Local Files MCP → Refresh actions
```

Restart the server first, since the action list is read at connect time. If
refreshing still shows nothing, delete the connector and recreate it.

### It worked yesterday, now it cannot connect

A free ngrok tunnel gets a new URL on every restart, so the connector points at
a dead hostname.

```bash
local-files-mcp detect-tunnel --save
```

Paste the new `/mcp` URL into the connector. A reserved ngrok domain or named
Cloudflare tunnel prevents the recurrence — see
[`docs/TUNNELS.md`](docs/TUNNELS.md).

### `400 Bad Request` — `Invalid Content-Type header`

### `421 Misdirected Request` — `Invalid Host header`

Both are fixed in current versions, which normalize `Content-Type`, `Accept`,
and tunnel `Host` headers for `/mcp`. If you are seeing them, you are on an old
copy — pull and reinstall.

## Auth

### Pairing code rejected

Codes are single-use and expire (default 3600 seconds). Generate a fresh one:

```bash
local-files-mcp pair
```

Confirm you are actually in OAuth mode — `local-files-mcp set-auth oauth` — and
that the ChatGPT connector's Authentication field agrees. A mismatch between the
two sides fails in confusing ways.

### Revoking access

```bash
local-files-mcp logout
```

Invalidates every issued token. Reconnecting requires a new pairing.

## Writes

### Writes silently do nothing

Expected behavior: `prepare_write` only queues an operation. Nothing lands until
it is approved and committed.

```bash
local-files-mcp pending
local-files-mcp approve <operation_id>
```

Or approve it on the GUI's pending-operations tab.

### `write_file` is not available

It is off by default. It only appears when Dangerous Mode is enabled with
`expose_direct_write_file`. Consider whether you actually want to remove the
approval gate — see [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) and
[`SECURITY.md`](SECURITY.md).

### Write refused inside a writable root

Check the root's `write_globs`. An empty list means no path is writable even
when `access` is `write`. `**/*` makes the whole root writable.

## Starting clean

To reset everything without reinstalling:

```bash
rm -rf ~/.local-files-mcp
local-files-mcp setup --preset safe
```

This clears config, issued tokens, pending operations, and the audit log. Your
files are untouched.
