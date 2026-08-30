"""The published side, over huggingface_hub. The only module that imports it."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from br_publisher.domain.manifest import Manifest, ManifestEntry
from br_publisher.domain.recipe import CARD_PATH, COMMIT_BYTE_CAP, DEFAULT_COMMIT_SIZE, MANIFEST_PATH
from br_publisher.errors import ManifestError
from br_publisher.ports import HubClient

from .fsio import json_bytes

LOGGER = logging.getLogger("brinss.publish")


def has_token() -> bool:
    """Whether huggingface_hub can find a token anywhere -- env, OIDC, or disk.

    ``get_token()`` walks several sources: an OIDC exchange when
    HF_OIDC_RESOURCE is set (Trusted Publishers in CI), then HF_TOKEN, then
    HUGGING_FACE_HUB_TOKEN, then the token file written by ``hf auth login``,
    then Colab secrets. Reading os.environ alone would reject a perfectly good
    CLI session.
    """
    from huggingface_hub import get_token

    return bool(get_token())


def build_client() -> HubClient:
    from huggingface_hub import HfApi

    return HfApi()


def _commit_message(targets: list[str]) -> str:
    message = f"Publicar {len(targets)} arquivo(s): {targets[0]}"
    if len(targets) > 1:
        message += f" ... {targets[-1]}"
    return message


def _commit_ref(info: object) -> str:
    oid = getattr(info, "oid", None)
    return f" ({oid[:8]})" if isinstance(oid, str) else ""


@dataclass
class CommitBatch:
    """Groups Parquet files, and the manifest describing them, into one commit.

    A file-per-commit first load is roughly 300 sequential commits: slow, hard on
    the rate limiting of the Hub, and it buries the repository history.

    The manifest goes in the *same* commit as the data. Uploading it afterwards
    left a window where the Hub held files the manifest did not record, and an
    abrupt shutdown inside that window is what stranded 25 months as a permanent
    "novo". One commit carrying both makes the inconsistent state unreachable;
    the in-memory manifest is only updated once the commit has landed.
    """

    client: HubClient
    repo_id: str
    manifest: Manifest
    max_files: int = DEFAULT_COMMIT_SIZE
    max_bytes: int = COMMIT_BYTE_CAP
    on_commit: object | None = None
    operations: list = field(default_factory=list)
    pending: list[tuple[str, ManifestEntry]] = field(default_factory=list)
    pending_bytes: int = 0
    commits: int = 0

    def add(self, local: Path, target: str, key: str, entry: ManifestEntry, size: int) -> None:
        from huggingface_hub import CommitOperationAdd

        self.operations.append(CommitOperationAdd(path_in_repo=target, path_or_fileobj=str(local)))
        self.pending.append((key, entry))
        self.pending_bytes += size
        if len(self.operations) >= self.max_files or self.pending_bytes >= self.max_bytes:
            self.flush()

    def flush(self) -> None:
        if not self.operations:
            return
        from huggingface_hub import CommitOperationAdd

        # Read before the manifest operation joins them, or the message names it.
        targets = [operation.path_in_repo for operation in self.operations]
        merged = {**self.manifest.entries(), **dict(self.pending)}
        payload = {
            "schema_version": Manifest(merged).to_payload()["schema_version"],
            "entries": {key: entry.to_payload() for key, entry in merged.items()},
        }
        operations = [
            *self.operations,
            CommitOperationAdd(path_in_repo=MANIFEST_PATH, path_or_fileobj=json_bytes(payload)),
        ]
        info = self.client.create_commit(
            repo_id=self.repo_id,
            repo_type="dataset",
            operations=operations,
            commit_message=_commit_message(targets),
        )
        # Only now that the commit landed may the manifest claim these months.
        self.manifest.adopt(dict(self.pending))
        self.commits += 1
        if callable(self.on_commit):
            self.on_commit(self.commits, len(targets), self.pending_bytes, _commit_ref(info))
        self.operations.clear()
        self.pending.clear()
        self.pending_bytes = 0


class HuggingFaceRepository:
    """DatasetRepository over huggingface_hub, batching commits.

    Batching is delegated to CommitBatch, which stays a separate class so its
    invariant -- the manifest travels in the SAME commit as the files it
    describes -- is testable without a repository, a settings object or a token.
    """

    def __init__(
        self,
        client: HubClient,
        repo_id: str,
        *,
        commit_size: int = DEFAULT_COMMIT_SIZE,
        byte_cap: int = COMMIT_BYTE_CAP,
        on_commit: object | None = None,
    ) -> None:
        self._client = client
        self._repo_id = repo_id
        self._manifest = Manifest.empty()
        self._batch = CommitBatch(
            client=client,
            repo_id=repo_id,
            manifest=self._manifest,
            max_files=commit_size,
            max_bytes=byte_cap,
            on_commit=on_commit,
        )

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    @property
    def commits(self) -> int:
        return self._batch.commits

    def ensure_exists(self) -> None:
        self._client.create_repo(self._repo_id, repo_type="dataset", exist_ok=True)

    def load_manifest(self) -> Manifest:
        """Read the manifest of the Hub, refusing to guess when it cannot be trusted.

        ``Manifest.empty()`` is returned only for the two cases that positively
        establish there is nothing published yet.

        The download is forced past the local huggingface_hub cache -- the file
        is tiny, and re-reading a blob that a crash may have left half-written is
        not a risk worth taking.
        """
        from huggingface_hub.errors import RepositoryNotFoundError

        try:
            if not self._client.file_exists(self._repo_id, MANIFEST_PATH, repo_type="dataset"):
                self._adopt(Manifest.empty())
                return self._manifest
            local = self._client.hf_hub_download(
                repo_id=self._repo_id, filename=MANIFEST_PATH, repo_type="dataset", force_download=True
            )
        except RepositoryNotFoundError:
            self._adopt(Manifest.empty())
            return self._manifest

        try:
            payload = json.loads(Path(local).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise ManifestError(f"{MANIFEST_PATH} do repositorio esta ilegivel: {exc}") from exc
        self._adopt(Manifest.from_payload(payload))
        return self._manifest

    def list_parquet(self) -> dict[str, int]:
        """Every published Parquet and its size, for orphan detection and pruning."""
        from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

        try:
            tree = self._client.list_repo_tree(
                self._repo_id, path_in_repo="data", repo_type="dataset", recursive=True
            )
            return {item.path: getattr(item, "size", 0) for item in tree if item.path.endswith(".parquet")}
        except (RepositoryNotFoundError, EntryNotFoundError):
            return {}

    def stage(self, local: Path, target: str, key: str, entry: ManifestEntry, size: int) -> None:
        self._batch.add(local, target, key, entry, size)

    def flush(self) -> None:
        self._batch.flush()

    def replace_manifest(self, entries: Mapping[str, ManifestEntry], message: str) -> None:
        merged = {**self._manifest.entries(), **entries}
        payload = {
            "schema_version": Manifest(merged).to_payload()["schema_version"],
            "entries": {key: entry.to_payload() for key, entry in merged.items()},
        }
        self._client.upload_file(
            path_or_fileobj=json_bytes(payload),
            path_in_repo=MANIFEST_PATH,
            repo_id=self._repo_id,
            repo_type="dataset",
            commit_message=message,
        )
        self._manifest.adopt(dict(entries))

    def write_card(self, markdown: str, *, overwrite: bool) -> None:
        """Write the dataset card, but never clobber one edited on the Hub.

        The card is generated, so republishing it on every run would silently
        throw away any citation, example or note added through the web UI. It is
        written when the repo has none, and otherwise only on an explicit
        --update-card.
        """
        if not overwrite and self._client.file_exists(self._repo_id, CARD_PATH, repo_type="dataset"):
            return
        self._client.upload_file(
            path_or_fileobj=markdown.encode("utf-8"),
            path_in_repo=CARD_PATH,
            repo_id=self._repo_id,
            repo_type="dataset",
            commit_message="Atualizar dataset card",
        )

    def _adopt(self, manifest: Manifest) -> None:
        """Swap in the loaded entries without replacing the object the batch holds."""
        self._manifest.adopt(manifest.entries())
