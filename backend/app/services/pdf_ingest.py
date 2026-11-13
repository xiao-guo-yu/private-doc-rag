from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf


SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;.!?])\s*|\n+")
SUMMARY_LIMIT = 480


@dataclass(slots=True)
class TextChunk:
    index: int
    text: str
    page_start: int
    page_end: int
    kind: str = "chunk"


@dataclass(slots=True)
class ParsedDocument:
    title: str
    page_count: int
    text: str
    pages: list[tuple[int, str]]
    chunks: list[TextChunk]
    summary: str


def _clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(path: Path) -> tuple[str, list[tuple[int, str]]]:
    with pymupdf.open(path) as document:
        metadata = document.metadata or {}
        title = (metadata.get("title") or path.stem).strip()
        pages: list[tuple[int, str]] = []
        for page_index in range(document.page_count):
            text = _clean_text(document.load_page(page_index).get_text("text"))
            if text:
                pages.append((page_index + 1, text))
    if not pages:
        raise ValueError("PDF 中没有可提取文本，可能是扫描版或空文档。")
    return title, pages


def _page_range(
    page_spans: list[tuple[int, int, int]], start: int, end: int
) -> tuple[int, int]:
    matched = [
        page_number
        for span_start, span_end, page_number in page_spans
        if span_end > start and span_start < end
    ]
    if not matched:
        return 1, 1
    return min(matched), max(matched)


def _best_cut(text: str, start: int, maximal_end: int) -> int:
    if maximal_end >= len(text):
        return len(text)
    window_start = max(start + 240, maximal_end - 180)
    candidates = [
        match.end()
        for match in re.finditer(r"[。！？!?；;]\s*|\n{2,}", text[window_start:maximal_end])
    ]
    if candidates:
        return window_start + candidates[-1]
    return maximal_end


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in SENTENCE_BOUNDARY.split(text)
        if len(sentence.strip()) >= 8
    ]


def _keywords(text: str, limit: int = 8) -> list[str]:
    chinese_runs = re.findall(r"[\u3400-\u9fff]{2,30}", text)
    latin_terms = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", text)
    counts: dict[str, int] = {}
    ignored = {
        "可以",
        "进行",
        "以及",
        "我们",
        "一个",
        "这个",
        "通过",
        "必须",
        "文档",
    }
    for run in chinese_runs:
        for index in range(len(run) - 1):
            term = run[index : index + 2]
            if term in ignored:
                continue
            counts[term] = counts.get(term, 0) + 1
    for term in latin_terms:
        counts[term] = counts.get(term, 0) + 1
    ordered = sorted(
        (term for term, count in counts.items() if count >= 2),
        key=lambda term: (-counts[term], -len(term)),
    )
    return ordered[:limit]


def _summarize_chunks(chunks: list[TextChunk]) -> str:
    text = "\n".join(chunk.text for chunk in chunks)
    sentences = _sentences(text)
    chosen: list[str] = []
    keywords = _keywords(text, 6)
    chosen.extend(sentences[:2])
    if len(chosen) < 3 and len(sentences) > 2:
        chosen.append(sentences[2])
    summary = " ".join(dict.fromkeys(chosen))
    if len(summary) > SUMMARY_LIMIT:
        summary = summary[:SUMMARY_LIMIT].rstrip("，；。 ") + "。"
    if keywords:
        summary += " 关键词：" + "、".join(keywords[:5])
    return summary


def chunk_pdf(
    path: Path,
    *,
    chunk_size: int = 800,
    overlap: int = 100,
) -> ParsedDocument:
    if chunk_size < 200:
        raise ValueError("chunk_size 必须至少为 200。")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0 且小于 chunk_size。")

    title, pages = extract_pages(path)
    parts: list[str] = []
    page_spans: list[tuple[int, int, int]] = []
    cursor = 0
    for page_number, page_text in pages:
        normalized = page_text.strip()
        if not normalized:
            continue
        if cursor:
            parts.append("\n\n")
            cursor += 2
        start = cursor
        parts.append(normalized)
        cursor += len(normalized)
        page_spans.append((start, cursor, page_number))
    full_text = "".join(parts).strip()

    chunks: list[TextChunk] = []
    start = 0
    while start < len(full_text):
        maximal_end = min(len(full_text), start + chunk_size)
        end = _best_cut(full_text, start, maximal_end)
        value = full_text[start:end].strip()
        if value:
            page_start, page_end = _page_range(page_spans, start, end)
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    text=value,
                    page_start=page_start,
                    page_end=page_end,
                )
            )
        if end >= len(full_text):
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    segment_summaries: list[TextChunk] = []
    segment_size = 6
    for segment_start in range(0, len(chunks), segment_size):
        segment = chunks[segment_start : segment_start + segment_size]
        summary = _summarize_chunks(segment)
        if summary:
            segment_summaries.append(
                TextChunk(
                    index=len(segment_summaries),
                    text=summary,
                    page_start=min(item.page_start for item in segment),
                    page_end=max(item.page_end for item in segment),
                    kind="summary",
                )
            )

    document_summary = " ".join(item.text for item in segment_summaries)
    if len(document_summary) > 1800:
        document_summary = document_summary[:1800].rstrip() + "…"

    chunks.extend(
        TextChunk(
            index=len(chunks) + offset,
            text=item.text,
            page_start=item.page_start,
            page_end=item.page_end,
            kind="summary",
        )
        for offset, item in enumerate(segment_summaries)
    )

    return ParsedDocument(
        title=title,
        page_count=len(pages),
        text=full_text,
        pages=pages,
        chunks=chunks,
        summary=document_summary,
    )
