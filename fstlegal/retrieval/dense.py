"""Dense (embedding) search with exact cosine similarity (Decision D-004).

Embeddings come from any server with an OpenAI-compatible ``/v1/embeddings``
endpoint, such as ``llama-server --embedding``. Vectors are cached in a ``.npz``
file tied to the corpus hash and the model name, so they are recomputed only
when either changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from .store import ChunkHit, Corpus


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HttpEmbedder:
    """Client for an OpenAI-compatible embeddings endpoint."""

    def __init__(self, base_url: str, name: str, batch_size: int = 16,
                 query_prefix: str = "", timeout: float = 300):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.batch_size = batch_size
        self.query_prefix = query_prefix
        self.client = httpx.Client(timeout=timeout)

    def embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            r = self.client.post(f"{self.base_url}/v1/embeddings",
                                 json={"input": batch, "model": self.name})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return _normalize(np.asarray(out, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed([self.query_prefix + text])[0]


def _normalize(v: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(norms, 1e-12)


class VectorIndex:
    def __init__(self, ids: list[str], vectors: np.ndarray, meta: list[dict]):
        self.ids = ids
        self.vectors = vectors
        self.meta = meta

    @classmethod
    def build(cls, corpus: Corpus, embedder: Embedder, cache_dir: Path) -> VectorIndex:
        safe = embedder.name.replace("/", "_").replace(":", "_")
        path = cache_dir / f"vectors_{safe}_{corpus.content_hash[:12]}.npz"
        chunks = corpus.chunks()
        if path.exists():
            data = np.load(path, allow_pickle=False)
            vectors = data["vectors"]
            ids = list(data["ids"])
        else:
            ids = [c["id"] for c in chunks]
            vectors = embedder.embed([c["text"] for c in chunks])
            cache_dir.mkdir(parents=True, exist_ok=True)
            np.savez(path, ids=np.array(ids), vectors=vectors)
        by_id = {c["id"]: c for c in chunks}
        return cls(ids, vectors, [by_id[i] for i in ids])

    def search(self, query_vector: np.ndarray, k: int = 20, kind: str | None = None,
               exclude_sources: set[str] | None = None) -> list[ChunkHit]:
        scores = self.vectors @ query_vector
        hits = []
        for i in np.argsort(-scores):
            m = self.meta[i]
            if kind and m["kind"] != kind:
                continue
            if exclude_sources and m["source_id"] in exclude_sources:
                continue
            hits.append(ChunkHit(m["id"], m["kind"], m["source_id"], m["text"],
                                 float(scores[i]), m["para_from"], m["para_to"]))
            if len(hits) == k:
                break
        return hits
