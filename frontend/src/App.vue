<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { marked } from "marked";
import DOMPurify from "dompurify";
import {
  deleteDocument,
  getDocuments,
  getHealth,
  getJob,
  streamChat,
  uploadPdf,
  type ChatDone,
  type ChatHistoryItem,
  type ChatMeta,
  type Citation,
  type DocumentItem,
  type HealthResponse,
  type RetrievalHit,
} from "./lib/api";

marked.setOptions({ gfm: true, breaks: true });

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  hits: RetrievalHit[];
  meta?: ChatMeta;
  timing?: ChatDone;
  pending?: boolean;
  error?: string;
}

interface UploadState {
  active: boolean;
  filename: string;
  progress: number;
  stage: string;
}

const health = ref<HealthResponse | null>(null);
const documents = ref<DocumentItem[]>([]);
const selectedDocumentIds = ref<string[]>([]);
const messages = ref<ChatMessage[]>([]);
const question = ref("");
const topK = ref(5);
const streaming = ref(false);
const backendError = ref("");
const upload = ref<UploadState>({
  active: false,
  filename: "",
  progress: 0,
  stage: "",
});
const activeCitations = ref<Citation[]>([]);
const activeHits = ref<RetrievalHit[]>([]);
const activeSourceMessageId = ref("");
const activeCitation = ref<Citation | null>(null);
const dragging = ref(false);
const sourcesOpen = ref(false);
const toast = ref("");
const chatScroller = ref<HTMLElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const textarea = ref<HTMLTextAreaElement | null>(null);
let streamController: AbortController | null = null;
let toastTimer: number | null = null;
let pollTimer: number | null = null;

const examples = [
  "概括这份文档的核心结论，并标注来源。",
  "项目用了哪些技术栈？分别解决什么问题？",
  "列出关键指标、数据和时间节点。",
  "文档里有哪些风险、限制或待改进项？",
];

const allSelected = computed(
  () =>
    documents.value.length > 0 &&
    selectedDocumentIds.value.length === documents.value.length,
);
const storeLabel = computed(() =>
  health.value?.vector_backend === "chroma" ? "Chroma" : "本地备用索引",
);
const providerLabel = computed(() =>
  health.value?.provider === "llm" ? "大模型在线" : "本地摘录模式",
);
const canSend = computed(
  () =>
    question.value.trim().length > 0 &&
    !streaming.value &&
    documents.value.length > 0 &&
    selectedDocumentIds.value.length > 0,
);

onMounted(async () => {
  await refreshData();
});

watch(question, () => {
  const element = textarea.value;
  if (!element) return;
  element.style.height = "auto";
  element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
});

async function refreshData() {
  backendError.value = "";
  try {
    const [nextHealth, nextDocuments] = await Promise.all([
      getHealth(),
      getDocuments(),
    ]);
    health.value = nextHealth;
    documents.value = nextDocuments.items;
    topK.value = nextHealth.top_k;
    const available = new Set(nextDocuments.items.map((item) => item.id));
    const retained = selectedDocumentIds.value.filter((id) =>
      available.has(id),
    );
    selectedDocumentIds.value =
      retained.length > 0 ? retained : nextDocuments.items.map((item) => item.id);
  } catch (error) {
    backendError.value =
      error instanceof Error ? error.message : "无法连接后端服务";
  }
}

function notify(message: string) {
  toast.value = message;
  if (toastTimer !== null) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.value = "";
  }, 3000);
}

function toggleDocument(documentId: string) {
  const index = selectedDocumentIds.value.indexOf(documentId);
  if (index >= 0) {
    selectedDocumentIds.value.splice(index, 1);
  } else {
    selectedDocumentIds.value.push(documentId);
  }
}

function toggleAllDocuments() {
  selectedDocumentIds.value = allSelected.value
    ? []
    : documents.value.map((item) => item.id);
}

function openFilePicker() {
  fileInput.value?.click();
}

async function onFileInput(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  if (files.length) await handleFiles(files);
}

function onDrop(event: DragEvent) {
  dragging.value = false;
  const files = Array.from(event.dataTransfer?.files ?? []);
  if (files.length) void handleFiles(files);
}

