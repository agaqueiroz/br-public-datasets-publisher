"""End-to-end through the composition root.

Exit codes and the exact Portuguese on stderr are the user-facing contract, so
these go through ``main(argv)`` rather than through the pieces underneath.
"""

from __future__ import annotations

import pytest

from br_publisher import main as main_module
from br_publisher.errors import LibraryIncompatibleError
from br_publisher.main import ExitCode, main


@pytest.fixture(autouse=True)
def _no_hub_calls(monkeypatch):
    """Nothing here may touch the network. A leak shows up as an exception."""
    monkeypatch.setattr(main_module, "has_token", lambda: True)


def test_no_hub_with_push_is_rejected(capsys):
    assert main(["--no-hub", "--push", "--no-log-file"]) == ExitCode.USAGE
    assert "incompativeis" in capsys.readouterr().err


def test_sample_with_push_is_rejected(capsys):
    assert main(["--sample", "--push", "--no-log-file"]) == ExitCode.USAGE
    assert "incompativeis" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--reconciliar", "--prune-parquet"])
@pytest.mark.parametrize("offline", ["--sample", "--no-hub"])
def test_hub_only_flags_are_rejected_offline(flag, offline, capsys):
    assert main([flag, offline, "--no-log-file"]) == ExitCode.USAGE
    assert "precisa consultar o Hub" in capsys.readouterr().err


def test_an_invalid_period_is_a_usage_error(capsys):
    assert main(["--periodo", "lixo", "--no-log-file"]) == ExitCode.USAGE
    assert "periodo invalido" in capsys.readouterr().err


def test_push_without_any_token_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(main_module, "has_token", lambda: False)
    assert main(["--push", "--no-log-file"]) == ExitCode.USAGE
    error = capsys.readouterr().err
    assert "HF_TOKEN" in error and "hf auth login" in error


def test_an_incompatible_library_exits_2_before_anything_else(monkeypatch, capsys):
    def boom() -> None:
        raise LibraryIncompatibleError("brinss-public-datasets 9.9.9 esta fora da faixa suportada (0.1.x).")

    monkeypatch.setattr(main_module, "check_library", boom)
    assert main(["--no-log-file"]) == ExitCode.USAGE
    assert "fora da faixa suportada" in capsys.readouterr().err


def test_an_unreadable_manifest_refuses_to_publish(monkeypatch, tmp_path, capsys):
    # An unreadable manifest must never degrade into an empty one: that would
    # re-upload the whole dataset.
    class _Client:
        def create_repo(self, repo_id, *, repo_type, exist_ok):
            return None

        def file_exists(self, repo_id, filename, **kwargs):
            return filename == "manifest.json"

        def hf_hub_download(self, **kwargs):
            path = tmp_path / "manifest.json"
            path.write_text("{ truncado", encoding="utf-8")
            return str(path)

        def list_repo_tree(self, repo_id, *, path_in_repo, repo_type, recursive):
            return []

        def create_commit(self, **kwargs):
            raise AssertionError("nada deveria ter sido publicado")

        def upload_file(self, **kwargs):
            raise AssertionError("nada deveria ter sido publicado")

    monkeypatch.setattr(main_module, "build_client", _Client)
    assert main(["--push", "--no-log-file"]) == ExitCode.USAGE


def test_a_dry_run_without_the_hub_reaches_the_summary(monkeypatch, tmp_path, capsys):
    # --no-hub is the cheapest full pass through the composition root: no
    # network at all, and every wiring decision still exercised.
    from br_publisher.library import BrinssLibrary

    monkeypatch.setattr(BrinssLibrary, "resources", lambda self, family_key: ())
    code = main(
        [
            "--no-hub",
            "--no-log-file",
            "--familia",
            "perfil_unidades",
            "--parquet-dir",
            str(tmp_path / "tmp"),
        ]
    )
    assert code == ExitCode.OK


def test_the_help_still_carries_the_flags_users_know(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for flag in ("--push", "--sample", "--familia", "--periodo", "--reconciliar", "--prune-parquet",
                 "--parquet-dir", "--sample-dir", "--commit-size", "--update-card", "--no-hub"):
        assert flag in out


def test_the_sample_dir_alias_still_works(tmp_path, monkeypatch):
    from br_publisher.library import BrinssLibrary

    monkeypatch.setattr(BrinssLibrary, "resources", lambda self, family_key: ())
    assert main(["--sample", "--no-log-file", "--sample-dir", str(tmp_path / "tmp")]) == ExitCode.OK


def test_a_log_file_is_written_when_asked(tmp_path, monkeypatch):
    from br_publisher.library import BrinssLibrary

    monkeypatch.setattr(BrinssLibrary, "resources", lambda self, family_key: ())
    log_file = tmp_path / "run.log"
    main(["--no-hub", "--log-file", str(log_file), "--parquet-dir", str(tmp_path / "tmp")])
    assert log_file.exists()
    assert "CONCLUIDO COM SUCESSO" in log_file.read_text(encoding="utf-8")


def test_a_run_that_cannot_start_leaves_no_log_behind(tmp_path):
    # Validation runs ahead of the logging setup on purpose.
    log_file = tmp_path / "run.log"
    assert main(["--sample", "--push", "--log-file", str(log_file)]) == ExitCode.USAGE
    assert not log_file.exists()
