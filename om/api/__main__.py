"""CLI: `python3 -m om.api serve|seed-demo|create-org|poll-mail` (SPEC §2)."""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from . import auth, state as state_mod


def _data(args) -> str:
    return args.data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m om.api", description="Acretia product API")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web app and API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8791)
    s.add_argument("--data", default="data/app")
    s.add_argument("--demo", action="store_true", help="seed the demo org and run in replay mode")
    s.add_argument("--llm-mode", default=None, help="replay | live (default: ACRETIA_LLM_MODE, or replay with --demo)")
    d = sub.add_parser("seed-demo", help="create the demo org, users, deals and documents")
    d.add_argument("--data", default="data/app")
    c = sub.add_parser("create-org", help="create an organization with its first owner")
    c.add_argument("--data", default="data/app")
    c.add_argument("--name", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--owner-name", default="")
    c.add_argument("--password", default=None, help="or set ACRETIA_OWNER_PASSWORD, or you will be prompted")
    m = sub.add_parser("poll-mail", help="poll the configured mailbox once")
    m.add_argument("--data", default="data/app")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from . import demo, server
        st = state_mod.create(args.data, llm_mode=args.llm_mode, demo=args.demo)
        if args.demo:
            demo.seed(args.data, st)
        server.serve(st, args.host, args.port)
        return 0
    if args.cmd == "seed-demo":
        from . import demo
        res = demo.seed(args.data)
        print(f"Demo ready in {args.data}: org {res['org_id']}, {len(res['deals'])} deals, "
              f"{res['documents_added']} documents added. Sign in as owner@meridian.example "
              f"(password: ${res['password_env']} or demo-password-123).")
        return 0
    if args.cmd == "create-org":
        pw = args.password or os.environ.get("ACRETIA_OWNER_PASSWORD") or getpass.getpass("Owner password: ")
        st = state_mod.create(args.data)
        try:
            res = auth.create_org(st.conn(), args.name, args.email, pw, args.owner_name or args.email.split("@")[0])
        except ValueError as e:
            print(f"Could not create the organization: {e}.", file=sys.stderr)
            return 2
        print(f"Created {args.name} ({res['org_id']}); owner {args.email}.")
        return 0
    if args.cmd == "poll-mail":
        import importlib
        try:
            mail = importlib.import_module("om.api.mail")
        except ModuleNotFoundError:
            print("Mail polling is not available in this build yet (om.api.mail is missing).", file=sys.stderr)
            return 2
        st = state_mod.create(args.data)
        fn = getattr(mail, "poll_once", None) or getattr(mail, "poll", None)
        if fn is None:
            print("om.api.mail has no poll_once(state) entry point.", file=sys.stderr)
            return 2
        fn(st)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
