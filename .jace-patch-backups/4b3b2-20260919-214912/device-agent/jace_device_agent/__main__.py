from __future__ import annotations

import argparse
import asyncio
import json
import sys

from jace_device_agent.client import (
    DeviceAgentClient,
    pair_with_core,
)
from jace_device_agent.config import (
    AgentConfig,
    config_path,
    normalise_server_url,
)
from jace_device_agent.credentials import credential_store
from jace_device_agent.identity import collect_identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jace-device-agent",
        description=(
            "Trusted outbound device connection for Jace Core."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    pair_parser = subparsers.add_parser(
        "pair",
        help="Pair this computer with Jace Core.",
    )
    pair_parser.add_argument(
        "--server",
        required=True,
        help="Jace Core URL, e.g. http://127.0.0.1:8000",
    )
    pair_parser.add_argument(
        "--pairing-code",
        required=True,
    )
    pair_parser.add_argument(
        "--name",
        default=None,
        help="Friendly device name. Defaults to hostname.",
    )
    pair_parser.add_argument(
        "--allow-insecure-remote",
        action="store_true",
        help=(
            "Allow non-HTTPS remote Core URLs. "
            "Use only on controlled development networks."
        ),
    )

    subparsers.add_parser(
        "run",
        help="Connect to Jace Core and remain online.",
    )

    subparsers.add_parser(
        "status",
        help="Show local Device Agent configuration.",
    )

    subparsers.add_parser(
        "identity",
        help="Show the host identity/capabilities advertised to Jace.",
    )

    # JACE_4B3B1_PROCESS_RUNTIME_CLI
    process_parser = subparsers.add_parser(
        "process-runtime",
        help="Enable, disable or inspect remote process execution.",
    )
    process_parser.add_argument(
        "action",
        choices=["enable", "disable", "status"],
    )

    return parser


async def run_pair(args) -> int:
    server_url = normalise_server_url(args.server)

    config = await pair_with_core(
        server_url=server_url,
        pairing_code=args.pairing_code,
        device_name=args.name,
        allow_insecure_remote=args.allow_insecure_remote,
    )

    print()
    print("Device paired successfully.")
    print(f"Device ID: {config.device_id}")
    print(f"Name:      {config.device_name}")
    print(f"Core:      {config.server_url}")
    print()
    print(
        "The private device credential was stored in the "
        "operating-system credential store."
    )
    print(
        "Run `python -m jace_device_agent run` "
        "to connect the Device Agent."
    )

    return 0


async def run_agent() -> int:
    config = AgentConfig.load()
    client = DeviceAgentClient(config)

    try:
        await client.run_forever()
    except KeyboardInterrupt:
        client.stop()

    return 0


def show_status() -> int:
    try:
        config = AgentConfig.load()
    except RuntimeError as exc:
        print(str(exc))
        return 1

    token_present = bool(
        credential_store.get_device_token(
            config.device_id
        )
    )

    print(
        json.dumps(
            {
                "configured": True,
                "config_path": str(config_path()),
                "server_url": config.server_url,
                "device_id": config.device_id,
                "device_name": config.device_name,
                "credential_present": token_present,
                "process_runtime_enabled": config.allow_process_execution,
            },
            indent=2,
        )
    )

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "pair":
        return asyncio.run(run_pair(args))

    if args.command == "run":
        return asyncio.run(run_agent())

    if args.command == "status":
        return show_status()

    if args.command == "identity":
        print(
            json.dumps(
                collect_identity(),
                indent=2,
            )
        )
        return 0

    if args.command == "process-runtime":
        config = AgentConfig.load()

        if args.action == "enable":
            config.allow_process_execution = True
            config.save()
            print(
                "Device Agent process runtime enabled. "
                "Restart the Device Agent to advertise process.runtime."
            )
            return 0

        if args.action == "disable":
            config.allow_process_execution = False
            config.save()
            print(
                "Device Agent process runtime disabled. "
                "Restart the Device Agent to remove process.runtime."
            )
            return 0

        print(
            json.dumps(
                {
                    "enabled": (
                        config.allow_process_execution
                    ),
                    "config_path": str(
                        config_path()
                    ),
                },
                indent=2,
            )
        )
        return 0

    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
