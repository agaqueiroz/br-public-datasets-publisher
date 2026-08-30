from __future__ import annotations

from pathlib import Path

import pytest

from br_publisher.errors import UsageError
from br_publisher.settings import Mode, ModeProfile, Settings, normalize_periods

from .conftest import FAMILY_KEYS, make_settings


@pytest.mark.parametrize(
    "given, expected",
    [
        (["2024-6"], ("2024-06",)),
        (["2024-06"], ("2024-06",)),
        (None, None),
        ([], None),
    ],
)
def test_normalize_periods_accepts_and_pads(given, expected):
    # Round-tripping through pd.Period repairs the usual "2024-6" typo, which
    # would otherwise match no catalogue entry and leave the run looking like a
    # legitimate "nothing to do".
    assert normalize_periods(given) == expected


@pytest.mark.parametrize("given", ["lixo", "2024-13", ""])
def test_normalize_periods_rejects_garbage(given):
    with pytest.raises(UsageError, match="periodo invalido"):
        normalize_periods([given])


def test_no_hub_with_push_is_rejected():
    with pytest.raises(UsageError, match="incompativeis"):
        make_settings(no_hub=True, push=True)


def test_sample_with_push_is_rejected():
    with pytest.raises(UsageError, match="incompativeis"):
        make_settings(sample=True, push=True)


@pytest.mark.parametrize("flag", ["reconciliar", "prune_parquet"])
@pytest.mark.parametrize("offline", ["sample", "no_hub"])
def test_hub_only_flags_are_rejected_offline(flag, offline):
    with pytest.raises(UsageError, match="precisa consultar o Hub"):
        make_settings(**{flag: True, offline: True})


@pytest.mark.parametrize(
    "flags, mode",
    [
        ({}, Mode.DRY_RUN),
        ({"sample": True}, Mode.SAMPLE),
        ({"push": True}, Mode.PUSH),
    ],
)
def test_the_mode_comes_from_the_flags(flags, mode):
    assert make_settings(**flags).mode is mode


@pytest.mark.parametrize(
    "mode, no_hub, may_download, may_convert, may_publish, uses_hub",
    [
        (Mode.DRY_RUN, False, False, False, False, True),
        (Mode.DRY_RUN, True, False, False, False, False),
        (Mode.SAMPLE, False, False, True, False, False),
        (Mode.PUSH, False, True, True, True, True),
    ],
)
def test_mode_profile_matrix(mode, no_hub, may_download, may_convert, may_publish, uses_hub):
    # One table replacing the six scattered `if args.sample` sites that each had
    # to remember what the flag implied.
    profile = ModeProfile.of(mode, no_hub=no_hub)
    assert (profile.may_download, profile.may_convert, profile.may_publish, profile.uses_hub) == (
        may_download,
        may_convert,
        may_publish,
        uses_hub,
    )


def test_sample_never_downloads():
    # That is the whole reason --sample exists: a full run pulls tens of GB.
    assert ModeProfile.of(Mode.SAMPLE).may_download is False


def test_the_header_label_names_reconciliation():
    profile = ModeProfile.of(Mode.PUSH)
    assert profile.header_label(reconcile=False) == "push"
    assert profile.header_label(reconcile=True) == "push+reconciliar"


def test_defaults_are_carried_over_from_the_parser():
    settings = make_settings()
    assert settings.repo_id == "agaqueiroz/brinss-public-datasets"
    assert settings.families == FAMILY_KEYS
    assert settings.periods is None
    assert settings.commit_size == 25
    assert settings.cache_dir is None
    assert settings.parquet_dir == Path("tmp")


def test_an_explicit_family_narrows_the_run():
    settings = make_settings(familia=["perfil_unidades"])
    assert settings.families == ("perfil_unidades",)


def test_the_log_file_wins_over_the_log_dir(tmp_path):
    settings = make_settings(
        argv=[], log_file=str(tmp_path / "exato.log"), log_dir=str(tmp_path / "ignorado")
    )
    assert settings.log.resolve_path() == tmp_path / "exato.log"


def test_no_log_file_resolves_to_nothing():
    assert make_settings().log.resolve_path() is None


def test_the_default_log_name_is_timestamped(tmp_path):
    settings = make_settings(argv=[], log_dir=str(tmp_path))
    path = settings.log.resolve_path()
    assert path.parent == tmp_path
    assert path.name.startswith("publish-") and path.name.endswith(".log")


def test_settings_are_frozen():
    settings = make_settings()
    with pytest.raises((AttributeError, TypeError)):
        settings.repo_id = "outro/repo"


def test_an_unknown_flag_name_is_a_test_bug_not_a_silent_default():
    # The old script's _args() would happily set an attribute nothing reads.
    with pytest.raises(AttributeError):
        make_settings(flag_que_nao_existe=True)


def test_from_namespace_is_the_only_constructor_the_cli_uses():
    assert isinstance(make_settings(), Settings)
