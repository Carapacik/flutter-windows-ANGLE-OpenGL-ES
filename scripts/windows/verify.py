"""Practical PE, staging, install, and ANGLE backend smoke checks."""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

from common import (DLLS, HEADERS, LIBS, ROOT, RUNTIME_FILES, WORK,
                    architecture, copy_file, environment, executable, staging)

MACHINES = {"x64": 0x8664, "arm64": 0xAA64}
BACKENDS = ("d3d11", "d3d11-9_3", "warp", "desktop-gl", "native-gles",
            "vulkan", "swiftshader")
RUNNER_DEPENDENT = {"desktop-gl", "native-gles", "vulkan"}


def pe_machine(path: Path) -> int:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError(f"Not a PE file: {path}")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError(f"Invalid PE header: {path}")
        return struct.unpack("<H", stream.read(2))[0]


def dumpbin_path() -> Path | None:
    root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Visual Studio"
    found = sorted(root.glob("*/*/VC/Tools/MSVC/*/bin/Hostx64/x64/dumpbin.exe"), reverse=True)
    return found[0] if found else None


def verify(arch: str, *, install: bool = False, stage: Path | None = None) -> None:
    arch = architecture(arch)
    stage = stage or staging(arch)
    for name in DLLS:
        path = stage / "lib" / name
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing runtime: {path}")
        machine = pe_machine(path)
        if machine != MACHINES[arch]:
            raise RuntimeError(f"{path}: PE machine {machine:#x}, expected {MACHINES[arch]:#x}")
    for name in LIBS:
        if not (stage / "lib" / name).is_file():
            raise RuntimeError(f"Missing import library: {name}")
    for name in HEADERS:
        if not (stage / "include" / name).is_dir():
            raise RuntimeError(f"Missing header directory: {name}")
    icd = stage / "lib" / "vk_swiftshader_icd.json"
    if not icd.is_file() or "vk_swiftshader.dll" not in icd.read_text(encoding="utf-8"):
        raise RuntimeError(f"Missing or invalid SwiftShader ICD manifest: {icd}")
    for forbidden in ("ucrtbased.dll", "vcruntime140d.dll"):
        if (stage / "lib" / forbidden).exists():
            raise RuntimeError(f"Debug runtime in staging: {forbidden}")
    dumpbin = dumpbin_path()
    if dumpbin:
        for name in LIBS:
            result = subprocess.run([str(dumpbin), "/headers",
                                     str(stage / "lib" / name)],
                                    capture_output=True, text=True, check=True)
            expected = f"{MACHINES[arch]:04X} machine"
            if expected.lower() not in result.stdout.lower():
                raise RuntimeError(f"Wrong-architecture import library: {name}")
        for name in ("libEGL.dll", "libGLESv2.dll"):
            result = subprocess.run([str(dumpbin), "/dependents", str(stage / "lib" / name)],
                                    capture_output=True, text=True, check=True)
            if re.search(r"\b(?:ucrtbased|vcruntime\d+d|msvcp\d+d)\.dll\b", result.stdout, re.I):
                raise RuntimeError(f"Debug CRT import in {name}")
    print(f"Verified {arch} PE machines, runtime set, libraries, and headers")
    if install:
        destination = ROOT / "windows" / "bin" / arch
        for name in RUNTIME_FILES:
            copy_file(stage / "lib" / name, destination / "dll" / name)
        for name in LIBS:
            copy_file(stage / "lib" / name, destination / "lib" / name)
        includes = ROOT / "windows" / "include" / "external"
        for name in HEADERS:
            target = includes / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(stage / "include" / name, target)
        print(f"Installed {arch} into windows/bin and shared headers")


def cmake_path() -> str:
    try:
        return executable("cmake.exe", "cmake")
    except FileNotFoundError:
        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft Visual Studio"
        found = sorted(root.glob("*/*/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"), reverse=True)
        if not found:
            raise
        return str(found[0])


def verify_example(arch: str) -> None:
    arch = architecture(arch)
    bundle = ROOT / "example" / "build" / "windows" / arch / "runner" / "Release"
    names = ("flutter_windows_angle_opengl_es_example.exe",
             "flutter_windows_angle_opengl_es_plugin.dll", "flutter_windows.dll",
             *DLLS)
    for name in names:
        path = bundle / name
        if not path.is_file() or pe_machine(path) != MACHINES[arch]:
            raise RuntimeError(f"Missing or wrong-architecture example binary: {path}")
    if not (bundle / "vk_swiftshader_icd.json").is_file():
        raise RuntimeError(f"Missing SwiftShader ICD manifest: {bundle}")
    print(f"Verified {arch} Flutter example bundle and all native DLLs")


def smoke(arch: str, *, stage: Path | None = None,
          backend: str | None = None) -> Path:
    arch = architecture(arch)
    stage = stage or staging(arch)
    verify(arch, stage=stage)
    cmake = cmake_path()
    build_dir = WORK / "smoke" / arch
    platform = "x64" if arch == "x64" else "ARM64"
    subprocess.run([cmake, "-S", str(ROOT / "tests" / "native"), "-B", str(build_dir),
                    "-A", platform, f"-DANGLE_ROOT={stage}"], env=environment(), check=True)
    subprocess.run([cmake, "--build", str(build_dir), "--config", "Release"], env=environment(), check=True)
    exe = build_dir / "Release" / "angle_smoke_test.exe"
    if not exe.is_file():
        raise FileNotFoundError(exe)
    if pe_machine(exe) != MACHINES[arch]:
        raise RuntimeError(f"Smoke executable has the wrong PE architecture: {exe}")
    host = os.environ.get("PROCESSOR_ARCHITECTURE", "").lower()
    if arch == "arm64" and host not in ("arm64", "aarch64"):
        print("ARM64 smoke executable built; run it on a native ARM64 host")
        return exe
    env = environment()
    env["Path"] = str(stage / "lib") + os.pathsep + env["Path"]
    selected = (backend,) if backend else BACKENDS
    for name in selected:
        result = subprocess.run([str(exe), name], cwd=stage, env=env)
        if result.returncode == 2 and name in RUNNER_DEPENDENT:
            print(f"{name}: runner unavailable; build remains verified")
            continue
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode,
                                                [str(exe), name])
    print(f"ANGLE backend smoke matrix passed on {arch}")
    return exe
