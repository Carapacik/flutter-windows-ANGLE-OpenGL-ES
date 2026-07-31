from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "windows"))

from angle_tools.collect_artifacts import (
    REQUIRED_LIBS,
    find_d3dcompiler,
    find_pinned_windows_sdk,
    select_latest_sdk_version,
)
from angle_tools.angle_build import apply_linker_reproducibility_override
from angle_tools.common import archive_name, contains_absolute_windows_path
from angle_tools.package_artifacts import sanitize_manifest_metadata


class PinnedD3DCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = json.loads(
            (REPO_ROOT / "config" / "angle.lock.json").read_text(
                encoding="utf-8"
            )
        )

    def test_semantic_latest_accepts_newer_sdk_families(self) -> None:
        selected = select_latest_sdk_version(
            (
                "10.0.26100.9999",
                "10.0.28000.9",
                "10.0.28000.12",
                "10.0.29000.0",
            ),
            "10.0.28000.0",
        )
        self.assertEqual(
            selected,
            "10.0.29000.0",
        )

    def test_release_uses_7z_and_upstream_import_library_names(self) -> None:
        self.assertEqual(
            archive_name(self.lock, "x64"),
            "ANGLE-2c5c60cd270d-windows-x64.7z",
        )
        self.assertEqual(
            REQUIRED_LIBS,
            ("libEGL.dll.lib", "libGLESv2.dll.lib"),
        )

    def test_sdk_below_minimum_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, "No installed Windows SDK is at least"
        ):
            find_pinned_windows_sdk(
                self.lock, sdk_root=Path(r"Z:\missing-windows-sdk")
            )

    def test_wrong_architecture_sdk_redistributable_is_rejected(self) -> None:
        with patch(
            "angle_tools.collect_artifacts.inspect_pe",
            return_value={"machine": "0xaa64"},
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Windows SDK redistributable mismatch"
            ):
                find_d3dcompiler(self.lock, "x64")

    def test_manifest_removes_ephemeral_runner_identity(self) -> None:
        sanitized = sanitize_manifest_metadata(
            {
                "runner_name": "GitHub Actions 1000000000",
                "runner_image": {"label": "windows-2025"},
            }
        )
        self.assertEqual(
            sanitized,
            {"runner_image": {"label": "windows-2025"}},
        )

    def test_linker_reproducibility_override_is_guarded_and_idempotent(
        self,
    ) -> None:
        configuration = self.lock["windows_sdk"][
            "angle_linker_reproducibility_override"
        ]
        state = {"content": configuration["upstream"] + "\n"}

        def read_text(_: Path, **__: object) -> str:
            return state["content"]

        def write_text(_: Path, content: str, **__: object) -> int:
            state["content"] = content
            return len(content)

        with (
            patch.object(Path, "read_text", read_text),
            patch.object(Path, "write_text", write_text),
        ):
            source = Path("synthetic-angle-source")
            first = apply_linker_reproducibility_override(self.lock, source)
            second = apply_linker_reproducibility_override(self.lock, source)
            self.assertTrue(first["applied"])
            self.assertEqual(first, second)
            self.assertEqual(
                state["content"].strip(),
                configuration["replacement"],
            )

    def test_linker_reproducibility_override_rejects_unknown_upstream(
        self,
    ) -> None:
        with patch.object(Path, "read_text", return_value="ldflags = []\n"):
            source = Path("synthetic-angle-source")
            with self.assertRaisesRegex(
                RuntimeError, "Cannot apply deterministic linker override"
            ):
                apply_linker_reproducibility_override(self.lock, source)

    def test_absolute_path_check_ignores_linker_option_syntax(self) -> None:
        self.assertFalse(
            contains_absolute_windows_path(
                {"upstream": 'ldflags += [ "/TIMESTAMP:" + build_timestamp ]'}
            )
        )
        self.assertTrue(
            contains_absolute_windows_path(
                {"source": r"C:\Windows Kits\10\Redist"}
            )
        )
        self.assertFalse(
            contains_absolute_windows_path(
                {
                    "repository": "https://github.com/google/angle.git",
                    "license": "https://go.microsoft.com/fwlink/",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
