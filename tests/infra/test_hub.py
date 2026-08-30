from __future__ import annotations

import json

import pytest

from br_publisher.domain.manifest import Manifest, ManifestEntry
from br_publisher.domain.recipe import CONVERSION_RECIPE, MANIFEST_PATH, MANIFEST_SCHEMA_VERSION
from br_publisher.errors import ManifestError
from br_publisher.infra.hub import CommitBatch, HuggingFaceRepository
from br_publisher.ports import HubClient

from ..fakes import RecordingHubClient


def _entry(**overrides) -> ManifestEntry:
    return ManifestEntry(
        source_sha256=overrides.pop("source_sha256", "sha256:abc"),
        source_url="https://fixtures.test/res.csv",
        resource_id="res",
        rows=2,
        columns=2,
        parquet_bytes=10,
        conversion=CONVERSION_RECIPE,
        **overrides,
    )


def _seed(tmp_path, name: str = "2024-06.parquet"):
    path = tmp_path / name
    path.write_bytes(b"parquet")
    return path


def test_the_recording_client_satisfies_the_hub_client_protocol():
    # Naming the slice of HfApi this tool uses is what lets the commit tests run
    # without huggingface_hub; if the Protocol grows a method, the fake has to
    # grow it too instead of failing with a TypeError mid-run.
    required = set(HubClient.__protocol_attrs__)
    client = RecordingHubClient()
    missing = {name for name in required if not callable(getattr(client, name, None))}
    assert missing == set()


def test_commit_batch_flushes_on_the_file_count(tmp_path):
    client = RecordingHubClient()
    batch = CommitBatch(client=client, repo_id="u/r", manifest=Manifest.empty(), max_files=2)
    for index in range(2):
        batch.add(_seed(tmp_path, f"m{index}.parquet"), f"data/f/{index}.parquet", f"f/{index}", _entry(), 1)
    assert len(client.commits) == 1
    assert batch.commits == 1


def test_commit_batch_publishes_the_manifest_in_the_same_commit(tmp_path):
    # Uploading the manifest afterwards left a window where the Hub held files
    # the manifest did not record. An abrupt shutdown inside that window is what
    # stranded 25 months as a permanent "novo".
    client = RecordingHubClient()
    manifest = Manifest.empty()
    batch = CommitBatch(client=client, repo_id="u/r", manifest=manifest, max_files=1)
    batch.add(_seed(tmp_path), "data/perfil_unidades/2024-06.parquet", "perfil_unidades/2024-06", _entry(), 7)

    (commit,) = client.commits
    paths = [operation.path_in_repo for operation in commit["operations"]]
    assert paths == ["data/perfil_unidades/2024-06.parquet", MANIFEST_PATH]
    assert commit["commit_message"] == "Publicar 1 arquivo(s): data/perfil_unidades/2024-06.parquet"

    payload = json.loads(commit["operations"][-1].path_or_fileobj.decode("utf-8"))
    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert "perfil_unidades/2024-06" in payload["entries"]
    assert manifest.get("perfil_unidades", "2024-06") is not None


def test_commit_batch_names_the_first_and_last_target(tmp_path):
    client = RecordingHubClient()
    batch = CommitBatch(client=client, repo_id="u/r", manifest=Manifest.empty(), max_files=3)
    for index in range(3):
        batch.add(_seed(tmp_path, f"m{index}.parquet"), f"data/f/{index}.parquet", f"f/{index}", _entry(), 1)
    assert client.commits[0]["commit_message"] == "Publicar 3 arquivo(s): data/f/0.parquet ... data/f/2.parquet"


def test_commit_batch_flushes_on_the_byte_cap(tmp_path):
    client = RecordingHubClient()
    batch = CommitBatch(
        client=client, repo_id="u/r", manifest=Manifest.empty(), max_files=100, max_bytes=10
    )
    batch.add(_seed(tmp_path), "data/f/0.parquet", "f/0", _entry(), 11)
    assert len(client.commits) == 1


