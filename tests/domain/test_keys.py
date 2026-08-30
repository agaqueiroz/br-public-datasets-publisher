from __future__ import annotations

import pytest

from br_publisher.domain.keys import manifest_key, parse_repo_path, path_in_repo, split_key

from ..conftest import FAMILY_KEYS


def test_path_in_repo_is_one_file_per_period():
    assert path_in_repo("perfil_unidades", "2024-06") == "data/perfil_unidades/2024-06.parquet"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("data/perfil_unidades/2024-06.parquet", ("perfil_unidades", "2024-06")),
        ("manifest.json", None),
        ("data/README.md", None),
        ("data/familia_inexistente/2024-06.parquet", None),
    ],
)
def test_parse_repo_path_round_trips_path_in_repo(path, expected):
    assert parse_repo_path(path, FAMILY_KEYS) == expected


def test_manifest_key_and_split_key_are_inverses():
    key = manifest_key("perfil_unidades", "2024-06")
    assert key == "perfil_unidades/2024-06"
    assert split_key(key) == ("perfil_unidades", "2024-06")
