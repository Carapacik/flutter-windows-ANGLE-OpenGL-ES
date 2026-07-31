from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path
from typing import Iterable

from .common import (
    angle_source,
    load_lock,
    output_dir,
    reset_directory,
    staging_dir,
    validate_architecture,
    write_json,
)
from .pe_utils import inspect_pe, sha256


ANGLE_RUNTIME = ("libEGL.dll", "libGLESv2.dll", "vulkan-1.dll")
REQUIRED_RUNTIME = (*ANGLE_RUNTIME, "d3dcompiler_47.dll")
REQUIRED_LIBS = ("libEGL.dll.lib", "libGLESv2.dll.lib")
BUILD_LIBS = {name: name for name in REQUIRED_LIBS}
CONDITIONAL_RUNTIME: tuple[str, ...] = ()
FORBIDDEN_RUNTIME = (
    "vk_swiftshader.dll",
    "vk_swiftshader_icd.json",
    "zlib.dll",
    "libc++.dll",
)
HEADER_DIRECTORIES = ("EGL", "GLES2", "GLES3", "KHR")

LICENSE_SOURCES = {
    "ANGLE.txt": (("LICENSE",),),
    "Vulkan-Loader.txt": (
        ("third_party", "vulkan-loader", "src", "LICENSE.txt"),
        ("third_party", "vulkan-loader", "src", "LICENSE.md"),
    ),
    "Abseil.txt": (
        ("third_party", "abseil-cpp", "LICENSE"),
        ("third_party", "abseil-cpp", "LICENSE.txt"),
    ),
}


def windows_sdk_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    sdk_dir = os.environ.get("WindowsSdkDir") or os.environ.get("WINDOWSSDKDIR")
    if sdk_dir:
        candidates.append(Path(sdk_dir))
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Windows Kits" / "10")
    candidates.append(Path(r"C:\Program Files (x86)\Windows Kits\10"))
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def select_latest_sdk_version(
    versions: Iterable[str], minimum: str
) -> str | None:
    minimum_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", minimum)
    if not minimum_match:
        raise RuntimeError(f"Invalid minimum Windows SDK version: {minimum}")
    minimum_version = tuple(int(part) for part in minimum_match.groups())
    matches: list[tuple[int, int, int, int]] = []
    for text in versions:
        version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", text)
        if not version_match:
            continue
        version = tuple(int(part) for part in version_match.groups())
        if version >= minimum_version:
            matches.append(version)
    if not matches:
        return None
    return ".".join(str(part) for part in max(matches))


def find_latest_windows_sdk(
    lock: dict[str, object], sdk_root: Path | None = None
) -> tuple[Path, str]:
    sdk = lock["windows_sdk"]
    assert isinstance(sdk, dict)
    minimum = str(sdk["minimum_version"])
    candidates = (
        [sdk_root.resolve()] if sdk_root else windows_sdk_root_candidates()
    )
    diagnostics: list[str] = []
    matches: list[tuple[str, Path]] = []
    for root in candidates:
        include_root = root / "Include"
        if not include_root.is_dir():
            diagnostics.append(f"{root}: missing {include_root}")
            continue
        directories = [
            directory
            for directory in include_root.iterdir()
            if directory.is_dir()
        ]
        selected = select_latest_sdk_version(
            (directory.name for directory in directories), minimum
        )
        if selected:
            required = (
                root / "Lib" / selected,
                root / "Licenses" / selected / "sdk_license.rtf",
            )
            missing = [str(path) for path in required if not path.exists()]
            if missing:
                diagnostics.append(
                    f"{root} version {selected}: missing "
                    + ", ".join(missing)
                )
                continue
            matches.append((selected, root))
    if matches:
        selected_text = select_latest_sdk_version(
            (version for version, _ in matches), minimum
        )
        assert selected_text is not None
        selected_root = next(
            root for version, root in matches if version == selected_text
        )
        return selected_root, selected_text
    raise RuntimeError(
        f"No installed Windows SDK is at least {minimum}. Checked: "
        + "; ".join(diagnostics)
    )


def find_pinned_windows_sdk(
    lock: dict[str, object], sdk_root: Path | None = None
) -> Path:
    return find_latest_windows_sdk(lock, sdk_root)[0]


