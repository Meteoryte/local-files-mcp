from __future__ import annotations

import argparse
import json

import uvicorn

from .auth import create_pairing_session, clear_session
from .config import (
    CONFIG_PATH, add_root, apply_full_access, apply_home_read, apply_project,
    apply_safe_inbox, default_config, load_config, save_config,
)
from .settings import format_settings, detect_ngrok, normalize_public_base_url, validate_chatgpt_url, mcp_url
from .pending import list_pending, approve as approve_op, reject as reject_op


def cmd_init(args):
    cfg = load_config()
    print(f"Config: {CONFIG_PATH}")
    print(f"Profile: {cfg.get('profile')}")


def cmd_setup(args):
    cfg = default_config()
    print("\nLocal Files MCP setup")
    print("=====================")
    print("1. Safe inbox only: ~/ChatGPT-MCP-Inbox, read-only")
    print("2. One project folder, read-only")
    print("3. Home folder, read-only, with deny rules")
    print("4. FULL ACCESS: entire disk/root, read/write, dangerous")
    choice = (args.preset or input("Choose preset [1]: ").strip() or "1").strip()

    if choice in {"1", "safe", "safe_inbox"}:
        apply_safe_inbox(cfg)
    elif choice in {"2", "project"}:
        path = args.path or input("Project folder path: ").strip()
        write = bool(args.write)
        if not args.path:
            write = (input("Allow write preparation in this project? [y/N]: ").strip().lower() == "y")
        apply_project(cfg, path, write=write)
    elif choice in {"3", "home", "home_read"}:
        apply_home_read(cfg)
    elif choice in {"4", "full", "full_access"}:
        phrase = "I UNDERSTAND FULL ACCESS"
        if not args.i_understand_this_is_dangerous:
            typed = input(f"Type exactly {phrase!r} to continue: ").strip()
            if typed != phrase:
                raise SystemExit("Cancelled full access setup.")
        apply_full_access(cfg)
    else:
        raise SystemExit("Unknown preset")

    save_config(cfg)
    print(f"\nWrote {CONFIG_PATH}")
    print(format_settings(cfg))


def cmd_show(args):
    print(json.dumps(load_config(), indent=2))


def cmd_settings(args):
    print(format_settings(load_config()))


def cmd_set_public_url(args):
    cfg = load_config()
    cfg.setdefault("server", {})["public_url"] = normalize_public_base_url(args.url)
    save_config(cfg)
    print(format_settings(cfg))


def cmd_detect_tunnel(args):
    url = detect_ngrok()
    if not url:
        raise SystemExit("No ngrok tunnel detected at http://127.0.0.1:4040/api/tunnels. Start ngrok or use set-public-url.")
    print(url)
    if args.save:
        cfg = load_config()
        cfg.setdefault("server", {})["public_url"] = normalize_public_base_url(url)
        save_config(cfg)
        print("Saved public_url.")
        print(format_settings(cfg))


def cmd_validate_url(args):
    cfg = load_config()
    if args.url:
        cfg.setdefault("server", {})["public_url"] = normalize_public_base_url(args.url)
    ok, message, corrected = validate_chatgpt_url(mcp_url(cfg))
    print(format_settings(cfg))
    if not ok:
        raise SystemExit(message)


def cmd_set_auth(args):
    cfg = load_config()
    cfg.setdefault("server", {})["auth_mode"] = args.mode
    save_config(cfg)
    print(f"Auth mode set to {args.mode}.")
    print(format_settings(cfg))


def cmd_pair(args):
    cfg = load_config()
    ttl = int(cfg.get("auth", {}).get("pairing_code_ttl_seconds", 600))
    code = create_pairing_session(ttl)
    print("\nPairing code")
    print("============")
    print(code)
    print(f"\nExpires in {ttl} seconds. Enter it only on the Local Files MCP auth page.")


def cmd_logout(args):
    clear_session()
    print("Cleared pairing session and tokens.")


def cmd_add_root(args):
    cfg = load_config()
    root = add_root(cfg, args.id, args.path, access=args.access, full=args.full)
    save_config(cfg)
    print(json.dumps(root, indent=2))


def cmd_full_access(args):
    cfg = load_config()
    apply_full_access(cfg)
    save_config(cfg)
    print("FULL ACCESS enabled in config.")
    print(format_settings(cfg))


def cmd_pending(args):
    print(json.dumps(list_pending(), indent=2))


def cmd_approve(args):
    print(json.dumps(approve_op(args.operation_id), indent=2))


def cmd_reject(args):
    print(json.dumps(reject_op(args.operation_id), indent=2))


def cmd_start(args):
    cfg = load_config()
    host = args.host or cfg.get("server", {}).get("host", "127.0.0.1")
    port = args.port or int(cfg.get("server", {}).get("port", 8765))
    print(format_settings(cfg))
    print(f"Starting Local Files MCP on http://{host}:{port}/mcp")
    uvicorn.run("local_files_mcp.server:app", host=host, port=port, reload=args.reload)



def cmd_gui(args):
    from .admin_gui import main as gui_main
    gui_main()


def build_parser():
    p = argparse.ArgumentParser(prog="local-files-mcp")
    sub = p.add_subparsers(required=True)

    sp = sub.add_parser("init")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("setup")
    sp.add_argument("--preset", help="safe, project, home, full")
    sp.add_argument("--path")
    sp.add_argument("--write", action="store_true")
    sp.add_argument("--i-understand-this-is-dangerous", action="store_true")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("show")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("settings")
    sp.set_defaults(func=cmd_settings)

    sp = sub.add_parser("set-public-url")
    sp.add_argument("url")
    sp.set_defaults(func=cmd_set_public_url)

    sp = sub.add_parser("detect-tunnel")
    sp.add_argument("--save", action="store_true")
    sp.set_defaults(func=cmd_detect_tunnel)

    sp = sub.add_parser("validate-url")
    sp.add_argument("url", nargs="?")
    sp.set_defaults(func=cmd_validate_url)

    sp = sub.add_parser("set-auth")
    sp.add_argument("mode", choices=["noauth", "oauth"])
    sp.set_defaults(func=cmd_set_auth)

    sp = sub.add_parser("pair")
    sp.set_defaults(func=cmd_pair)

    sp = sub.add_parser("logout")
    sp.set_defaults(func=cmd_logout)

    sp = sub.add_parser("add-root")
    sp.add_argument("path")
    sp.add_argument("--id", required=True)
    sp.add_argument("--access", default="read", choices=["none", "metadata", "search", "read", "write"])
    sp.add_argument("--full", action="store_true", help="Allow all extensions and no deny globs for this root")
    sp.set_defaults(func=cmd_add_root)

    sp = sub.add_parser("full-access")
    sp.add_argument("--i-understand-this-is-dangerous", action="store_true", required=True)
    sp.set_defaults(func=cmd_full_access)

    sp = sub.add_parser("pending")
    sp.set_defaults(func=cmd_pending)

    sp = sub.add_parser("approve")
    sp.add_argument("operation_id")
    sp.set_defaults(func=cmd_approve)

    sp = sub.add_parser("reject")
    sp.add_argument("operation_id")
    sp.set_defaults(func=cmd_reject)

    sp = sub.add_parser("gui")
    sp.set_defaults(func=cmd_gui)

    sp = sub.add_parser("start")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=cmd_start)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
