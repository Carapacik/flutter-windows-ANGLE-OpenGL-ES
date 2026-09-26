"""ANGLE Windows release pipeline: setup, build, verify, smoke, package."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import build as angle_build
import package as angle_package
import verify as angle_verify
from common import CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup")
    for name in ("build", "verify", "smoke", "package", "verify-example"):
        command = commands.add_parser(name)
        command.add_argument("architecture", choices=CONFIG["architectures"])
        if name == "verify":
            command.add_argument("--install", action="store_true")
        if name in ("verify", "smoke"):
            command.add_argument("--staging", type=Path)
        if name == "smoke":
            command.add_argument("--backend", choices=angle_verify.BACKENDS)
    commands.add_parser("checksums")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            angle_build.setup()
        elif args.command == "build":
            angle_build.build(args.architecture)
        elif args.command == "verify":
            angle_verify.verify(args.architecture, install=args.install, stage=args.staging)
        elif args.command == "smoke":
            angle_verify.smoke(args.architecture, stage=args.staging,
                               backend=args.backend)
        elif args.command == "package":
            angle_package.package(args.architecture)
        elif args.command == "verify-example":
            angle_verify.verify_example(args.architecture)
        elif args.command == "checksums":
            angle_package.checksums()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