def d3dcompiler_notice(lock: dict[str, object], architecture: str) -> str:
    sdk = lock["windows_sdk"]
    assert isinstance(sdk, dict)
    configuration = sdk["d3dcompiler_redistributable"]
    assert isinstance(configuration, dict)
    source = configuration["path_class"].replace(
        "<architecture>", architecture
    )
    return (
        "Microsoft Windows SDK Direct3D Compiler Redistributable\n"
        f"Minimum SDK version: {sdk['minimum_version']}\n"
        "Selection: latest installed semantic version at build time\n"
        f"SDK source class: {source}\n"
        "Distributed under the Microsoft Windows SDK redistributable terms.\n"
        f"Terms: {configuration['license_terms_url']}\n"
    )


def find_d3dcompiler(
    lock: dict[str, object],
    architecture: str,
    sdk_root: Path | None = None,
) -> tuple[Path, dict[str, object]]:
    sdk = lock["windows_sdk"]
    assert isinstance(sdk, dict)
    configuration = sdk["d3dcompiler_redistributable"]
    assert isinstance(configuration, dict)
    root, selected_version = find_latest_windows_sdk(lock, sdk_root)
    path_class = configuration["path_class"].replace(
        "<architecture>", architecture
    )
    candidate = root / "Redist" / "D3D" / architecture / "d3dcompiler_47.dll"
    if not candidate.is_file():
        raise RuntimeError(
            f"Pinned Windows SDK d3dcompiler is missing: {candidate}"
        )
    info = inspect_pe(candidate)
    actual_hash = sha256(candidate)
    actual_size = candidate.stat().st_size
    expected_machine = lock["architectures"][architecture]["pe_machine"]
    errors: list[str] = []
    if info["machine"].lower() != str(expected_machine).lower():
        errors.append(f"machine expected {expected_machine}, got {info['machine']}")
    if errors:
        raise RuntimeError(
            f"Windows SDK redistributable mismatch at {candidate}: "
            + "; ".join(errors)
        )
    license_path = (
        root / "Licenses" / selected_version / "sdk_license.rtf"
    )
    return candidate, {
        "sdk_version": selected_version,
        "minimum_sdk_version": sdk["minimum_version"],
        "path_class": path_class,
        "resolved_source": str(candidate),
        "license_path_class": configuration["license_path_class"].replace(
            "<selected-version>", selected_version
        ),
        "license_size": license_path.stat().st_size,
        "license_sha256": sha256(license_path),
        "license_terms_url": configuration["license_terms_url"],
        "size": actual_size,
        "sha256": actual_hash,
        "pe": info,
    }


def find_output(out: Path, name: str) -> Path:
    direct = out / name
    if direct.is_file():
        return direct
    matches = [
        path
        for path in out.rglob(name)
        if path.is_file()
        and not any(
            part in {"obj", "gen"} for part in path.relative_to(out).parts
        )
    ]
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches) or "none"
        raise RuntimeError(f"Expected exactly one output {name}; found {rendered}")
    return matches[0]


def copy_required(out: Path, destination: Path, names: Iterable[str]) -> dict[str, str]:
    copied: dict[str, str] = {}
    for name in names:
        source = find_output(out, name)
        target = destination / name
        shutil.copy2(source, target)
        copied[name] = str(source)
    return copied


