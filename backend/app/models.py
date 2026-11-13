from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    id: str
    filename: str
    title: str | None = None
    size_bytes: int
    pages: int
    chunks: int
    status: str
    summary: str
    created_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total_pages: int
    total_chunks: int


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    status: str


class JobStatusResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    stage: str
    document_id: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    provider: str
    vector_backend: str
    documents: int
    chunks: int
    chunk_size: int
    chunk_overlap: int
    top_k: int


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=12)
    history: list[HistoryMessage] = Field(default_factory=list)


class Citation(BaseModel):
    index: int
    document_id: str
    document_name: str
    page_start: int
    page_end: int
    chunk_index: int
    score: float
    snippet: str


class RetrievalHit(BaseModel):
    rank: int
    document_id: str
    document_name: str
    page_start: int
    page_end: int
    chunk_index: int
    score: float
    snippet: str
