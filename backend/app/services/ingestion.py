from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..config import Settings
from ..db import MetadataStore
from .embeddings import HashEmbedding
from .pdf_ingest import chunk_pdf
from .vector_store import VectorStore


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        metadata: MetadataStore,
        vector_store: VectorStore,
        embeddings: HashEmbedding,
    ) -> None:
        self.settings = settings
        self.metadata = metadata
        self.vector_store = vector_store
        self.embeddings = embeddings

    async def ingest(
        self,
        *,
        job_id: str,
        document_id: str,
        file_path: Path,
        filename: str,
        size_bytes: int,
        sha256: str,
    ) -> None:
        try:
            self.metadata.update_job(
                job_id,
                status="running",
                progress=8,
                stage="读取 PDF",
                document_id=document_id,
            )
            parsed = await asyncio.to_thread(
                chunk_pdf,
                file_path,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
            )

            self.metadata.update_job(
                job_id,
                progress=42,
                stage=f"提取 {parsed.page_count} 页 · {len(parsed.chunks)} 个切片",
            )
            texts = [chunk.text for chunk in parsed.chunks]
            embeddings = await asyncio.to_thread(self.embeddings.embed, texts)

            self.metadata.update_job(
                job_id,
                progress=70,
                stage="写入 Chroma 向量库",
            )
            ids = [
                f"{document_id}:{chunk.kind}:{chunk.index}" for chunk in parsed.chunks
            ]
            metadatas = [
                {
                    "document_id": document_id,
                    "document_name": filename,
                    "title": parsed.title,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "chunk_index": chunk.index,
                    "kind": chunk.kind,
                }
                for chunk in parsed.chunks
            ]
            await asyncio.to_thread(
                self.vector_store.add,
                ids=ids,
                texts=texts,
                metadatas=metadatas,
                embeddings=embeddings,
            )

            content_chunks = sum(1 for chunk in parsed.chunks if chunk.kind == "chunk")
            self.metadata.add_document(
                {
                    "id": document_id,
                    "filename": filename,
                    "title": parsed.title,
                    "size_bytes": size_bytes,
                    "pages": parsed.page_count,
                    "chunks": content_chunks,
                    "status": "ready",
                    "summary": parsed.summary,
                    "file_path": str(file_path),
                    "sha256": sha256,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            self.metadata.update_job(
                job_id,
                status="completed",
                progress=100,
                stage="索引完成",
                document_id=document_id,
            )
        except Exception as error:
            self.metadata.update_job(
                job_id,
                status="failed",
                progress=100,
                stage="处理失败",
                document_id=document_id,
                error=str(error),
            )
            try:
                await asyncio.to_thread(self.vector_store.delete_document, document_id)
            except Exception:
                pass

    @staticmethod
    def new_document_id() -> str:
        return uuid.uuid4().hex