def collect(args: argparse.Namespace) -> None:
    lock = load_lock()
    architecture = validate_architecture(args.architecture, lock)
    out = output_dir(architecture)
    source = angle_source()
    if not (out / "build-report.json").exists():
        raise RuntimeError(f"Missing successful build report in {out}")
    if not source.exists():
        raise RuntimeError("ANGLE source checkout is missing")

    staging = staging_dir(architecture)
    print(f"[1/5] Reset staging directory {staging}", flush=True)
    reset_directory(staging)
    include = staging / "include"
    lib = staging / "lib"
    licenses = staging / "LICENSES"
    include.mkdir()
    lib.mkdir()
    licenses.mkdir()

    print("[2/5] Copy multi-backend runtime DLLs and import libraries", flush=True)
    copied = copy_required(out, lib, ANGLE_RUNTIME)
    d3dcompiler_source, d3dcompiler_provenance = find_d3dcompiler(
        lock, architecture
    )
    shutil.copy2(d3dcompiler_source, lib / "d3dcompiler_47.dll")
    copied["d3dcompiler_47.dll"] = str(d3dcompiler_source)
    for destination_name, build_name in BUILD_LIBS.items():
        source_path = find_output(out, build_name)
        shutil.copy2(source_path, lib / destination_name)
        copied[destination_name] = str(source_path)

    print("[3/5] Inspect core PE imports and resolve conditional runtimes", flush=True)
    imported: set[str] = set()
    while True:
        imported = {
            imported_name.lower()
            for path in lib.glob("*.dll")
            for imported_name in inspect_pe(path)["runtime_dependencies"]
        }
        added = False
        for name in CONDITIONAL_RUNTIME:
            if name.lower() in imported and not (lib / name).is_file():
                source_path = find_output(out, name)
                copied[name] = str(source_path)
                shutil.copy2(source_path, lib / name)
                added = True
        if not added:
            break

    print("[4/5] Copy exact pinned headers and dependency licenses", flush=True)
    for directory in HEADER_DIRECTORIES:
        header_source = source / "include" / directory
        if not header_source.is_dir():
            raise RuntimeError(
                f"Required ANGLE header directory is missing: {header_source}"
            )
        shutil.copytree(header_source, include / directory)

    copied_licenses: dict[str, str] = {}
    for output_name, candidates in LICENSE_SOURCES.items():
        selected: Path | None = None
        for candidate in candidates:
            path = source.joinpath(*candidate)
            if path.is_file():
                selected = path
                break
        if selected:
            shutil.copy2(selected, licenses / output_name)
            copied_licenses[output_name] = str(selected)
    for mandatory in ("ANGLE.txt", "Vulkan-Loader.txt"):
        if mandatory not in copied_licenses:
            raise RuntimeError(f"Mandatory license source was not found: {mandatory}")
    sdk_notice = licenses / "Microsoft-Windows-SDK-D3DCompiler.txt"
    sdk_notice.write_text(
        d3dcompiler_notice(lock, architecture),
        encoding="utf-8",
        newline="\n",
    )
    copied_licenses[sdk_notice.name] = "generated from config/angle.lock.json"
    sdk_root = find_pinned_windows_sdk(lock)
    sdk_license = (
        sdk_root
        / "Licenses"
        / str(d3dcompiler_provenance["sdk_version"])
        / "sdk_license.rtf"
    )
    if sha256(sdk_license) != d3dcompiler_provenance["license_sha256"]:
        raise RuntimeError(
            "Windows SDK license SHA-256 differs from collected provenance"
        )
    sdk_license_destination = licenses / "Microsoft-Windows-SDK-License.rtf"
    shutil.copy2(sdk_license, sdk_license_destination)
    copied_licenses[sdk_license_destination.name] = str(sdk_license)

    print("[5/5] Record collection sources and runtime decisions", flush=True)
    write_json(
        staging / "collect-report.json",
        {
            "architecture": architecture,
            "source_output": str(out),
            "files": copied,
            "licenses": copied_licenses,
            "conditional_runtime_decisions": {
                name: {
                    "imported_by_core": name.lower() in imported,
                    "included": (lib / name).is_file(),
                }
                for name in CONDITIONAL_RUNTIME
            },
            "runtime_decisions": {
                "d3dcompiler_47.dll": (
                    "packaged from the architecture-matched Windows SDK "
                    f"{d3dcompiler_provenance['sdk_version']} D3D "
                    "redistributable selected as the latest installed SDK "
                    f">= {lock['windows_sdk']['minimum_version']}"
                ),
                "vulkan_loader": (
                    "vulkan-1.dll packaged because the compiled hardware Vulkan "
                    "backend dynamically loads this architecture-matched loader"
                ),
                "swiftshader": "not built or packaged",
                "zlib.dll": "not built, imported, or packaged",
            },
            "d3dcompiler_provenance": d3dcompiler_provenance,
        },
    )

    print(f"Artifacts collected: {staging}")
