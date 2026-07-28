# Connecting to ChatGPT Developer Mode

## Before you start

You need three things working:

1. The MCP server running locally (GUI → **Start MCP Server**, or `local-files-mcp start`)
2. A public HTTPS tunnel pointing at port `8765` — see [`TUNNELS.md`](TUNNELS.md)
3. At least one configured root, or the server has nothing to expose

## 1. Turn on Developer Mode in ChatGPT

```text
Settings → Apps & Connectors → Advanced settings → Developer mode: ON
```

## 2. Create the connector

```text
Settings → Apps & Connectors → Create
```

Fill in the fields. The GUI's **Copy ChatGPT Settings** button puts exactly
these on your clipboard:

```text
Name: Local Files MCP
Description: Local document access for folders you explicitly configure. Search/read files; writes require local approval.
MCP URL / Connector URL: https://YOUR-PUBLIC-TUNNEL.example/mcp
Authentication: No authentication
```

## The URL rules

This is where most setups fail. The URL you paste into ChatGPT must:

- be **public HTTPS** — not `http://`, not `localhost`, not `127.0.0.1`, not a
  private LAN address like `192.168.x.x`
- end with exactly **one** `/mcp`

Correct:

```text
https://abc123.ngrok-free.app/mcp
```

Wrong:

```text
http://127.0.0.1:8765/mcp
http://localhost:8765/mcp
https://abc123.ngrok-free.app/mcp/mcp
https://192.168.1.10:8765/mcp
https://abc123.ngrok-free.app
```

Note the asymmetry: the GUI field named **Public HTTPS URL** wants the *base*
URL with no path, because the GUI appends `/mcp` for you. ChatGPT wants the
*full* URL including `/mcp`.

```text
GUI field:     https://abc123.ngrok-free.app
ChatGPT field: https://abc123.ngrok-free.app/mcp
```

Click **Fix/Validate URL** in the GUI before copying if you are unsure, or run:

```bash
local-files-mcp validate-url https://abc123.ngrok-free.app
```

## 3. Authentication mode

### No authentication (easiest)

Best for first-time setup and local testing. Anyone who learns your tunnel URL
can reach the server while the tunnel is open, so keep the tunnel short-lived
and the root scope narrow.

```bash
local-files-mcp set-auth noauth
```

### Pairing-code OAuth

Set the connector's Authentication to **OAuth** in ChatGPT, then:

```bash
local-files-mcp set-auth oauth
local-files-mcp pair
```

`pair` prints a short pairing code. Enter it when ChatGPT prompts during the
authorization step. Codes expire — the default TTL is 3600 seconds.

To revoke every issued token:

```bash
local-files-mcp logout
```

This pairing flow is development-grade, not a production identity system. See
[`../SECURITY.md`](../SECURITY.md).

## 4. Verify the connection

Open your tunnel's `/tools` URL in a browser:

```text
https://abc123.ngrok-free.app/tools
```

That endpoint lists the tools the server is currently advertising. If the list
is there, the server and tunnel are healthy and any remaining problem is on the
ChatGPT side.

## After changing tools or settings

ChatGPT caches a connector's action list. Whenever you change the profile,
toggle tools, or enable Dangerous Mode:

1. Restart the MCP server
2. In ChatGPT: **Settings → Apps & Connectors → Local Files MCP → Refresh actions**

If refreshing does not pick up the change, delete the connector and recreate it.

## Tunnel URLs change

A free ngrok tunnel gets a new URL every restart. When that happens the old
connector URL is dead. Update it:

```bash
local-files-mcp detect-tunnel --save
```

then paste the new `/mcp` URL into the ChatGPT connector. A reserved ngrok
domain or a named Cloudflare tunnel avoids this — see [`TUNNELS.md`](TUNNELS.md).
