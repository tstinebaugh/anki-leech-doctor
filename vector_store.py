"""A small exact-search vector store on numpy.

Each record has an id, a metadata dict, and one vector per named space
(e.g. "semantic", "visual", "phonetic"). Search is a matrix-vector product over
the whole space, which is exact and takes well under a millisecond for the few
thousand cards this app indexes. See docs/design/0001-numpy-vector-index.md.

Everything is saved in one .npz file, written to a temp file and swapped in with
os.replace, so a crash never leaves a half-written index.
"""
import json
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

FORMAT_VERSION = 1


def _normalize_rows(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32, copy=False)


class VectorStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._ids: List[str] = []
        self._pos: Dict[str, int] = {}
        self._meta: List[Dict[str, Any]] = []
        self._spaces: Dict[str, np.ndarray] = {}
        self._load()

    # ---- persistence -----------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with np.load(self.path, allow_pickle=False) as data:
                if int(data["format_version"]) != FORMAT_VERSION:
                    raise ValueError(f"unsupported index format {int(data['format_version'])}")
                ids = [str(i) for i in data["ids"]]
                meta = json.loads(str(data["meta_json"]))
                spaces = {k[len("space_"):]: data[k].astype(np.float32) for k in data.files if k.startswith("space_")}
            if len(meta) != len(ids) or any(m.shape[0] != len(ids) for m in spaces.values()):
                raise ValueError("ids, metadata and vectors have different lengths")
        except Exception as e:
            # A broken index is just a cache: start empty and let the next sync rebuild it
            print(f"Ignoring unreadable vector index {self.path}: {e}")
            return
        self._ids, self._meta, self._spaces = ids, meta, spaces
        self._pos = {cid: i for i, cid in enumerate(ids)}

    def _save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".vectors-", suffix=".npz.tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                np.savez(
                    f,
                    format_version=np.array(FORMAT_VERSION),
                    ids=np.array(self._ids, dtype=str),
                    meta_json=np.array(json.dumps(self._meta, ensure_ascii=False)),
                    **{f"space_{name}": m for name, m in self._spaces.items()},
                )
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    # ---- writes ----------------------------------------------------------------------

    def upsert(
        self,
        ids: Sequence[str],
        vectors: Dict[str, Sequence[Sequence[float]]],
        metadatas: Sequence[Dict[str, Any]],
    ) -> None:
        """Adds new records and replaces existing ones with the same id."""
        if not ids:
            return
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate ids in one upsert")
        if len(metadatas) != len(ids):
            raise ValueError("metadatas must match ids")
        new = {name: _normalize_rows(np.asarray(v, dtype=np.float32).reshape(len(ids), -1)) for name, v in vectors.items()}

        with self._lock:
            if self._ids and set(new) != set(self._spaces):
                raise ValueError(f"vector spaces {sorted(new)} don't match the index {sorted(self._spaces)}")
            for name, m in new.items():
                if name in self._spaces and self._spaces[name].shape[1] != m.shape[1]:
                    raise ValueError(f"{name} vectors have {m.shape[1]} dims, index has {self._spaces[name].shape[1]}")

            existing = [(i, self._pos[cid]) for i, cid in enumerate(ids) if cid in self._pos]
            added = [i for i, cid in enumerate(ids) if cid not in self._pos]

            for i, row in existing:
                self._meta[row] = dict(metadatas[i])
                for name, m in new.items():
                    self._spaces[name][row] = m[i]
            if added:
                for name, m in new.items():
                    block = m[added]
                    self._spaces[name] = np.vstack([self._spaces[name], block]) if name in self._spaces and self._ids else block
                for i in added:
                    self._pos[ids[i]] = len(self._ids)
                    self._ids.append(ids[i])
                    self._meta.append(dict(metadatas[i]))
            self._save()

    def delete(self, ids: Sequence[str]) -> int:
        """Removes records by id. Returns how many were removed."""
        with self._lock:
            drop = {self._pos[cid] for cid in ids if cid in self._pos}
            if not drop:
                return 0
            keep = np.array([i for i in range(len(self._ids)) if i not in drop], dtype=np.intp)
            self._ids = [self._ids[i] for i in keep]
            self._meta = [self._meta[i] for i in keep]
            self._spaces = {name: m[keep] for name, m in self._spaces.items()}
            self._pos = {cid: i for i, cid in enumerate(self._ids)}
            self._save()
            return len(drop)

    def clear(self) -> None:
        with self._lock:
            self._ids, self._meta, self._spaces, self._pos = [], [], {}, {}
            if os.path.exists(self.path):
                os.remove(self.path)

    # ---- reads -----------------------------------------------------------------------

    def count(self) -> int:
        return len(self._ids)

    def get(self, ids: Sequence[str]) -> List[Dict[str, Any]]:
        """Metadata for the given ids, skipping unknown ones."""
        with self._lock:
            return [self._meta[self._pos[cid]] for cid in ids if cid in self._pos]

    def all_metadata(self) -> List[Tuple[str, Dict[str, Any]]]:
        with self._lock:
            return list(zip(self._ids, self._meta))

    def query(self, space: str, vector: Sequence[float], k: int) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Top-k records by cosine similarity in one space, best first."""
        with self._lock:
            m: Optional[np.ndarray] = self._spaces.get(space)
            if m is None or not self._ids or k <= 0:
                return []
            q = np.asarray(vector, dtype=np.float32).ravel()
            if q.shape[0] != m.shape[1]:
                raise ValueError(f"query has {q.shape[0]} dims, {space} index has {m.shape[1]}")
            norm = float(np.linalg.norm(q))
            if norm == 0:
                return []
            scores = m @ (q / norm)
            k = min(k, len(scores))
            top = np.argpartition(-scores, k - 1)[:k] if k < len(scores) else np.arange(len(scores))
            top = top[np.argsort(-scores[top], kind="stable")]
            return [(self._ids[i], float(scores[i]), self._meta[i]) for i in top]
