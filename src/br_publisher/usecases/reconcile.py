"""Adopt Parquet already on the Hub into the manifest, without re-uploading."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from br_publisher.domain.keys import manifest_key
from br_publisher.domain.manifest import ManifestEntry
from br_publisher.domain.plan import Plan
from br_publisher.infra.fsio import sha256_file
from br_publisher.library.models import SourceResource

if TYPE_CHECKING:
    from .publish import PublishContext


class ReconcileOrphans:
    """Adopt published files the manifest forgot, at the cost of their row count.

    What the entry cannot recover is the row count: that would mean reading the
    source back, which is the expensive half this exists to skip. ``adopted:
    true`` marks those entries so a later audit can force a proper rewrite.

    The assumption worth stating out loud: this trusts that the published file
    was built from the source that is current *now*. If the portal replaced the
    file between the upload and this reconciliation, the entry is born wrong and
    that month will never refresh itself.

    Downloading to recover a hash only happens under --push. A dry run keeps the
    standing rule -- it never fetches -- and instead reports which months could
    be adopted for free and which would cost a download.
    """

    def __init__(self, ctx: PublishContext) -> None:
        self._ctx = ctx

    def __call__(
        self,
        orphans: Sequence[tuple[str, str, str]],
        repo_files: Mapping[str, int],
        plan: Plan,
    ) -> None:
        ctx = self._ctx
        adopted: dict[str, ManifestEntry] = {}
        would_download = 0

        for path, family_key, period in orphans:
            resource = ctx.catalog.resource_for(family_key, period)
            if resource is None:
                ctx.reporter.warning("  orfao %s: sem recurso correspondente no catalogo; ignorado.", path)
                continue
            digest, origin = self._digest(resource)
            if digest is None:
                would_download += 1
                ctx.reporter.info(
                    "  orfao %s/%s: exigiria baixar a origem para reconciliar.", family_key, period
                )
                continue
            adopted[manifest_key(family_key, period)] = ManifestEntry(
                source_sha256=digest,
                source_url=resource.url,
                resource_id=resource.resource_id,
                rows=None,
                columns=None,
                parquet_bytes=repo_files.get(path),
                conversion=ctx.recipe,
                adopted=True,
            )
            ctx.reporter.info("  adota %s/%s (sha via %s)", family_key, period, origin)

        if would_download:
            ctx.reporter.info(
                "reconciliar: %d arquivo(s) exigem baixar a origem; repita com --push.", would_download
            )
        if not adopted:
            ctx.reporter.info("reconciliar: nada a adotar.")
            return
        if not ctx.profile.may_publish:
            ctx.reporter.info("reconciliar: %d arquivo(s) seriam adotados (dry run).", len(adopted))
            return

        ctx.repository.replace_manifest(adopted, f"Reconciliar {len(adopted)} arquivo(s) ja publicados")
        plan.reconciled.extend(tuple(key.split("/", 1)) for key in sorted(adopted))
        ctx.reporter.checkpoint("reconciliar: %d arquivo(s) adotados no manifesto.", len(adopted))

    def _digest(self, resource: SourceResource) -> tuple[str | None, str]:
        """The source's SHA256 and where it came from, cheapest source first.

        ``registry.json`` is the cheap win: the library records a resource's hash
        on first download and keeps it even after the file itself is deleted, so
        a month whose source is long gone can still be identified for free.
        """
        ctx = self._ctx
        known = ctx.store.known_digest(resource)
        if known:
            return known, "registry"
        cached = ctx.store.cached_path(resource)
        if cached is not None:
            return sha256_file(cached), "cache"
        if not ctx.profile.may_download:
            return None, "indisponivel"
        return sha256_file(ctx.store.fetch(resource)), "download"
