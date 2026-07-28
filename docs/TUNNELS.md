# HTTPS tunnels

ChatGPT Developer Mode will only talk to a public HTTPS endpoint. The server
itself binds to `127.0.0.1:8765`, so you need a tunnel in front of it.

## ngrok, from inside the GUI

You do not need a separate terminal. Open the **Server + ChatGPT** tab:

1. Click **Start Server**
2. Click **Start Tunnel**
3. The GUI detects the public HTTPS URL automatically
4. Click **Copy ChatGPT Settings**

### If ngrok is not installed

The **ngrok Tunnel** section of the GUI handles it:

| Button | What it does |
|---|---|
| **Download ngrok** | Opens the ngrok download page |
| **Auto-Find** | Searches your PATH for `ngrok` |
| **Choose...** | Lets you point at the executable manually |
| **Auth token** + **Save Token to ngrok** | Runs `ngrok config add-authtoken` for you |

The app does not store your ngrok auth token. It passes the value to ngrok and
clears the field.

## ngrok, from a terminal

```bash
ngrok http 8765
```

Then let the app find the URL:

```bash
local-files-mcp detect-tunnel --save
```

or click **Detect ngrok Tunnel** in the GUI. Detection reads ngrok's local API,
so ngrok must already be running.

## Setting the URL by hand

```bash
local-files-mcp set-public-url https://abc123.ngrok-free.app
```

Pass the **base** URL with no path. The server appends `/mcp` when it generates
ChatGPT settings.

## Free tunnels change URL on restart

Every `ngrok http 8765` on a free plan produces a new hostname, which breaks the
connector you already configured in ChatGPT. Two ways around it:

- **Reserved ngrok domain** — a static domain tied to your account, so the URL
  survives restarts
- **Named Cloudflare Tunnel** — a persistent hostname on a domain you control

Treat whichever hostname you end up with as sensitive. It is a public door to a
server that reads your local files, so do not post it in issues, screenshots, or
commits.

## Cloudflare Tunnel

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

Copy the printed HTTPS URL and set it manually:

```bash
local-files-mcp set-public-url https://your-tunnel.trycloudflare.com
```

Auto-detection is ngrok-specific; Cloudflare URLs must be set by hand.

## Why tunnel headers used to break

Tunnels rewrite `Host`, and some clients send an unhelpful `Content-Type`. The
server normalizes all of this for `/mcp` requests:

- `Content-Type: application/octet-stream` is rewritten to `application/json`
- wildcard or missing `Accept` becomes `application/json, text/event-stream`
- the external tunnel `Host` header is rewritten to `127.0.0.1:8765` for the
  inner MCP SDK transport, so its DNS-rebinding protection stops rejecting the
  tunnel

OAuth, discovery, `/authorize`, `/token`, `/register`, and metadata endpoints
still see the real public URL, because those have to match what ChatGPT was
given.

If you are on an older copy and seeing `400 Bad Request` with
`Invalid Content-Type header` or `421 Misdirected Request` with
`Invalid Host header`, update — that is fixed.

## Checking a tunnel

Open in a browser:

```text
https://your-tunnel-url/tools
```

A tool list means the whole path from the public internet to your local server
is working.
