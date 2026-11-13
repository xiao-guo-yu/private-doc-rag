from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, Settings, get_settings
from .db import MetadataStore
from .models import (
    ChatRequest,
    DocumentItem,
    DocumentListResponse,
    HealthResponse,
    JobStatusResponse,
    UploadResponse,
)
from .services.embeddings import HashEmbedding
from .services.ingestion import IngestionService
from .services.rag import RagEngine
from .services.vector_store import create_vector_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    metadata = MetadataStore(settings.sqlite_path)
    embeddings = HashEmbedding()
    vector_store = create_vector_store(
        settings.chroma_dir,
        settings.data_dir / "fallback_vectors.json",
    )
    app.state.settings = settings
    app.state.metadata = metadata
    app.state.embeddings = embeddings
    app.state.vector_store = vector_store
    app.state.ingestion = IngestionService(
        settings,
        metadata,
        vector_store,
        embeddings,
    )
    app.state.rag = RagEngine(settings, metadata, vector_store, embeddings)
    app.state.tasks = set()
    yield
    tasks = list(app.state.tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="私有文档 RAG 问答助手",
    description="Upload private PDFs, retrieve grounded context, and stream cited answers.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8010",
        "http://127.0.0.1:8010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _settings() -> Settings:
    return app.state.settings


def _metadata() -> MetadataStore:
    return app.state.metadata


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = _settings()
    metadata = _metadata()
    documents, chunks = metadata.count()
    vector_store = app.state.vector_store
    return HealthResponse(
        status="ok",
        provider="llm" if settings.effective_api_key else "extractive",
        vector_backend=vector_store.backend_name,
        documents=documents,
        chunks=chunks,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        top_k=settings.top_k,
    )


@app.get("/api/documents", response_model=DocumentListResponse)
async def list_documents() -> DocumentListResponse:
    rows = _metadata().list_documents()
    items = [
        DocumentItem(
            id=row["id"],
            filename=row["filename"],
            title=row["title"],
            size_bytes=int(row["size_bytes"]),
            pages=int(row["pages"]),
            chunks=int(row["chunks"]),
            status=row["status"],
            summary=row["summary"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return DocumentListResponse(
        items=items,
        total_pages=sum(item.pages for item in items),
        total_chunks=sum(item.chunks for item in items),
    )


@app.post("/api/documents/upload", response_model=UploadResponse, status_code=202)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    settings = _settings()
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名。")
    filename = Path(file.filename).name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="当前仅支持 PDF 文档。")

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {settings.max_upload_mb} MB 限制。",
        )
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="文件不是有效的 PDF。")

    job_id = uuid.uuid4().hex
    document_id = app.state.ingestion.new_document_id()
    suffix = uuid.uuid4().hex[:10]
    stored_path = settings.upload_dir / f"{document_id}-{suffix}.pdf"
    await asyncio.to_thread(stored_path.write_bytes, content)
    sha256 = hashlib.sha256(content).hexdigest()
    _metadata().create_job(job_id)

    task = asyncio.create_task(
        app.state.ingestion.ingest(
            job_id=job_id,
            document_id=document_id,
            file_path=stored_path,
            filename=filename,
            size_bytes=len(content),
            sha256=sha256,
        )
    )
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return UploadResponse(job_id=job_id, filename=filename, status="queued")


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def job_status(job_id: str) -> JobStatusResponse:
    row = _metadata().get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    return JobStatusResponse(
        id=row["id"],
        status=row["status"],
        progress=int(row["progress"]),
        stage=row["stage"],
        document_id=row["document_id"],
        error=row["error"],
    )


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str) -> JSONResponse:
    row = _metadata().delete_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    await asyncio.to_thread(
        app.state.vector_store.delete_document,
        document_id,
    )
    file_path = Path(row["file_path"])
    if file_path.exists() and file_path.is_file():
        file_path.unlink(missing_ok=True)
    return JSONResponse({"deleted": document_id})


def _sse(event: dict) -> bytes:
    payload = json.dumps(event["data"], ensure_ascii=False)
    return f"event: {event['event']}\ndata: {payload}\n\n".encode("utf-8")


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空。")
    request.question = question

    async def stream():
        try:
            async for event in app.state.rag.stream(request):
                yield _sse(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            yield _sse(
                {
                    "event": "error",
                    "data": {"message": str(error)},
                }
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str):
        candidate = (frontend_dist / path).resolve()
        if path and candidate.is_file() and frontend_dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return JSONResponse(
            {
                "message": "RAG backend is running.",
                "frontend": "Run `npm run dev` in frontend or build frontend/dist.",
            }
        )
