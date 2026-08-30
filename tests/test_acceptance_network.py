"""Reads the published repository the way a consumer would.

Nothing else verifies that what was published is legible from outside. The
``configs:`` block the card writes by hand is otherwise only checked for shape:
if the glob is wrong, the viewer of the Hub shows nothing and the unit suite
still passes.

``datasets`` is what consumers actually use, so verifying with it verifies the
real contract. It is a dev dependency for this file alone -- see PLAN.md,
"Avaliação: a biblioteca datasets simplifica isto?" for why it is not a runtime
dependency.

Run after a --push against a throwaway repo:

    uv run pytest -m network
"""

from __future__ import annotations

import os

import pytest

from br_publisher.domain.recipe import DEFAULT_REPO_ID

REPO_ID = os.environ.get("BRINSS_PUBLISH_TEST_REPO", DEFAULT_REPO_ID)
FAMILY = os.environ.get("BRINSS_PUBLISH_TEST_FAMILY", "perfil_unidades")


@pytest.mark.network
def test_the_hub_can_read_what_we_published():
    datasets = pytest.importorskip("datasets")

    dataset = datasets.load_dataset(REPO_ID, name=FAMILY, split="train", streaming=True)
    row = next(iter(dataset))

    # The two defects the conversion exists to prevent, seen from outside:
    # a pandas Period stored as the month ordinal 653 instead of "2024-06",
    # and type inference eating the leading zeros of CID/CBO/CNAE codes.
    assert isinstance(row["periodo_referencia"], str)
    assert len(row["periodo_referencia"]) == 7 and row["periodo_referencia"][4] == "-"
    assert all(isinstance(value, (str, type(None))) for value in row.values())


@pytest.mark.network
def test_every_published_family_is_a_readable_config():
    datasets = pytest.importorskip("datasets")

    configs = datasets.get_dataset_config_names(REPO_ID)
    assert configs, "o card nao declara nenhuma config"
    for config in configs:
        # A config whose glob matches nothing is a broken entry in the viewer.
        splits = datasets.get_dataset_split_names(REPO_ID, config_name=config)
        assert "train" in splits, f"config {config} nao expoe o split train"
