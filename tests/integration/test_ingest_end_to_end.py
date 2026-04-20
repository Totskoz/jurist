import json  # noqa: F401 — kept for symmetry with other integration tests
from pathlib import Path
from unittest.mock import patch

import pytest

from jurist.config import Settings
from jurist.ingest.allowlist import BWB_ALLOWLIST
from jurist.ingest.statutes import run_ingest
from jurist.schemas import KGSnapshot

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"


def _fixture_bytes_for(bwb_id: str) -> bytes:
    return (FIXTURES / f"{bwb_id}_excerpt.xml").read_bytes()


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings", Settings(data_dir=data))
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data / "cache" / "bwb")
    return data


def _fake_fetch(bwb_id: str, **_kw) -> bytes:
    return _fixture_bytes_for(bwb_id)


def test_end_to_end_ingest_on_fixtures(isolated_data, monkeypatch):
    with patch("jurist.ingest.statutes.fetch_bwb_xml", side_effect=_fake_fetch):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)

    assert isinstance(snap, KGSnapshot)
    out_path = isolated_data / "kg" / "huurrecht.json"
    assert out_path.exists()

    parsed = KGSnapshot.model_validate_json(out_path.read_text(encoding="utf-8"))
    assert set(parsed.source_versions.keys()) == set(BWB_ALLOWLIST.keys())
    assert len(parsed.nodes) > 0
    # Article dumps written for each node
    for n in parsed.nodes[:5]:
        flat = n.article_id.split("/", 1)[1].replace("/", "-")
        dump = isolated_data / "articles" / n.bwb_id / f"{flat}.md"
        assert dump.exists(), f"missing dump for {n.article_id}"
        content = dump.read_text(encoding="utf-8")
        assert n.label in content
        assert n.body_text in content
