# Configuration

## Where things live

Nothing is stored in the repository. All runtime state goes to:

```text
~/.local-files-mcp/
├── config.json      the live configuration
├── session.json     issued tokens and pairing state
├── audit.jsonl      append-only access log
└── pending/         write operations awaiting approval
```

Move that directory by setting `LOCAL_FILES_MCP_HOME`:

```bash
export LOCAL_FILES_MCP_HOME=~/my-mcp-config
```

`local-files-mcp setup` creates `config.json` on first run. You should not need
to edit it by hand — the GUI and CLI cover everything — but it is plain JSON if
you want to.

Inspect the current state:

```bash
local-files-mcp show        # full config
local-files-mcp settings    # the ChatGPT connector settings block
```

## Profiles

A profile is a preset bundle of roots and safety flags.

| Profile | Scope | Access |
|---|---|---|
| `safe` | `~/ChatGPT-MCP-Inbox` only | read-only |
| `project` | one folder you pick | read-only unless `--write` |
| `home` | your home directory, with deny rules | read-only |
| `full` | the whole disk | read + write. **Dangerous** |

```bash
local-files-mcp setup --preset safe
local-files-mcp setup --preset project --path ~/Projects/my-app --write
local-files-mcp setup --preset home
```

Full access will not apply without an explicit acknowledgement flag:

```bash
local-files-mcp full-access --i-understand-this-is-dangerous
```

## Roots

A root is one allowlisted folder plus the rules that apply inside it.

```bash
local-files-mcp add-root ~/Projects/my-app --id my-app --access read
local-files-mcp add-root ~/Notes --id notes --access write
local-files-mcp add-root ~/Scratch --id scratch --access write --full
```

`--access` accepts `none`, `metadata`, `search`, `read`, or `write`, in
increasing order of capability. `--full` removes the extension allowlist and
deny globs **for that root only**.

Each root carries:

| Field | Meaning |
|---|---|
| `id` | short name used in tool output |
| `path` | absolute folder path |
| `access` | the level above |
| `recursive` | whether subfolders are included |
| `allow_extensions` | file types readable in this root |
| `deny_globs` | patterns excluded even when otherwise allowed |
| `write_globs` | patterns writable when `access` is `write` |

The default deny globs block the things you almost never want exposed:

```text
**/.env*
**/secrets/**
**/.git/**
**/node_modules/**
```

Keep them. They are the reason a stray `.env` inside an allowlisted project does
not get read out.

## Safety settings

Defaults, all of which err toward caution:

| Setting | Default | Effect |
|---|---|---|
| `max_file_bytes` | `1048576` | Refuse to read files larger than 1 MB |
| `max_search_results` | `100` | Cap results per search |
| `max_scan_files` | `5000` | Cap files touched per scan |
| `allow_symlinks` | `false` | Do not follow links out of a root |
| `block_hidden_files` | `true` | Skip dotfiles |
| `block_binary_files` | `true` | Skip non-text files |
| `redact_secrets` | `true` | Mask key-shaped strings in returned content |
| `label_file_content_untrusted` | `true` | Tag file content as untrusted input |
| `require_local_approval_for_writes` | `true` | Writes need approval in the GUI |
| `allow_destructive_tools` | `false` | Keep delete/move off |

`redact_secrets` masks private keys, AWS access keys, GitHub tokens, bearer
tokens, JWTs, database URLs with inline credentials, and generic
`api_key = ...` assignments before content leaves the machine. It is a safety
net, not a guarantee — do not rely on it to protect a folder you should not have
allowlisted in the first place.

## Tools

Each tool can be toggled independently. Defaults:

| Tool | Default |
|---|---|
| `get_mcp_app_settings`, `list_roots`, `list_directory` | on |
| `search_files`, `read_file`, `search`, `fetch` | on |
| `prepare_write`, `commit_operation` | on |
| `write_file`, `delete_file`, `move_file`, `shell` | **off** |

Tool exposure is also clamped by the active profile — a read-only root will not
serve writes even if the tool is enabled.

## The write flow

By default, a model cannot change a file on its own:

```text
prepare_write  →  operation appears in the GUI  →  you approve  →  commit_operation
```

From the CLI instead of the GUI:

```bash
local-files-mcp pending
local-files-mcp approve <operation_id>
local-files-mcp reject <operation_id>
```

## Dangerous Mode

Dangerous Mode removes the approval step. Every flag defaults to off:

| Flag | Default | Effect |
|---|---|---|
| `enabled` | `false` | Master switch |
| `auto_approve_prepared_writes` | `false` | Skip the GUI approval gate |
| `expose_direct_write_file` | `false` | Advertise the `write_file` tool |
| `allow_create` | `true` | Permit new files (once enabled) |
| `allow_overwrite` | `true` | Permit overwriting (once enabled) |
| `allow_delete` | `false` | Permit deletion |
| `allow_move` | `false` | Permit moves |
| `allow_shell` | `false` | Permit shell execution |
| `warning_acknowledged` | `false` | Set when you confirm the warning |

Turn this on only on a private machine you control, and pair it with the
narrowest possible root. A model that can write without approval, inside a wide
root, can do real damage from a single bad instruction in a file it read.

## Environment variables

These override `config.json` at runtime. See [`../.env.example`](../.env.example).

| Variable | Default |
|---|---|
| `LOCAL_FILES_MCP_HOME` | `~/.local-files-mcp` |
| `LOCAL_FILES_MCP_HOST` | `127.0.0.1` |
| `LOCAL_FILES_MCP_PORT` | `8765` |
| `LOCAL_FILES_MCP_PUBLIC_URL` | empty |
| `LOCAL_FILES_MCP_AUTH_MODE` | `noauth` |
| `LOCAL_FILES_MCP_PAIRING_CODE_TTL_SECONDS` | `3600` |
| `LOCAL_FILES_MCP_AUTHORIZATION_CODE_TTL_SECONDS` | `600` |
| `LOCAL_FILES_MCP_ACCESS_TOKEN_TTL_SECONDS` | `2592000` |
| `LOCAL_FILES_MCP_REFRESH_TOKEN_TTL_SECONDS` | `31536000` |
| `LOCAL_FILES_MCP_SLIDING_ACCESS_TOKENS` | `true` |

Leaving `LOCAL_FILES_MCP_HOST` at `127.0.0.1` matters. Binding to `0.0.0.0`
exposes the server to your whole network with no tunnel in front of it.

## Audit log

Every read, search, and denial is appended to `~/.local-files-mcp/audit.jsonl`.

```json
{"enabled": true, "log_reads": true, "log_searches": true, "log_denials": true, "hash_paths": false}
```

Set `hash_paths` to `true` to record hashed paths instead of literal ones if the
log itself needs to be shareable.

## Example configs

[`../examples/settings.safe.example.json`](../examples/settings.safe.example.json)
and
[`../examples/settings.full-access.example.json`](../examples/settings.full-access.example.json)
show both ends of the range. Replace `YOUR-TUNNEL` and the placeholder paths
with your own before use.