async function handleFiles(files: File[]) {
  if (upload.value.active) return;
  const pdfs = files.filter(
    (file) =>
      file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"),
  );
  if (!pdfs.length) {
    notify("请选择 PDF 文件。");
    return;
  }
  for (const file of pdfs) {
    await uploadOne(file);
  }
}

async function uploadOne(file: File) {
  upload.value = {
    active: true,
    filename: file.name,
    progress: 4,
    stage: "上传 PDF",
  };
  try {
    const result = await uploadPdf(file);
    upload.value.progress = 12;
    upload.value.stage = "创建索引任务";
    await pollUntilComplete(result.job_id);
  } catch (error) {
    notify(error instanceof Error ? error.message : "上传失败");
  } finally {
    upload.value.active = false;
    if (pollTimer !== null) {
      window.clearInterval(pollTimer);
      pollTimer = null;
    }
  }
}

async function pollUntilComplete(jobId: string) {
  while (true) {
    const job = await getJob(jobId);
    upload.value = {
      active: true,
      filename: upload.value.filename,
      progress: job.progress,
      stage: job.stage,
    };
    if (job.status === "completed") {
      await refreshData();
      if (job.document_id && !selectedDocumentIds.value.includes(job.document_id)) {
        selectedDocumentIds.value.push(job.document_id);
      }
      notify("文档已切块并写入向量库。");
      return;
    }
    if (job.status === "failed") {
      throw new Error(job.error || "文档索引失败。");
    }
    await new Promise<void>((resolve) => {
      pollTimer = window.setTimeout(resolve, 500);
    });
  }
}

async function removeDocument(item: DocumentItem) {
  if (!window.confirm(`删除「${item.filename}」及其全部索引？`)) return;
  try {
    await deleteDocument(item.id);
    selectedDocumentIds.value = selectedDocumentIds.value.filter(
      (id) => id !== item.id,
    );
    await refreshData();
    notify("文档已删除。");
  } catch (error) {
    notify(error instanceof Error ? error.message : "删除失败");
  }
}

function useExample(prompt: string) {
  question.value = prompt;
  textarea.value?.focus();
}

function buildHistory(): ChatHistoryItem[] {
  return messages.value
    .filter((message) => !message.error && message.content.trim())
    .slice(-6)
    .map((message) => ({
      role: message.role,
      content: message.content,
    }));
}

async function sendQuestion() {
  if (!canSend.value) {
    if (!documents.value.length) notify("请先上传一份 PDF。");
    else if (!selectedDocumentIds.value.length) notify("请至少选择一份文档。");
    return;
  }
  const text = question.value.trim();
  const history = buildHistory();
  const userMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: text,
    citations: [],
    hits: [],
  };
  const assistantMessage: ChatMessage = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: "",
    citations: [],
    hits: [],
    pending: true,
  };
  messages.value.push(userMessage, assistantMessage);
  question.value = "";
  streaming.value = true;
  activeCitation.value = null;
  activeCitations.value = [];
  activeHits.value = [];
  activeSourceMessageId.value = assistantMessage.id;
  streamController = new AbortController();
  await scrollToBottom();

  try {
    await streamChat(
      {
        question: text,
        document_ids: selectedDocumentIds.value,
        top_k: topK.value,
        history,
      },
      {
        onMeta(meta) {
          assistantMessage.meta = meta;
        },
        onRetrieval(hits) {
          assistantMessage.hits = hits;
          activeHits.value = hits;
          activeCitations.value = assistantMessage.citations;
          sourcesOpen.value = true;
        },
        onCitations(citations) {
          assistantMessage.citations = citations;
          activeCitations.value = citations;
          activeCitation.value = citations[0] ?? null;
        },
        onToken(token) {
          assistantMessage.pending = false;
          assistantMessage.content += token;
          void scrollToBottom();
        },
        onWarning(message) {
          notify(message);
        },
        onDone(timing) {
          assistantMessage.timing = timing;
          assistantMessage.pending = false;
        },
      },
      streamController.signal,
    );
  } catch (error) {
    if ((error as Error).name !== "AbortError") {
      assistantMessage.error =
        error instanceof Error ? error.message : "请求失败";
      assistantMessage.content ||= "回答生成失败，请检查后端服务。";
      notify(assistantMessage.error);
    } else {
      assistantMessage.content ||= "已停止生成。";
    }
    assistantMessage.pending = false;
  } finally {
    streaming.value = false;
    streamController = null;
    void scrollToBottom();
  }
}

