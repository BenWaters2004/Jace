from __future__ import annotations

import argparse
import json

from jace_device_agent.host_policy import host_policy_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("list")

    approve = sub.add_parser("approve-root")
    approve.add_argument("--path", required=True)
    approve.add_argument(
        "--shell",
        action="append",
        dest="shells",
        choices=["powershell", "cmd", "wsl", "bash"],
        required=True,
    )
    approve.add_argument("--process", action="store_true")
    approve.add_argument("--terminal", action="store_true")

    revoke = sub.add_parser("revoke-root")
    revoke.add_argument("--path", required=True)

    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(host_policy_registry.status(), indent=2))
        return 0

    if args.command == "list":
        print(
            json.dumps(
                [r.payload() for r in host_policy_registry.roots()],
                indent=2,
            )
        )
        return 0

    if args.command == "approve-root":
        result = host_policy_registry.approve_root(
            path=args.path,
            allowed_shells=args.shells,
            process_enabled=args.process,
            terminal_enabled=args.terminal,
        )
        print(json.dumps(result.payload(), indent=2))
        print()
        print(
            "Local authority recorded. Strong isolation is still unavailable; "
            "arbitrary remote shells remain fail-closed until 4B.4C.2."
        )
        return 0

    if args.command == "revoke-root":
        removed = host_policy_registry.revoke_root(args.path)
        print("Removed." if removed else "No matching approved root.")
        return 0 if removed else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
