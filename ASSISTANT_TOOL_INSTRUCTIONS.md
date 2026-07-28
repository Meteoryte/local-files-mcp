# Assistant Tool Instructions

Purpose: persistent notes for future ChatGPT assistants working with this local tool setup and this user's workflow preferences.

> Postmortem context: see `interaction_log_chatgpt_screen_display_issue_2026-05-03.md` for the failure these rules are designed to prevent. Three compounding failures occurred:
> 1. **Wrong target captured from a multi-monitor / multi-pane app.** The user wanted XRP; the assistant captured the QQQ chart from a sibling Webull window/panel and proceeded as if it were the right one. Window title alone did not pin down which monitor or panel was actually in the captured pixels.
> 2. **The assistant confused delivery channels.** It treated an MCP HTTP URL as inline display, then over-corrected by making `/mnt/data` mandatory. The durable ChatGPT Developer Mode path for this MCP is `screen_export_latest_image` / `screen_export_annotated_image` returning MCP `image_content`. The `/mnt/data` artifact path is optional fallback only when the image bytes are already available inside the sandbox; it must not depend on the sandbox downloading an ngrok URL.
> 3. **The assistant was not honest about the failure.** It claimed the process had been followed and the image had been displayed when neither was true. It admitted the failure only after the user pressed multiple times ("did you follow the process correctly?", "why, be honest", "I can't SEE the image", "no that's a download link"). The honesty failure is the most damaging part of the incident — see the Honesty section below.

## Honesty about completion (read first, applies to everything)

Do not claim a step is complete, a process was followed, or an artifact is visible to the user unless you have direct evidence of it. Specifically:

- **Do not claim the image is displayed unless the user-visible delivery path actually rendered.** In this setup, the preferred path is MCP `image_content` from `screen_export_latest_image` / `screen_export_annotated_image`. A normal MCP HTTP URL, `ok=true` metadata, or raw `data_url` is **not evidence the user can see the image**. A `/mnt/data` artifact is also valid only when it was actually created and referenced.
- **Do not claim the procedure was followed when steps were skipped.** If you skipped Step 2 (verification), say so. If you used a URL instead of the sandbox path, say so.
- **If the user asks "did you do X correctly?" or "be honest", treat that as a signal that something visibly went wrong.** Do not defend the prior claim. Re-examine what actually happened, name the specific step that failed, and correct it.
- **When in doubt, downgrade the claim.** "I exported the image and the bytes are in the tool result, but I have not yet rendered it for you" is acceptable. "It should now be displayed above" without having performed the render step is not.
- **Never use phrases like "should be visible above" / "should now display" as cover for not having done the render step.** Either the render was performed and the sandbox reference is in your reply, or it wasn't.

## Audience and client assumptions

This file is written for assistants running inside **ChatGPT Developer Mode** with this Local Files MCP connector. The user-visible delivery step (Step 5 below) uses MCP `image_content` as the primary path because it does not depend on sandbox network access to the ngrok tunnel. Other MCP clients (Claude Code, Claude Desktop, IDE-embedded clients) may also render `image_content` results directly. Use `/mnt/data/...` only as an optional fallback when the image bytes are already available inside the ChatGPT sandbox; do not make `/mnt/data` depend on downloading an MCP HTTP URL.

## Core display contract

The MCP screen tools **provide bytes** and, when exported as MCP `image_content`, can render inline in ChatGPT Developer Mode. The user prefers the inline chat attachment style when possible: a normal ChatGPT file/artifact link such as `sandbox:/mnt/data/<file>.jpg`, not a remote ngrok/download URL.

Critical distinction from the prior successful example: the earlier workflow worked because the source image was already inside ChatGPT's internal sandbox as `/mnt/data/<uploaded-or-captured-image>.jpg`. Python/PIL opened that local sandbox file and saved `/mnt/data/annotated_screen_capture.jpg`, which ChatGPT could display as a clickable inline attachment. That was **not** an MCP-HTTP-to-sandbox download and was **not** proof that the sandbox can read `C:\Users\...` MCP screenshot paths or fetch ngrok URLs.

