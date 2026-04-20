from pathlib import Path
from unittest.mock import patch

import pytest

from jurist.config import Settings
from jurist.fakes import FAKE_ANSWER, FAKE_VISIT_PATH
from jurist.ingest.statutes import run_ingest

FIXTURES = Path(__file__).parents[1] / "ingest" / "fixtures"


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("jurist.ingest.statutes.settings", Settings(data_dir=data))
    monkeypatch.setattr("jurist.ingest.fetch.CACHE_DIR", data / "cache" / "bwb")
    return data


def _fake_fetch(bwb_id: str, **_kw) -> bytes:
    return (FIXTURES / f"{bwb_id}_excerpt.xml").read_bytes()


def test_fake_visit_path_ids_exist_in_real_kg(isolated_data):
    with patch("jurist.ingest.statutes.fetch_bwb_xml", side_effect=_fake_fetch):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
    node_ids = {n.article_id for n in snap.nodes}
    missing = [aid for aid in FAKE_VISIT_PATH if aid not in node_ids]
    assert not missing, f"FAKE_VISIT_PATH drift: missing {missing} in real KG"


def test_fake_answer_citations_resolve_to_real_kg(isolated_data):
    with patch("jurist.ingest.statutes.fetch_bwb_xml", side_effect=_fake_fetch):
        snap = run_ingest(refresh=False, no_fetch=False, bwb_ids=None, limit=None)
    labels = {n.label for n in snap.nodes}
    for cit in FAKE_ANSWER.relevante_wetsartikelen:
        assert cit.article_label in labels, (
            f"FAKE_ANSWER citation drift: {cit.article_label!r} not among real labels"
        )
