import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jurist.kg.networkx_kg import NetworkXKG


def _sample_snapshot_json() -> str:
    return json.dumps({
        "generated_at": "2026-04-20T10:00:00Z",
        "source_versions": {"BWBR0005290": "2024-01-01"},
        "nodes": [
            {
                "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                "bwb_id": "BWBR0005290",
                "label": "Boek 7, Artikel 248",
                "title": "Huurverhoging",
                "body_text": "De verhuurder kan ...",
                "outgoing_refs": ["BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249"],
            },
            {
                "article_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
                "bwb_id": "BWBR0005290",
                "label": "Boek 7, Artikel 249",
                "title": "Voorstel",
                "body_text": "Een voorstel tot huurverhoging ...",
                "outgoing_refs": [],
            },
        ],
        "edges": [
            {
                "from_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248",
                "to_id": "BWBR0005290/Boek7/Titel4/Afdeling5/Artikel249",
                "kind": "explicit",
                "context": None,
            }
        ],
    })


def test_load_from_json_roundtrip(tmp_path: Path):
    path = tmp_path / "kg.json"
    path.write_text(_sample_snapshot_json(), encoding="utf-8")
    kg = NetworkXKG.load_from_json(path)
    assert len(kg.all_nodes()) == 2
    assert len(kg.all_edges()) == 1


def test_get_node_known_and_unknown(tmp_path: Path):
    path = tmp_path / "kg.json"
    path.write_text(_sample_snapshot_json(), encoding="utf-8")
    kg = NetworkXKG.load_from_json(path)
    node = kg.get_node("BWBR0005290/Boek7/Titel4/Afdeling5/Artikel248")
    assert node is not None
    assert node.label == "Boek 7, Artikel 248"
    assert kg.get_node("does/not/exist") is None


def test_missing_file_raises_filenotfound(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        NetworkXKG.load_from_json(tmp_path / "nope.json")


def test_malformed_json_raises_validation_error(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{\"nodes\": []}", encoding="utf-8")  # missing required
    with pytest.raises(ValidationError):
        NetworkXKG.load_from_json(path)


def test_duplicate_node_id_raises_value_error(tmp_path: Path):
    snap = json.loads(_sample_snapshot_json())
    snap["nodes"].append(snap["nodes"][0])  # duplicate
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        NetworkXKG.load_from_json(path)
