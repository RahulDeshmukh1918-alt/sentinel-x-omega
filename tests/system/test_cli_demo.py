"""The command-line demo runs the whole pipeline without a database or web server."""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.system
ROOT = Path(__file__).resolve().parents[2]


def test_run_demo_no_db(sample_video):
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_demo.py"), "--video", str(sample_video), "--no-db"],
        capture_output=True, text=True, timeout=180, cwd=ROOT,
    )
    assert res.returncode == 0, res.stderr
    assert "DEMO MODE" in res.stdout
    assert "Incidents created: 1" in res.stdout
    assert "Fire Brigade" in res.stdout


def test_run_demo_reports_missing_video(tmp_path):
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_demo.py"), "--video", str(tmp_path / "nope.mp4"), "--no-db"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
    )
    assert res.returncode == 2
    assert "SOURCE_NOT_FOUND" in res.stdout + res.stderr