def test_commit_batch_flush_is_a_noop_when_empty():
    client = RecordingHubClient()
    CommitBatch(client=client, repo_id="u/r", manifest=Manifest.empty()).flush()
    assert client.commits == []


def test_commit_batch_does_not_record_a_commit_that_failed(tmp_path):
    # The in-memory manifest may only claim a month once its commit landed.
    client = RecordingHubClient(fail_on_commit=True)
    manifest = Manifest.empty()
    batch = CommitBatch(client=client, repo_id="u/r", manifest=manifest, max_files=1)
    with pytest.raises(RuntimeError):
        batch.add(_seed(tmp_path), "data/perfil_unidades/2024-06.parquet", "perfil_unidades/2024-06", _entry(), 1)
    assert len(manifest) == 0
    assert batch.commits == 0


def test_commit_batch_keeps_the_cached_parquet(tmp_path):
    # The converted Parquet is kept on purpose now; deleting it here is what
    # made an interrupted run restart instead of resume.
    client = RecordingHubClient()
    local = _seed(tmp_path)
    batch = CommitBatch(client=client, repo_id="u/r", manifest=Manifest.empty(), max_files=1)
    batch.add(local, "data/f/0.parquet", "f/0", _entry(), 1)
    assert local.exists()


def test_load_manifest_of_a_repo_without_one():
    repository = HuggingFaceRepository(RecordingHubClient(), "u/r")
    assert len(repository.load_manifest()) == 0


def test_load_manifest_reads_what_the_repo_holds(tmp_path):
    client = RecordingHubClient()
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "entries": {"perfil_unidades/2024-06": _entry().to_payload()},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    client.seed_manifest_download(path)

    repository = HuggingFaceRepository(client, "u/r")
    manifest = repository.load_manifest()
    assert manifest.get("perfil_unidades", "2024-06").source_sha256 == "sha256:abc"


def test_an_unreadable_manifest_is_an_error_not_an_empty_one(tmp_path):
    client = RecordingHubClient()
    path = tmp_path / "manifest.json"
    path.write_text("{ truncado", encoding="utf-8")
    client.seed_manifest_download(path)

    with pytest.raises(ManifestError):
        HuggingFaceRepository(client, "u/r").load_manifest()


def test_list_parquet_ignores_everything_else():
    client = RecordingHubClient()
    client.tree = [
        type("Item", (), {"path": "data/perfil_unidades/2024-06.parquet", "size": 10})(),
        type("Item", (), {"path": "data/README.md", "size": 1})(),
    ]
    repository = HuggingFaceRepository(client, "u/r")
    assert repository.list_parquet() == {"data/perfil_unidades/2024-06.parquet": 10}


def test_the_card_is_not_clobbered_unless_asked():
    # Republishing a generated card on every run would silently throw away any
    # citation or note added through the web UI.
    client = RecordingHubClient(existing={"README.md"})
    HuggingFaceRepository(client, "u/r").write_card("# novo", overwrite=False)
    assert client.uploads == []


def test_the_card_is_written_when_the_repo_has_none():
    client = RecordingHubClient()
    HuggingFaceRepository(client, "u/r").write_card("# novo", overwrite=False)
    assert client.uploads[0]["path_in_repo"] == "README.md"


def test_update_card_overwrites_an_existing_one():
    client = RecordingHubClient(existing={"README.md"})
    HuggingFaceRepository(client, "u/r").write_card("# novo", overwrite=True)
    assert len(client.uploads) == 1


def test_replace_manifest_uploads_and_then_adopts():
    client = RecordingHubClient()
    repository = HuggingFaceRepository(client, "u/r")
    repository.replace_manifest({"perfil_unidades/2024-06": _entry(adopted=True)}, "Reconciliar 1")
    assert client.uploads[0]["path_in_repo"] == MANIFEST_PATH
    assert repository.manifest.get("perfil_unidades", "2024-06").adopted is True
