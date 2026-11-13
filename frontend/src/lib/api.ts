export interface HealthResponse {
  status: string;
  provider: "llm" | "extractive";
  vector_backend: string;
  documents: number;
  chunks: number;
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
}

export interface DocumentItem {
  id: string;
  filename: string;
  title: string | null;
  size_bytes: number;
  pages: number;
  chunks: number;
  status: string;
  summary: string;
  created_at: string;
}

export interface DocumentListResponse {
  items: DocumentItem[];
  total_pages: number;
  total_chunks: number;
}

export interface UploadResponse {
  job_id: string;
  filename: string;
  status: string;
}

export interface JobStatusResponse {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  stage: string;
  document_id: string | null;
  error: string | null;
}

export interface Citation {
  index: number;
  document_id: string;
  document_name: string;
  page_start: number;
  page_end: number;
  chunk_index: number;
  score: number;
  snippet: string;
}

export interface RetrievalHit extends Citation {
  rank: number;
}

export interface ChatMeta {
  mode: "llm" | "extractive";
  provider: string;
  model: string | null;
  documents_selected: number;
  retrieved: number;
}

export interface ChatDone {
  latency_ms: number;
  first_token_ms: number;
  citations: number;
  answer_chars?: number;
}

export interface ChatHistoryItem {
  role: "user" | "assistant";
  content: string;
}

export interface StreamCallbacks {
  onMeta?: (meta: ChatMeta) => void;
  onRetrieval?: (hits: RetrievalHit[]) => void;
  onCitations?: (citations: Citation[]) => void;
  onToken?: (text: string) => void;
  onWarning?: (message: string) => void;
  onDone?: (done: ChatDone) => void;
}

export interface ChatPayload {
  question: string;
  document_ids: string[];
  top_k: number;
  history: ChatHistoryItem[];
}

async function readError(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const data = await response.json();
    return typeof data.detail === "string" ? data.detail : fallback;
  } catch {
    return fallback;
  }
}

async function jsonRequest<T>(
  url: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return jsonRequest<HealthResponse>("/api/health");
}

export function getDocuments(): Promise<DocumentListResponse> {
  return jsonRequest<DocumentListResponse>("/api/documents");
}

export async function uploadPdf(file: File): Promise<UploadResponse> {
  const data = new FormData();
  data.append("file", file);
  return jsonRequest<UploadResponse>("/api/documents/upload", {
    method: "POST",
    body: data,
  });
}

export function getJob(jobId: string): Promise<JobStatusResponse> {
  return jsonRequest<JobStatusResponse>(`/api/jobs/${jobId}`);
}

export async function deleteDocument(documentId: string): Promise<void> {
  const response = await fetch(`/api/documents/${documentId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
}

function parseEvent(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!dataLines.length) {
    return null;
  }
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

export async function streamChat(
  payload: ChatPayload,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  if (!response.body) {
    throw new Error("浏览器未提供流式响应体。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      const parsed = parseEvent(block);
      if (parsed) {
        switch (parsed.event) {
          case "meta":
            callbacks.onMeta?.(parsed.data as ChatMeta);
            break;
          case "retrieval":
            callbacks.onRetrieval?.(
              (parsed.data as { hits: RetrievalHit[] }).hits ?? [],
            );
            break;
          case "citations":
            callbacks.onCitations?.(
              (parsed.data as { citations: Citation[] }).citations ?? [],
            );
            break;
          case "token":
            callbacks.onToken?.((parsed.data as { text: string }).text ?? "");
            break;
          case "warning":
            callbacks.onWarning?.(
              (parsed.data as { message: string }).message,
            );
            break;
          case "done":
            callbacks.onDone?.(parsed.data as ChatDone);
            break;
          case "error":
            throw new Error((parsed.data as { message: string }).message);
          default:
            break;
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      break;
    }
  }
}
