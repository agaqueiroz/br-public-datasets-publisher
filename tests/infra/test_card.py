from __future__ import annotations

from br_publisher.infra.card import DatasetCardRenderer

from ..conftest import FAMILIES


def test_the_card_declares_one_viewer_config_per_family():
    # Without the configs block the Hub cannot tell eight unrelated datasets
    # apart and the preview shows nothing.
    keys = ["beneficios_concedidos", "perfil_unidades"]
    card = DatasetCardRenderer(families=FAMILIES).render(keys)
    lines = card.splitlines()

    assert lines[0] == "---"
    assert lines[1] == "configs:"
    assert [line for line in lines if line.startswith("- config_name: ")] == [
        "- config_name: beneficios_concedidos",
        "- config_name: perfil_unidades",
    ]
    for key in keys:
        assert f"    path: data/{key}/*.parquet" in lines


def test_the_yaml_block_is_closed_before_the_prose():
    card = DatasetCardRenderer(families=FAMILIES).render(["perfil_unidades"])
    lines = card.splitlines()
    assert lines.index("---", 1) < lines.index("# Datasets abertos do INSS, em Parquet")


def test_each_family_gets_a_titled_table_row():
    card = DatasetCardRenderer(families=FAMILIES).render(["perfil_unidades"])
    assert f"| `perfil_unidades` | {FAMILIES['perfil_unidades'].title} |" in card


def test_an_unknown_family_falls_back_to_its_key():
    card = DatasetCardRenderer(families={}).render(["perfil_unidades"])
    assert "| `perfil_unidades` | perfil_unidades |" in card


def test_a_partial_rollout_advertises_only_what_it_reached():
    card = DatasetCardRenderer(families=FAMILIES).render(["perfil_unidades"])
    assert "config_name: beneficios_concedidos" not in card