function stopGeneration() {
  streamController?.abort();
}

function clearConversation() {
  if (streaming.value) stopGeneration();
  messages.value = [];
  activeCitations.value = [];
  activeHits.value = [];
  activeCitation.value = null;
  activeSourceMessageId.value = "";
}

function showMessageSources(message: ChatMessage, citation?: Citation) {
  activeSources.value = message.citations;
  activeHits.value = message.hits;
  activeSourceMessageId.value = message.id;
  activeCitation.value = citation ?? message.citations[0] ?? null;
  sourcesOpen.value = true;
}

const activeSources = computed({
  get: () => activeCitations.value,
  set: (value: Citation[]) => {
    activeCitations.value = value;
  },
});

async function scrollToBottom() {
  await nextTick();
  const element = chatScroller.value;
  if (!element) return;
  element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
}

function renderMarkdown(content: string): string {
  const raw = marked.parse(content, { async: false }) as string;
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function documentPages(citation: Citation): string {
  return citation.page_start === citation.page_end
    ? `第 ${citation.page_start} 页`
    : `第 ${citation.page_start}–${citation.page_end} 页`;
}

function firstTokenLabel(timing?: ChatDone): string {
  if (!timing || timing.first_token_ms == null) return "已完成";
  return `首字 ${(timing.first_token_ms / 1000).toFixed(2)}s`;
}
</script>

<template>
  <div class="app-shell">
    <aside class="library-panel">
      <header class="brand">
        <div class="brand-mark"><span>页</span></div>
        <div>
          <h1>页知</h1>
          <p>PRIVATE DOCUMENT RAG</p>
        </div>
      </header>

      <div class="workspace-selector">
        <span class="workspace-dot"></span>
        <div>
          <strong>我的资料库</strong>
          <small>{{ documents.length }} 份文档 · {{ health?.chunks ?? 0 }} 个切片</small>
        </div>
        <span class="workspace-caret">⌄</span>
      </div>

      <div
        class="upload-zone"
        :class="{ dragging, uploading: upload.active }"
        @click="openFilePicker"
        @dragenter.prevent="dragging = true"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,application/pdf"
          multiple
          hidden
          @change="onFileInput"
        />
        <template v-if="upload.active">
          <div class="upload-row">
            <span class="upload-spinner"></span>
            <div>
              <strong>{{ upload.filename }}</strong>
              <small>{{ upload.stage }} · {{ upload.progress }}%</small>
            </div>
          </div>
          <div class="upload-progress">
            <span :style="{ width: `${upload.progress}%` }"></span>
          </div>
        </template>
        <template v-else>
          <div class="upload-icon">＋</div>
          <strong>拖入 PDF，建立私有知识库</strong>
          <span>800 字切块 · 100 字重叠 · 本地存储</span>
        </template>
      </div>

      <div class="library-heading">
        <span>文档</span>
        <button class="text-button" @click="toggleAllDocuments">
          {{ allSelected ? "取消全选" : "全选" }}
        </button>
      </div>

      <div class="document-list">
        <div v-if="backendError" class="backend-offline">
          <strong>后端未连接</strong>
          <span>{{ backendError }}</span>
        </div>
        <article
          v-for="item in documents"
          :key="item.id"
          class="document-card"
          :class="{
            selected: selectedDocumentIds.includes(item.id),
          }"
          @click="toggleDocument(item.id)"
        >
          <button
            class="document-check"
            :aria-label="`选择 ${item.filename}`"
            @click.stop="toggleDocument(item.id)"
          >
            <span v-if="selectedDocumentIds.includes(item.id)">✓</span>
          </button>
          <div class="pdf-badge">PDF</div>
          <div class="document-copy">
            <strong :title="item.title || item.filename">
              {{ item.title || item.filename }}
            </strong>
            <span>{{ item.pages }} 页 · {{ item.chunks }} 切块 · {{ formatBytes(item.size_bytes) }}</span>
          </div>
          <button
            class="document-delete"
            title="删除文档"
            @click.stop="removeDocument(item)"
          >
            ×
          </button>
        </article>
        <button
          v-if="!documents.length && !backendError"
          class="empty-document"
          @click="openFilePicker"
        >
          <span>还没有文档</span>
          <small>上传第一份 PDF 开始提问</small>
        </button>
      </div>

      <footer class="library-footer">
        <div class="privacy-note">
          <span class="privacy-icon">◫</span>
          <p>
            文档与向量索引保存在本机
            <small>{{ storeLabel }} · data/ 目录</small>
          </p>
        </div>
        <div class="config-line">
          <span>{{ health ? `${health.chunk_size}/${health.chunk_overlap}` : "800/100" }}</span>
          <span>TOP {{ topK }}</span>
          <span>{{ providerLabel }}</span>
        </div>
      </footer>
    </aside>

    <main class="chat-panel">
      <header class="chat-header">
        <div>
          <p class="section-kicker">GROUNDED ANSWERS</p>
          <h2>向你的文档提问</h2>
        </div>
        <div class="header-actions">
          <span
            class="mode-pill"
            :class="{ online: health?.provider === 'llm' }"
          >
            <i></i>{{ providerLabel }}
          </span>
          <button
            class="icon-button source-toggle"
            title="展开引用面板"
            @click="sourcesOpen = !sourcesOpen"
          >
            引
          </button>
          <button
            class="icon-button"
            title="清空对话"
            @click="clearConversation"
          >
            ↺
          </button>
        </div>
      </header>

      <section ref="chatScroller" class="chat-scroll">
        <div v-if="!messages.length" class="welcome-state">
          <div class="welcome-orbit">
            <span class="orbit-dot dot-a"></span>
            <span class="orbit-dot dot-b"></span>
            <span class="welcome-glyph">问</span>
          </div>
          <p class="section-kicker">ASK WITH EVIDENCE</p>
          <h3>每句话，都能回到原文</h3>
          <p class="welcome-copy">
            上传私有 PDF，系统会切块检索、约束回答，并在每个结论旁标出来源页码。
          </p>
          <div class="example-grid">
            <button
              v-for="example in examples"
              :key="example"
              class="example-card"
              @click="useExample(example)"
            >
              <span>↗</span>
              <p>{{ example }}</p>
            </button>
          </div>
          <div class="pipeline-strip">
            <span>PDF</span><i></i><span>800 字切块</span><i></i>
            <span>Chroma Top-K</span><i></i><span>带引用回答</span>
          </div>
        </div>

        <div v-else class="message-list">
          <article
            v-for="message in messages"
            :key="message.id"
            class="message"
            :class="[message.role, { active: activeSourceMessageId === message.id }]"
          >
            <div v-if="message.role === 'assistant'" class="message-avatar">
              页
            </div>
            <div class="message-body">
              <header class="message-meta">
                <span>{{ message.role === "user" ? "你" : "页知" }}</span>
                <span v-if="message.meta" class="answer-mode">
                  {{ message.meta.mode === "llm" ? "流式生成" : "本地摘录" }}
                </span>
                <span v-if="message.timing" class="answer-latency">
                  {{ firstTokenLabel(message.timing) }}
                </span>
              </header>
              <div
                v-if="message.role === 'assistant'"
                class="message-content markdown"
                v-html="renderMarkdown(message.content || (message.pending ? '正在检索文档…' : ''))"
              ></div>
              <div v-else class="message-content user-content">
                {{ message.content }}
              </div>
              <div v-if="message.pending" class="typing-line">
                <span></span><span></span><span></span>
              </div>
              <p v-if="message.error" class="message-error">
                {{ message.error }}
              </p>
              <footer
                v-if="message.role === 'assistant' && message.citations.length"
                class="message-sources"
              >
                <button
                  v-for="citation in message.citations.slice(0, 4)"
                  :key="citation.index"
                  class="citation-chip"
                  @click="showMessageSources(message, citation)"
                >
                  <b>[{{ citation.index }}]</b>
                  <span>{{ citation.document_name }}</span>
                  <em>{{ documentPages(citation) }}</em>
                </button>
                <button
                  class="all-sources-button"
                  @click="showMessageSources(message)"
                >
                  查看全部 {{ message.citations.length }} 条依据 →
                </button>
              </footer>
            </div>
          </article>
        </div>
      </section>

      <footer class="composer-wrap">
        <div class="selection-line">
          <span>
            <i class="status-dot"></i>
            检索范围：{{ selectedDocumentIds.length ? `${selectedDocumentIds.length} 份文档` : "未选择文档" }}
          </span>
          <label>
            Top-K
            <select v-model.number="topK">
              <option :value="3">3</option>
              <option :value="5">5</option>
              <option :value="8">8</option>
            </select>
          </label>
        </div>
        <div class="composer">
          <textarea
            ref="textarea"
            v-model="question"
            rows="1"
            :disabled="streaming"
            placeholder="询问文档中的事实、指标、结论或差异…"
            @keydown.enter.exact.prevent="sendQuestion"
          ></textarea>
          <div class="composer-tools">
            <button class="attach-button" title="上传 PDF" @click="openFilePicker">
              ＋
            </button>
            <span class="composer-hint">Enter 发送 · Shift + Enter 换行</span>
            <button
              v-if="!streaming"
              class="send-button"
              :disabled="!canSend"
              @click="sendQuestion"
            >
              提问 <span>↑</span>
            </button>
            <button v-else class="send-button stop" @click="stopGeneration">
              停止 <span>■</span>
            </button>
          </div>
        </div>
        <p class="grounding-note">
          回答受检索文档约束；引用编号对应右侧原文片段。
        </p>
      </footer>
    </main>

    <aside class="sources-panel" :class="{ open: sourcesOpen }">
      <header class="sources-header">
        <div>
          <p class="section-kicker">EVIDENCE</p>
          <h2>原文依据</h2>
        </div>
        <button class="icon-button sources-close" @click="sourcesOpen = false">
          ×
        </button>
      </header>

      <template v-if="activeCitations.length">
        <div class="source-summary">
          <strong>{{ activeCitations.length }}</strong>
          <span>个相关片段</span>
          <small>已按相关度排序</small>
        </div>

        <div class="source-tabs">
          <button
            v-for="citation in activeCitations"
            :key="citation.index"
            :class="{ active: activeCitation?.index === citation.index }"
            @click="activeCitation = citation"
          >
            {{ citation.index }}
          </button>
        </div>

        <article
          v-for="citation in activeCitations"
          :key="`card-${citation.index}`"
          v-show="!activeCitation || activeCitation.index === citation.index"
          class="source-card"
        >
          <header>
            <span class="source-index">{{ citation.index }}</span>
            <div>
              <strong>{{ citation.document_name }}</strong>
              <small>{{ documentPages(citation) }} · 切块 {{ citation.chunk_index }}</small>
            </div>
          </header>
          <div class="source-score">
            <span>相关度</span>
            <div><i :style="{ width: `${Math.max(8, citation.score * 100)}%` }"></i></div>
            <strong>{{ Math.round(citation.score * 100) }}%</strong>
          </div>
          <blockquote>{{ citation.snippet }}</blockquote>
          <footer>
            <span>{{ citation.document_id.slice(0, 8) }}</span>
            <span>{{ activeHits.find((hit) => hit.rank === citation.index)?.score.toFixed(3) ?? "—" }}</span>
          </footer>
        </article>
      </template>

      <div v-else class="sources-empty">
        <div class="empty-crosshair"><span></span></div>
        <h3>引用会出现在这里</h3>
        <p>提出第一个问题后，可以在这里逐条核对文档名称、页码、相关度和原文片段。</p>
        <dl>
          <div><dt>切片</dt><dd>{{ health?.chunk_size ?? 800 }} 字</dd></div>
          <div><dt>重叠</dt><dd>{{ health?.chunk_overlap ?? 100 }} 字</dd></div>
          <div><dt>召回</dt><dd>Top {{ topK }}</dd></div>
          <div><dt>索引</dt><dd>{{ storeLabel }}</dd></div>
        </dl>
      </div>
    </aside>

    <Transition name="toast">
      <div v-if="toast" class="toast-message">{{ toast }}</div>
    </Transition>
  </div>
</template>