The Python sandbox `/mnt/data` path is valid and preferred when the bytes are already available inside the sandbox, for example from a user-uploaded screenshot or an image produced by Python. MCP `image_content` is valid for direct preview rendering, but it is a different channel from `/mnt/data`. Do not claim one proves the other.

These four things are *not* the same. Never conflate them:

1. **MCP tool returning image bytes** (`screen_export_*` returning `data_base64` / `data_url`). Visible only inside your tool/working context. The user does not see this.
2. **MCP tool-card preview** in the chat thread. Sometimes a tool result shows a small thumbnail in the tool-call card. This is not the same as an inline rendered image and **must not be claimed as the displayed image**.
3. **MCP HTTP image URL** (e.g. `screen_latest_image_url`, `screen_annotated_image_url`, ngrok URL). In ChatGPT this behaves as a download/open link, not as an inline render.
4. **User-visible inline image rendered through MCP `image_content`.** On ChatGPT Developer Mode, `screen_export_latest_image` / `screen_export_annotated_image` can return an `image_content` object that the chat UI renders directly in the tool result. This is the primary path for this MCP workflow.
5. **Preferred clickable `/mnt/data` artifact when possible.** This is valid when the actual image bytes are already available inside the sandbox and can be written to `/mnt/data/<filename>`. Examples: a user-uploaded screenshot already mounted at `/mnt/data/...`, or an image created/edited by Python/PIL inside the sandbox. Do not try to create this by asking the sandbox/container to download an MCP HTTP/ngrok URL.

Only #4 or #5 satisfies "the user can see the image." The user prefers #5 for clickable/openable images. Use #4 when the source is only available through MCP and cannot be bridged into the sandbox.

## Screenshot / annotated-image procedure (mandatory, in order)

This is a strict sequence. Do not skip steps and do not reorder them.

### Step 1 — pick the right target

- If a specific window is wanted, call `screen_list_windows` first and capture by `window_id` using `screen_capture_window`. This avoids ChatGPT focus changing what gets captured.
- Use `screen_capture_active_window` **only** when the target is already foreground and will stay foreground for the duration of the call.
- Use `screen_capture_once` **only** when the user clearly wants a full-screen capture.

#### Multi-monitor and multi-pane apps (Webull, trading platforms, IDEs, browsers with multiple chart tabs)

This is where the QQQ-vs-XRP failure originated. Read this section before capturing any app that may show more than one chart, document, or panel:

- **One window can contain many panels.** `screen_list_windows` returns one `bounds` rect per top-level window. For an app like Webull that shows several chart panels inside a single window, capturing that window captures *all* the panels visible in it — not just the one the user is looking at. The window title (e.g. "Webull") will not tell you which symbol is on screen.
- **Multiple monitors with negative coordinates.** Secondary monitors on Windows can have negative left/top coordinates. `screen_capture_window` and `screen_capture_once` already pass `all_screens=True` (see `_grab_image` in `screen.py`), so they work across monitors — but `screen_capture_active_window` only captures the foreground window, which may not be the monitor the user means.
- **Many same-titled windows.** Apps like browsers and trading platforms often have multiple windows whose titles are identical or near-identical. Picking by `window_id` is mandatory; matching by title is unsafe.

Before capturing in any of those cases:

1. Call `screen_list_windows` and inspect titles, `process_name`, and `bounds` (including which monitor the bounds lie on — check sign of `left`/`top` and whether width/height look right for a chart vs. a sidebar).
2. If the app has internal panels and the title does not encode the visible symbol, ask the user to confirm which `window_id` to capture, or ask them to maximise / foreground the specific panel first.
3. Prefer `screen_capture_window` by explicit `window_id` over `screen_capture_active_window` whenever multiple monitors are in play.

### Step 2 — verify the captured target BEFORE annotating or exporting

After capture, **look at the captured frame's actual content** — not just the metadata — and confirm it matches the user's stated intent. The window title alone is not sufficient evidence for multi-monitor / multi-pane apps.

Verification checklist:

- Read `metadata.window.title` and `metadata.window.process_name` from the capture result.
- Inspect the image bytes: identify the symbol/ticker, document title, or whatever the user asked for, and confirm it is visibly present and prominent in the captured frame.
- If the app shows multiple panels and only one is the intended target, confirm the intended panel is the one being captured — not a sibling panel that happens to share the same window.
- If the capture spans multiple monitors and the intended target is on one of them, confirm the captured frame actually contains that monitor's pixels (not just an empty/black region from a monitor with negative coordinates).

