from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .collect_artifacts import FORBIDDEN_RUNTIME, REQUIRED_RUNTIME
from .common import (
    REPO_ROOT,
    load_lock,
    staging_dir,
    validate_architecture,
    work_root,
    write_json,
)
from .pe_utils import inspect_pe, is_debug_runtime, sha256


def verify(args: argparse.Namespace) -> None:
    lock = load_lock()
    architecture = validate_architecture(args.architecture, lock)
    release = (
        Path(args.release).resolve()
        if args.release
        else REPO_ROOT
        / "example"
        / "build"
        / "windows"
        / architecture
        / "runner"
        / "Release"
    )
    staging = (
        Path(args.staging).resolve()
        if args.staging
        else staging_dir(architecture)
    )
    expected_machine = lock["architectures"][architecture]["pe_machine"].lower()
    errors: list[str] = []
    outputs: dict[str, Any] = {}
    if not release.is_dir():
        raise RuntimeError(f"Flutter release directory is missing: {release}")
    paths = sorted(
        (
            path
            for path in release.iterdir()
            if path.is_file() and path.suffix.lower() in (".exe", ".dll")
        ),
        key=lambda path: path.name.lower(),
    )
    if not paths:
        errors.append(f"no PE outputs found in {release}")
    required_names = {
        "flutter_windows_angle_opengl_es_example.exe",
        "flutter_windows_angle_opengl_es_plugin.dll",
        *REQUIRED_RUNTIME,
    }
    all_release_files = {
        path.name: path for path in release.iterdir() if path.is_file()
    }
    actual_names = set(all_release_files)
    missing = sorted(required_names - actual_names)
    if missing:
        errors.append("missing Flutter outputs: " + ", ".join(missing))
    actual_names_lower = {name.lower(): name for name in actual_names}
    forbidden = sorted(
        actual_names_lower[name.lower()]
        for name in FORBIDDEN_RUNTIME
        if name.lower() in actual_names_lower
    )
    if forbidden:
        errors.append("forbidden Flutter runtime outputs: " + ", ".join(forbidden))
    runtime_hashes: dict[str, Any] = {}
    for name in REQUIRED_RUNTIME:
        staged_path = staging / "lib" / name
        release_path = release / name
        if not staged_path.is_file():
            errors.append(f"staging runtime is missing: {staged_path}")
            continue
        if not release_path.is_file():
            continue
        staged_hash = sha256(staged_path)
        release_hash = sha256(release_path)
        runtime_hashes[name] = {
            "staging_sha256": staged_hash,
            "release_sha256": release_hash,
            "matched": staged_hash == release_hash,
        }
        if staged_hash != release_hash:
            errors.append(f"{name}: Flutter output SHA-256 differs from staging")
    for path in paths:
        info = inspect_pe(path)
        outputs[path.name] = info
        print(f"{path.name}: machine={info['machine']} ({info['machine_name']})")
        if info["machine"].lower() != expected_machine:
            errors.append(
                f"{path.name}: expected PE machine {expected_machine}, "
                f"got {info['machine']}"
            )
        debug_imports = [
            name
            for name in info["runtime_dependencies"]
            if is_debug_runtime(name)
        ]
        if debug_imports:
            errors.append(
                f"{path.name}: imports Debug CRT: {', '.join(debug_imports)}"
            )
    report = {
        "passed": not errors,
        "architecture": architecture,
        "expected_machine": expected_machine,
        "release_directory": str(release),
        "staging_directory": str(staging),
        "outputs": outputs,
        "runtime_hashes": runtime_hashes,
        "forbidden_runtime": sorted(FORBIDDEN_RUNTIME),
        "errors": errors,
    }
    report_path = (
        Path(args.report).resolve()
        if args.report
        else work_root() / f"flutter-{architecture}-report.json"
    )
    write_json(report_path, report)
    if errors:
        raise RuntimeError(
            "Flutter output validation failed:\n- " + "\n- ".join(errors)
        )
    print(f"Flutter {architecture} PE validation passed")
