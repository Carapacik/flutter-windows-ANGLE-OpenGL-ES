from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .common import (
    archive_name,
    archive_timestamp,
    command_environment,
    contains_absolute_windows_path,
    dist_dir,
    find_executable,
    load_lock,
    output_dir,
    reset_directory,
    run,
    staging_dir,
    validate_architecture,
    work_root,
    write_json,
)
from .pe_utils import sha256


REPORT_NAMES = {
    "collect-report.json",
    "repository-verify-report.json",
    "verify-report.json",
    "smoke-report.json",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def archive_files(package_root: Path) -> list[Path]:
    return sorted(
        (path for path in package_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )


def file_metadata(package_root: Path) -> list[dict[str, Any]]:
    result = []
    for path in archive_files(package_root):
        relative = path.relative_to(package_root).as_posix()
        result.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return result


def sanitize_manifest_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_manifest_metadata(item)
            for key, item in value.items()
            if key not in {"executable", "resolved_source", "runner_name"}
        }
    if isinstance(value, list):
        return [sanitize_manifest_metadata(item) for item in value]
    if isinstance(value, str):
        return "\n".join(
            line
            for line in value.splitlines()
            if not contains_absolute_windows_path(line)
        )
    return value


def build_manifest(
    architecture: str,
    package_root: Path,
    lock: dict[str, Any],
    verify_report: dict[str, Any],
    smoke_report: dict[str, Any],
    build_report: dict[str, Any],
) -> dict[str, Any]:
    d3dcompiler_provenance = {
        key: value
        for key, value in verify_report["d3dcompiler_provenance"].items()
        if key != "resolved_source"
    }
    return {
        "schema_version": 2,
        "release_version": lock["release_version"],
        "architecture": architecture,
        "angle": lock["angle"],
        "archive_timestamp": lock["archive_timestamp"],
        "flutter_angle_reference": lock["flutter_angle_reference"],
        "gn_args": build_report["gn_args"],
        "build_targets": build_report["targets"],
        "toolchain": {
            **sanitize_manifest_metadata(build_report["toolchain"]),
            "native_smoke": sanitize_manifest_metadata(
                smoke_report.get("build_toolchain")
            ),
        },
        "windows_sdk": {
            **lock["windows_sdk"],
            "resolved_build_version": build_report["toolchain"][
                "windows_sdk_version"
            ],
            "angle_toolchain_override_result": build_report[
                "windows_sdk_override"
            ],
            "angle_linker_reproducibility_override_result": build_report[
                "linker_reproducibility_override"
            ],
        },
        "dependencies": lock["dependencies"],
        "runtime": {
            "pe_files": verify_report["pe_files"],
            "import_libraries": verify_report["import_libraries"],
            "external_prerequisites": verify_report["external_prerequisites"],
            "libcxx": {"included": False, "reason": "not imported by runtime"},
            "zlib": {"included": False, "reason": "not imported by runtime"},
            "d3dcompiler": {
                "included": True,
                "file": "lib/d3dcompiler_47.dll",
                "reason": (
                    "application-local Windows SDK redistributable for "
                    "self-contained deployment"
                ),
                "provenance": d3dcompiler_provenance,
            },
            "vulkan_loader": {
                "included": True,
                "file": "lib/vulkan-1.dll",
                "reason": "hardware Vulkan backend dynamically loads vulkan-1.dll",
            },
        },
        "validation": {
            "artifacts": {"passed": verify_report["passed"]},
            "headers": verify_report["headers"],
            "d3d11": smoke_report["results"]["d3d11"],
            "desktop_gl": smoke_report["results"].get("desktop_gl"),
            "native_gles": smoke_report["results"].get("native_gles"),
            "vulkan": smoke_report["results"].get("vulkan"),
            "interop_d3d11": smoke_report["results"].get("interop_d3d11"),
            "interop_warp": smoke_report["results"].get("interop_warp"),
            "native_execution": {
                "tested": smoke_report.get("executed", True),
                "passed": (
                    smoke_report["passed"]
                    if smoke_report.get("executed", True)
                    else None
                ),
                "architecture": smoke_report["architecture"],
            },
            "backends_built": [
                "d3d11",
                "desktop_gl",
                "native_gles",
                "vulkan",
            ],
            "swiftshader": {
                "included": False,
                "note": "not required for the hardware Vulkan backend",
            },
        },
        "build_host": sanitize_manifest_metadata(build_report["build_host"]),
        "native_test_host": sanitize_manifest_metadata(
            smoke_report["native_test_host"]
        ),
        "files": file_metadata(package_root),
    }


def create_7z(package_root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    environment = command_environment()
    seven_zip = find_executable(["7z.exe", "7z"], env=environment)
    run(
        [
            seven_zip,
            "a",
            "-t7z",
            "-mx=9",
            "-mmt=off",
            "-mtc=off",
            "-mta=off",
            "-mtm=on",
            destination,
            "*",
        ],
        cwd=package_root,
        env=environment,
    )


def normalize_archive_timestamps(
    package_root: Path, lock: dict[str, Any]
) -> None:
    timestamp = archive_timestamp(lock).timestamp()
    paths = sorted(
        package_root.rglob("*"),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in paths:
        os.utime(path, (timestamp, timestamp))


def verify_7z(
    package_root: Path,
    archive_path: Path,
    expected_manifest: dict[str, Any],
) -> None:
    extracted = work_root() / "archive-check" / archive_path.stem
    reset_directory(extracted)
    environment = command_environment()
    seven_zip = find_executable(["7z.exe", "7z"], env=environment)
    run(
        [seven_zip, "x", "-y", f"-o{extracted}", archive_path],
        env=environment,
    )
    expected = {
        path.relative_to(package_root).as_posix(): path
        for path in archive_files(package_root)
    }
    actual = {
        path.relative_to(extracted).as_posix(): path
        for path in archive_files(extracted)
    }
    if set(actual) != set(expected):
        raise RuntimeError(
            "7z content mismatch: "
            f"expected {sorted(expected)}, got {sorted(actual)}"
        )
    for name, expected_path in expected.items():
        actual_path = actual[name]
        if sha256(expected_path) != sha256(actual_path):
            raise RuntimeError(f"7z payload mismatch: {name}")
    archived_manifest = load_json(actual["manifest.json"])
    if archived_manifest != expected_manifest:
        raise RuntimeError("Archived manifest does not match generated manifest")
    if contains_absolute_windows_path(archived_manifest):
        raise RuntimeError("Archived manifest contains an absolute Windows path")


def package(args: argparse.Namespace) -> None:
    lock = load_lock()
    architecture = validate_architecture(args.architecture, lock)
    staging = staging_dir(architecture)
    verify_path = staging / "verify-report.json"
    smoke_path = staging / "smoke-report.json"
    build_path = output_dir(architecture) / "build-report.json"
    for required in (verify_path, smoke_path, build_path):
        if not required.is_file():
            raise RuntimeError(f"Required successful report is missing: {required}")
    verify_report = load_json(verify_path)
    smoke_report = load_json(smoke_path)
    build_report = load_json(build_path)
    for report_name, report in (
        ("verify-report.json", verify_report),
        ("smoke-report.json", smoke_report),
        ("build-report.json", build_report),
    ):
        if report.get("architecture") != architecture:
            raise RuntimeError(
                f"{report_name} architecture mismatch: expected {architecture}, "
                f"got {report.get('architecture')!r}"
            )
        if report.get("errors"):
            raise RuntimeError(f"{report_name} contains errors: {report['errors']}")
    if verify_report.get("passed") is not True:
        raise RuntimeError("Artifact verification did not pass")
    if build_report.get("angle_commit") != lock["angle"]["commit"]:
        raise RuntimeError(
            "Build report ANGLE commit mismatch: expected "
            f"{lock['angle']['commit']}, got "
            f"{build_report.get('angle_commit')!r}"
        )
    resolved_sdk = build_report.get("toolchain", {}).get(
        "windows_sdk_version"
    )
    minimum_sdk = tuple(
        int(part) for part in lock["windows_sdk"]["minimum_version"].split(".")
    )
    resolved_sdk_tuple = tuple(
        int(part) for part in str(resolved_sdk).split(".")
    )
    if resolved_sdk_tuple < minimum_sdk:
        raise RuntimeError(
            "Build report Windows SDK is below the configured minimum "
            f"{lock['windows_sdk']['minimum_version']}: {resolved_sdk!r}"
        )
    if smoke_report.get("passed") is not True:
        raise RuntimeError("All native smoke tests must pass before packaging")
    if smoke_report.get("executed", True):
        required_backends = ["d3d11", "interop_d3d11", "interop_warp"]
        for backend in required_backends:
            if not smoke_report.get("results", {}).get(backend, {}).get("passed"):
                raise RuntimeError(f"{backend} smoke test did not pass")
    elif architecture != "arm64":
        raise RuntimeError(
            "Only ARM64 may be packaged with a validated native-smoke skip"
        )

    package_root = work_root() / "package" / architecture
    reset_directory(package_root)
    print(f"[1/4] Copy verified {architecture} staging into package root", flush=True)
    for path in staging.iterdir():
        if path.name in REPORT_NAMES:
            continue
        destination = package_root / path.name
        if path.is_dir():
            shutil.copytree(path, destination)
        elif path.is_file():
            shutil.copy2(path, destination)
    print("[2/4] Generate manifest from build, PE, and smoke reports", flush=True)
    manifest = build_manifest(
        architecture,
        package_root,
        lock,
        verify_report,
        smoke_report,
        build_report,
    )
    write_json(package_root / "manifest.json", manifest)
    normalize_archive_timestamps(package_root, lock)
    archive = dist_dir() / archive_name(lock, architecture)
    print(f"[3/4] Create 7z archive {archive}", flush=True)
    create_7z(package_root, archive)
    print(
        "[4/4] Extract 7z and verify paths, manifest, and hashes",
        flush=True,
    )
    verify_7z(package_root, archive, manifest)
    print(f"Created {archive}")
    print(f"SHA-256 {sha256(archive)}")


def checksums(_: argparse.Namespace) -> None:
    lock = load_lock()
    archives = [
        dist_dir() / archive_name(lock, architecture)
        for architecture in lock["architectures"]
    ]
    missing = [str(path) for path in archives if not path.is_file()]
    if missing:
        raise RuntimeError("Cannot create checksums; missing: " + ", ".join(missing))
    lines = [f"{sha256(path)}  {path.name}" for path in sorted(archives)]
    output = dist_dir() / "SHA256SUMS"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(output.read_text(encoding="utf-8"), end="")
