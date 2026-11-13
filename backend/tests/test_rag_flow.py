from __future__ import annotations

import time
import json
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]


def create_test_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Private RAG assistant. The frontend uses Vue3 and TypeScript. "
        "The backend uses FastAPI and streams answers with SSE. "
        "PDF text is split into 800 character chunks with 100 character overlap. "
        "Chroma retrieves the top-k passages and answers include page citations.",
        fontsize=11,
    )
    document.save(path)
    document.close()
    return path


def test_complete_upload_and_streaming_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RAG_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    from backend.app.config import get_settings

    get_settings.cache_clear()
    from backend.app.main import app

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["chunk_size"] == 800

        sample = create_test_pdf(tmp_path / "rag-test.pdf")
        with sample.open("rb") as handle:
            upload = client.post(
                "/api/documents/upload",
                files={"file": (sample.name, handle, "application/pdf")},
            )
        assert upload.status_code == 202, upload.text
        job_id = upload.json()["job_id"]

        deadline = time.time() + 15
        job = None
        while time.time() < deadline:
            job_response = client.get(f"/api/jobs/{job_id}")
            assert job_response.status_code == 200
            job = job_response.json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert job is not None
        assert job["status"] == "completed", job

        documents = client.get("/api/documents").json()["items"]
        assert len(documents) == 1
        document_id = documents[0]["id"]

        response = client.post(
            "/api/chat/stream",
            json={
                "question": "Which frontend, backend and retrieval settings are used?",
                "document_ids": [document_id],
                "top_k": 5,
                "history": [],
            },
        )
        assert response.status_code == 200
        body = response.text
        assert "event: meta" in body
        assert "event: citations" in body
        assert "event: token" in body
        assert "event: done" in body
        answer = "".join(
            json.loads(line[5:]).get("text", "")
            for line in body.splitlines()
            if line.startswith("data:") and '"text"' in line
        )
        assert "Vue3" in answer or "FastAPI" in answer

        deleted = client.delete(f"/api/documents/{document_id}")
        assert deleted.status_code == 200
        assert client.get("/api/documents").json()["items"] == []
