from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any

from .embeddings import HashEmbedding


class VectorStore:
    backend_name = "unknown"

    def add(
        self,
        *,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        raise NotImplementedError

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def delete_document(self, document_id: str) -> None:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


class ChromaVectorStore(VectorStore):
    backend_name = "chroma"

    def __init__(self, path: Path) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection(
            name="private_document_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add(
        self,
        *,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        if not ids:
            return
        self._collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        total = self._collection.count()
        if total == 0:
            return []
        where: dict[str, Any] | None = None
        if document_ids:
            if len(document_ids) == 1:
                where = {"document_id": document_ids[0]}
            else:
                where = {"document_id": {"$in": document_ids}}
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(total, max(top_k * 4, top_k)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        hits: list[dict[str, Any]] = []
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for text, metadata, distance in zip(documents, metadatas, distances):
            hits.append(
                {
                    "text": text,
                    "metadata": metadata,
                    "score": max(0.0, 1.0 - float(distance)),
                }
            )
        return hits

    def delete_document(self, document_id: str) -> None:
        self._collection.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self._collection.count()


class JsonFallbackVectorStore(VectorStore):
    backend_name = "local-json-fallback"

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        if path.exists():
            try:
                self._records = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._records = []

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._records, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(
        self,
        *,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        with self._lock:
            id_set = set(ids)
            self._records = [
                record for record in self._records if record["id"] not in id_set
            ]
            for record_id, text, metadata, embedding in zip(
                ids, texts, metadatas, embeddings
            ):
                self._records.append(
                    {
                        "id": record_id,
                        "text": text,
                        "metadata": metadata,
                        "embedding": embedding,
                    }
                )
            self._flush()

    def query(
        self,
        embedding: list[float],
        *,
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            allowed = set(document_ids or [])
            candidates = [
                record
                for record in self._records
                if not allowed or record["metadata"].get("document_id") in allowed
            ]
            scored = []
            for record in candidates:
                score = sum(
                    left * right
                    for left, right in zip(embedding, record["embedding"])
                )
                scored.append(
                    {
                        "text": record["text"],
                        "metadata": record["metadata"],
                        "score": max(0.0, min(1.0, score)),
                    }
                )
            scored.sort(key=lambda item: item["score"], reverse=True)
            return scored[:top_k]

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self._records = [
                record
                for record in self._records
                if record["metadata"].get("document_id") != document_id
            ]
            self._flush()

    def count(self) -> int:
        with self._lock:
            return len(self._records)


def create_vector_store(chroma_dir: Path, fallback_path: Path) -> VectorStore:
    try:
        return ChromaVectorStore(chroma_dir)
    except Exception as error:  # pragma: no cover - environment fallback
        print(f"[vector-store] Chroma unavailable, using JSON fallback: {error}")
        return JsonFallbackVectorStore(fallback_path)