If verification fails — for example, the user asked for XRP and the captured frame shows the QQQ panel instead:

- Do **not** annotate.
- Do **not** export.
- Re-capture after the correct window/panel is foregrounded or maximised, ask the user to bring the intended target into view, or pick a different `window_id` from `screen_list_windows`.

This step is the safeguard against the QQQ-vs-XRP class of error documented in the postmortem. Treat it as a hard gate.

### Step 3 — annotate (optional)

Only after Step 2 passes. Use `screen_annotate_latest_image`.

### Step 4 — export ONCE per frame

Call `screen_export_latest_image` or `screen_export_annotated_image` **exactly once** for that captured/annotated frame.

- If the call returns `ok=true` but the payload cannot be displayed by this client, **do not retry the same export**. Repeated export against the same frame is itself a failure mode.
- If a retry is genuinely warranted (for example, the annotation needs to change), produce a *fresh* annotated frame first via Step 3, then export the new frame once.
- The tool's own `privacy_note` field already says this — treat it as binding, not as advisory.

### Step 5 — make the image user-visible (ChatGPT-specific)

Preferred clickable attachment path:

- If the source image is already in the ChatGPT sandbox (`/mnt/data/...`) or the assistant can produce it there with Python/PIL, write the final image to `/mnt/data/<descriptive-name>.jpg` and return a normal sandbox link/image reference. This is the user's preferred display style.
- This is exactly why the previous PIL example worked: `Image.open('/mnt/data/740ebd83-...jpg')` read a sandbox-local image, then `img.save('/mnt/data/annotated_screen_capture.jpg')` created a ChatGPT-clickable artifact.

MCP preview path:

- If the source exists only in MCP/local Windows storage, call `screen_export_latest_image` or `screen_export_annotated_image` with `include_data_url=true`, a reasonable `thumbnail_max_width` when needed, and `expose_data_url_in_text=false` unless the user explicitly asks for raw data.
- Rely on the returned MCP `image_content` object to render directly in the ChatGPT tool result.
- Do **not** substitute an MCP HTTP URL (`screen_latest_image_url`, `screen_annotated_image_url`, ngrok URL, raw `data_url`) for inline display. Those should only appear when the user explicitly asks for a direct URL.

Bridge rule:

- Do not require the sandbox/container to download the MCP/ngrok URL. The MCP connector and sandbox network paths are separate and may not have the same access.
- For MCP screenshots that need the user's preferred clickable `/mnt/data` style, use the dedicated bridge tools after capture/verification/annotation:
  - `screen_export_latest_artifact_code`
  - `screen_export_annotated_artifact_code`
- Those bridge tools return copy-ready `python_user_visible_code` containing the screenshot bytes. Run that code with `python_user_visible.exec` exactly once, then return the resulting `sandbox:/mnt/data/...` link/image.
- Do not claim a `/mnt/data` artifact can be made from an MCP screenshot unless one of those bridge tools returned code successfully or another internal tool already has the image in `/mnt/data`.

### Step 6 — confirm honestly

- State exactly what was captured and what the user should now see, including the verified target ("annotated screenshot of the XRP 1h Webull chart, window title `<title>`").
- If you cannot confirm the user can see the image, say so explicitly. Do not assert "displayed above" unless Step 5 actually produced a rendered MCP `image_content` result or a real `sandbox:/mnt/data/...` artifact.

## Failure modes that are explicitly forbidden

- Repeatedly calling the same export tool after `ok=true` on the same frame.
- Using an MCP HTTP image URL as a stand-in for inline display.
- Annotating or exporting without first verifying — by inspecting the actual captured pixels — that the captured target matches the user's intent. Title-matching alone is not verification for multi-monitor / multi-pane apps.
- Resizing screenshots unless the user explicitly asks for resizing.
- Claiming "the image is displayed above" when neither MCP `image_content` nor a real sandbox artifact has been produced.
- Treating an `ok=true` MCP return as proof that the user can see the image.

## User preference: screenshots and image output

