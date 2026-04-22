"""M5 — priority-ECLI curated-list ingest."""
import pytest

from jurist.ingest.priority_eclis import load_eclis


def test_load_eclis_parses_text_file(tmp_path):
    p = tmp_path / "huurrecht.txt"
    p.write_text("ECLI:NL:HR:2024:1761\n# a comment\n\nECLI:NL:HR:2024:1763\n")
    eclis = load_eclis(p)
    assert eclis == ["ECLI:NL:HR:2024:1761", "ECLI:NL:HR:2024:1763"]


def test_load_eclis_rejects_invalid_lines(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("not-an-ecli\nECLI:NL:HR:2024:1761\n")
    with pytest.raises(ValueError, match="invalid ECLI"):
        load_eclis(p)
