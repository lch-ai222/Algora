from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_project_builds_offline_and_wheel_contains_cli_entrypoint(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(tmp_path),
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(tmp_path.glob("mini_store_long-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert "mini_store/cli.py" in names
        assert "mini_store/diagnostics.py" in names
        assert "mini_store/output.py" in names
        assert "mini_store/version.py" in names
        entry_points = next(name for name in names if name.endswith("entry_points.txt"))
        assert "mini-store = mini_store.cli:main" in wheel.read(entry_points).decode()
        metadata = next(name for name in names if name.endswith("METADATA"))
        metadata_text = wheel.read(metadata).decode()
        assert "Name: mini-store-long" in metadata_text
        assert "Version: 0.2.0" in metadata_text
