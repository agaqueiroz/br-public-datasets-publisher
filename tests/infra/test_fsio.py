from __future__ import annotations

import hashlib
import json

from br_publisher.infra.fsio import json_bytes, sha256_file, write_json_atomic


def test_sha256_file_matches_hashlib(tmp_path):
    # The chunked reader exists so multi-GB resources do not land in memory;
    # it still has to agree with hashing the whole file at once.
    path = tmp_path / "res.bin"
    payload = b"x" * (1024 * 1024 + 7)
    path.write_bytes(payload)
    assert sha256_file(path) == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_write_json_atomic_replaces_the_previous_file(tmp_path):
    path = tmp_path / "index.json"
    write_json_atomic(path, {"a": 1})
    write_json_atomic(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    # The .tmp must not survive: a leftover would shadow nothing, but it is the
    # visible symptom of a write that did not complete.
    assert not (tmp_path / "index.json.tmp").exists()


def test_write_json_atomic_creates_missing_parents(tmp_path):
    path = tmp_path / "deep" / "nested" / "index.json"
    write_json_atomic(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_json_bytes_is_stable_and_sorted():
    assert json_bytes({"b": 1, "a": 2}) == b'{\n  "a": 2,\n  "b": 1\n}'
