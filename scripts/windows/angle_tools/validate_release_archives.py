from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .collect_artifacts import (
    FORBIDDEN_RUNTIME,
    HEADER_DIRECTORIES,
    REQUIRED_LIBS,
    REQUIRED_RUNTIME,
    d3dcompiler_notice,
)
from .common import (
    archive_name,
    archive_timestamp,
    command_environment,
    contains_absolute_windows_path,
    dist_dir,
    find_executable,
    load_lock,
    reset_directory,
    run,
    work_root,
    write_json,
)
from .pe_utils import (
    IMAGE_DEBUG_TYPE_REPRO,
    inspect_import_library,
    inspect_pe,
    is_debug_runtime,
    sha256,
)


REPRODUCIBLE_RUNTIME = {"libegl.dll", "libglesv2.dll", "vulkan-1.dll"}


def file_map(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def validate_archive(
    archive: Path, architecture: str, lock: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    extracted = work_root() / "archive-validation" / architecture
    reset_directory(extracted)
    environment = command_environment()
    seven_zip = find_executable(["7z.exe", "7z"], env=environment)
    run(
        [seven_zip, "x", "-y", f"-o{extracted}", archive],
        env=environment,
    )

    files = file_map(extracted)
    expected_timestamp = int(archive_timestamp(lock).timestamp())
    for name, path in files.items():
        actual_timestamp = int(path.stat().st_mtime)
        if actual_timestamp != expected_timestamp:
            errors.append(
                f"{name}: expected archive timestamp "
                f"{lock['archive_timestamp']['value']}, got "
                f"{actual_timestamp}"
            )
    expected_libs = set(REQUIRED_RUNTIME) | set(REQUIRED_LIBS)
    actual_libs = {
        path.name for path in (extracted / "lib").iterdir() if path.is_file()
    } if (extracted / "lib").is_dir() else set()
    if actual_libs != expected_libs:
        errors.append(
            "lib file set mismatch: "
            f"expected {sorted(expected_libs)}, got {sorted(actual_libs)}"
        )
    for directory in HEADER_DIRECTORIES:
        header_root = extracted / "include" / directory
        if not header_root.is_dir() or not any(header_root.rglob("*.h")):
            errors.append(f"missing public headers: include/{directory}")
    for forbidden in FORBIDDEN_RUNTIME:
        if any(path.name.lower() == forbidden.lower() for path in files.values()):
            errors.append(f"forbidden runtime present: {forbidden}")

    manifest_path = extracted / "manifest.json"
    manifest: dict[str, Any] = {}
    if not manifest_path.is_file():
        errors.append("manifest.json is missing")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 2:
            errors.append("manifest schema_version must be 2")
        if manifest.get("architecture") != architecture:
            errors.append("manifest architecture mismatch")
        if manifest.get("angle") != lock["angle"]:
            errors.append("manifest ANGLE pin mismatch")
        if manifest.get("archive_timestamp") != lock["archive_timestamp"]:
            errors.append("manifest archive timestamp policy mismatch")
        if contains_absolute_windows_path(manifest):
            errors.append("manifest contains an absolute Windows path")
        metadata = {
            item["path"]: item
            for item in manifest.get("files", [])
            if isinstance(item, dict) and "path" in item
        }
        expected_metadata = set(files) - {"manifest.json"}
        if set(metadata) != expected_metadata:
            errors.append("manifest file list does not match archive content")
        for name, item in metadata.items():
            path = files.get(name)
            if path is None:
                continue
            if sha256(path) != item.get("sha256"):
                errors.append(f"manifest hash mismatch: {name}")

    notice = extracted / "LICENSES" / "Microsoft-Windows-SDK-D3DCompiler.txt"
    if (
        not notice.is_file()
        or notice.read_text(encoding="utf-8")
        != d3dcompiler_notice(lock, architecture)
    ):
        errors.append("Windows SDK d3dcompiler notice mismatch")
    if not (
        extracted / "LICENSES" / "Microsoft-Windows-SDK-License.rtf"
    ).is_file():
        errors.append("Windows SDK license is missing")

    expected_machine = lock["architectures"][architecture]["pe_machine"].lower()
    pe_files: dict[str, Any] = {}
    for name in REQUIRED_RUNTIME:
        path = extracted / "lib" / name
        if not path.is_file():
            continue
        info = inspect_pe(path)
        pe_files[name] = info
        if info["machine"].lower() != expected_machine:
            errors.append(
                f"{name}: expected PE machine {expected_machine}, "
                f"got {info['machine']}"
            )
        debug_imports = [
            imported
            for imported in info["runtime_dependencies"]
            if is_debug_runtime(imported)
        ]
        if debug_imports:
            errors.append(
                f"{name}: imports Debug CRT: {', '.join(debug_imports)}"
            )
        if (
            name.lower() in REPRODUCIBLE_RUNTIME
            and IMAGE_DEBUG_TYPE_REPRO not in info["debug_types"]
        ):
            errors.append(f"{name}: LLD REPRO debug record is missing")

    import_libraries: dict[str, Any] = {}
    for name in REQUIRED_LIBS:
        path = extracted / "lib" / name
        if not path.is_file():
            continue
        info = inspect_import_library(path)
        import_libraries[name] = info
        actual = [machine.lower() for machine in info["machines"]]
        if actual != [expected_machine]:
            errors.append(
                f"{name}: expected COFF machine {expected_machine}, "
                f"got {info['machines']}"
            )

    return {
        "passed": not errors,
        "architecture": architecture,
        "archive": archive.name,
        "archive_sha256": sha256(archive),
        "pe_files": pe_files,
        "import_libraries": import_libraries,
        "errors": errors,
    }


def read_checksums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not name:
            raise RuntimeError(f"Invalid SHA256SUMS line: {line!r}")
        result[name] = digest.lower()
    return result


def validate(args: argparse.Namespace) -> None:
    lock = load_lock()
    root = Path(args.dist).resolve() if args.dist else dist_dir()
    expected = {
        archive_name(lock, architecture)
        for architecture in lock["architectures"]
    }
    obsolete = sorted(
        path.name
        for pattern in ("ANGLE-*-windows-*.zip",)
        for path in root.glob(pattern)
        if path.is_file()
    )
    if obsolete:
        raise RuntimeError(
            "Obsolete ZIP archives are not allowed: " + ", ".join(obsolete)
        )

    reports: dict[str, Any] = {}
    errors: list[str] = []
    for architecture in lock["architectures"]:
        path = root / archive_name(lock, architecture)
        if not path.is_file():
            errors.append(f"missing release archive: {path.name}")
            continue
        print(f"Validate {path}", flush=True)
        report = validate_archive(path, architecture, lock)
        reports[architecture] = report
        errors.extend(
            f"{architecture}: {error}" for error in report["errors"]
        )

    actual = {
        path.name
        for path in root.glob("ANGLE-*-windows-*.7z")
        if path.is_file()
    }
    if actual != expected:
        errors.append(
            f"release archive names mismatch: expected {sorted(expected)}, "
            f"got {sorted(actual)}"
        )

    checksums_path = root / "SHA256SUMS"
    if args.require_checksums:
        if not checksums_path.is_file():
            errors.append("SHA256SUMS is missing")
        else:
            checksums = read_checksums(checksums_path)
            if set(checksums) != expected:
                errors.append("SHA256SUMS file set mismatch")
            for name in expected:
                path = root / name
                if path.is_file() and checksums.get(name) != sha256(path):
                    errors.append(f"SHA256SUMS mismatch: {name}")

    report_path = (
        Path(args.report).resolve()
        if args.report
        else work_root() / "archive-validation-report.json"
    )
    write_json(
        report_path,
        {
            "passed": not errors,
            "archives": reports,
            "errors": errors,
        },
    )
    if errors:
        raise RuntimeError(
            "release archive validation failed:\n- " + "\n- ".join(errors)
        )
    print("Both release 7z archives and checksums passed validation")
