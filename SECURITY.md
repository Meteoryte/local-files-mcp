# Security model

This app can expose your local files to ChatGPT through MCP. Use the smallest folder scope that solves the job.

## Recommended modes

- `safe`: only `~/ChatGPT-MCP-Inbox`, read-only.
- `project`: one project folder, read-only by default.
- `home_read`: home folder with deny rules.
- `full_access`: root/disk, write tools enabled. Dangerous.

## Full access warning

Full access intentionally allows broad reading and writing. It is useful for a private dev box you control, but it can expose secrets or let the model prepare file changes anywhere. This package still keeps write commit local-approval based, but reads are broad in full access mode.

## Prompt injection

Files can contain malicious instructions. The server labels file content as untrusted. Do not ask the model to blindly follow instructions from arbitrary files.

## OAuth/pairing

The pairing-code OAuth mode is for local development, not production identity. In production, use hardened OAuth 2.1 with PKCE and proper token lifecycle management.
