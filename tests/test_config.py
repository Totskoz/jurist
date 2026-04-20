from pathlib import Path

from jurist.config import settings


def test_kg_path_defaults_under_data_dir():
    assert settings.kg_path.parts[-2:] == ("kg", "huurrecht.json")
    assert isinstance(settings.kg_path, Path)