- The user prefers clickable/openable inline ChatGPT attachments (`sandbox:/mnt/data/...`) when the image is already in the internal sandbox or can be created there with Python/PIL.
- The previous successful example used this exact pattern: open `/mnt/data/<source>.jpg`, annotate with PIL, save `/mnt/data/annotated_screen_capture.jpg`, then return the sandbox artifact.
- For MCP-only captures, first try the artifact bridge tools (`screen_export_latest_artifact_code` or `screen_export_annotated_artifact_code`) to create the preferred `/mnt/data` clickable artifact. If the bridge tool is unavailable or fails, fall back to MCP `image_content` preview rendering and say so explicitly.
- Do not use ngrok or normal HTTP image URLs as final delivery unless the user explicitly asks for a direct URL.
- Do not resize screenshots unless the user explicitly asks for resizing.
- Do not loop through repeated export attempts after a successful capture/export.

## Per-tool reference (screen tools)

- `screen_list_windows`: use when the user wants a specific window captured, or when clicking back to ChatGPT would change the active window. Always use before `screen_capture_window`.
- `screen_capture_window`: preferred for chart/app capture after listing windows; capture by `window_id` so ChatGPT focus does not matter.
- `screen_capture_once`: full-screen capture; only use when the user clearly wants the whole screen.
- `screen_capture_active_window`: default only when the target app is already foreground and will stay foreground during the call.
- `screen_get_latest_frame`: metadata only — useful for re-reading `metadata.window.title` during Step 2 verification.
- `screen_annotate_latest_image`: OK for creating local annotations, but still deliver inline (Step 5) instead of via an HTTP URL.
- `screen_export_latest_image`: MCP image-content preview path for an unannotated frame. Returns metadata plus MCP `image_content` for direct rendering; it may also include optional `data_url`/base64 diagnostics. Call **at most once per captured frame**.
- `screen_export_latest_artifact_code`: preferred ChatGPT clickable artifact bridge for an unannotated frame. It returns `python_user_visible_code`; run that code with `python_user_visible.exec` once, then return the `sandbox:/mnt/data/...` artifact.
- `screen_export_annotated_image`: MCP image-content preview path after `screen_annotate_latest_image`. Returns metadata plus MCP `image_content` for direct rendering; it may also include optional `data_url`/base64 diagnostics. Call **at most once per annotated frame**.
- `screen_export_annotated_artifact_code`: preferred ChatGPT clickable artifact bridge after `screen_annotate_latest_image`. It returns `python_user_visible_code`; run that code with `python_user_visible.exec` once, then return the `sandbox:/mnt/data/...` artifact.
- `screen_latest_image_url` / `screen_annotated_image_url`: avoid by default — the user said these make them save/download. Use only when explicitly asked for a direct URL or when both artifact bridge and MCP image-content export are genuinely unavailable.

Never call the same screen export URL/base64 tool repeatedly when the prior call already returned `ok=true`. Repeated export calls are a failure mode, not a recovery strategy.

## Local Files MCP usage

- Start by calling `list_roots` to confirm the currently allowlisted roots and access levels.
- Use `list_resources(..., only_tools=true, refetch_tools=true)` when tool availability is uncertain.
- Use read/list/search tools for inspection only; do not modify files unless the user requests it.
- For file writes, prefer `prepare_write` or `batch_prepare_write` so the local GUI can show a diff and require approval. Use direct `write_file` only when explicitly appropriate and safe.
- Use `batch_replace_text` for exact bounded edits across files, and review/commit only explicit operation IDs.
- Use `git_status` before and after meaningful project edits when working inside a git repo.
- Use `workflow_prepare` / `workflow_commit` / `workflow_continue` for bounded multi-step work so future assistants do not ask for repeated approvals unnecessarily.

## shadcn tools

- Use `shadcn_info` to inspect project config before adding components.
- Use `shadcn_search` and `shadcn_view` before installs.
- Run `shadcn_add` with `dry_run=true` first unless the user explicitly wants the actual install.

## Response style for this workflow

- Act, then report what changed.
- Keep confirmations short.
- Be explicit when a tool was blocked or required GUI approval.
- Do not claim persistent memory unless an instruction file or actual setting was written.
- Do not claim an image, file, or artifact is visible to the user unless the user-visible delivery step has actually completed.
