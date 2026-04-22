"""M5 — CLI flags for priority + refilter-cache ingest modes."""
import subprocess
import sys


def test_caselaw_help_mentions_m5_flags():
    result = subprocess.run(
        [sys.executable, "-m", "jurist.ingest.caselaw", "--help"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--priority-eclis" in result.stdout
    assert "--refilter-cache" in result.stdout


def test_caselaw_priority_eclis_requires_existing_file(tmp_path):
    missing = tmp_path / "nope.txt"
    result = subprocess.run(
        [sys.executable, "-m", "jurist.ingest.caselaw",
         "--priority-eclis", str(missing)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()
