from __future__ import annotations

from br_publisher.domain.deciders import ManifestDecider, SampleDecider
from br_publisher.domain.manifest import (
    REASON_FORCED,
    REASON_NEW,
    REASON_RECIPE_CHANGED,
    REASON_SAMPLE,
    REASON_SOURCE_CHANGED,
    REASON_UNCHANGED,
    Manifest,
    ManifestEntry,
)
from br_publisher.domain.recipe import CONVERSION_RECIPE


def _manifest(**overrides) -> Manifest:
    entry = ManifestEntry(
        source_sha256=overrides.pop("source_sha256", "sha256:abc"),
        source_url="https://fixtures.test/res.csv",
        resource_id="res-2024-06",
        conversion=overrides.pop("conversion", CONVERSION_RECIPE),
        **overrides,
    )
    return Manifest({"beneficios_concedidos/2024-06": entry})


def _decider(manifest: Manifest, *, force: bool = False) -> ManifestDecider:
    return ManifestDecider(manifest=manifest, recipe=CONVERSION_RECIPE, force=force)


def test_a_period_absent_from_the_manifest_is_new():
    decision = _decider(_manifest()).decide("beneficios_concedidos", "2024-07", "sha256:abc", reusable=False)
    assert decision.upload is True
    assert decision.reason == REASON_NEW


def test_an_unchanged_source_hash_is_skipped():
    decision = _decider(_manifest()).decide("beneficios_concedidos", "2024-06", "sha256:abc", reusable=True)
    assert decision.upload is False
    assert decision.reason == REASON_UNCHANGED


def test_the_portal_replacing_the_file_forces_a_rebuild():
    decision = _decider(_manifest()).decide("beneficios_concedidos", "2024-06", "sha256:zzz", reusable=False)
    assert decision.upload is True
    assert decision.reason == REASON_SOURCE_CHANGED


def test_a_recipe_bump_forces_a_rebuild():
    manifest = _manifest(conversion="v0|antigo")
    decision = _decider(manifest).decide("beneficios_concedidos", "2024-06", "sha256:abc", reusable=True)
    assert decision.upload is True
    assert decision.reason == REASON_RECIPE_CHANGED


def test_force_overrides_an_unchanged_month():
    decision = _decider(_manifest(), force=True).decide(
        "beneficios_concedidos", "2024-06", "sha256:abc", reusable=True
    )
    assert decision.upload is True
    assert decision.reason == REASON_FORCED


def test_families_that_share_a_period_are_isolated():
    # The manifest key carries the family, so one family's 2024-06 says nothing
    # about another's.
    decision = _decider(_manifest()).decide("perfil_unidades", "2024-06", "sha256:abc", reusable=False)
    assert decision.upload is True
    assert decision.reason == REASON_NEW


def test_sample_decider_skips_what_the_build_cache_already_has():
    decision = SampleDecider().decide("perfil_unidades", "2024-06", "sha256:abc", reusable=True)
    assert decision.upload is False
    assert decision.reason == REASON_UNCHANGED


def test_sample_decider_converts_anything_not_cached():
    decision = SampleDecider().decide("perfil_unidades", "2024-06", "sha256:abc", reusable=False)
    assert decision.upload is True
    assert decision.reason == REASON_SAMPLE


def test_sample_decider_redoes_a_month_when_forced():
    decision = SampleDecider(force=True).decide("perfil_unidades", "2024-06", "sha256:abc", reusable=True)
    assert decision.upload is True
    assert decision.reason == REASON_SAMPLE
