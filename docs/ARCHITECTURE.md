# 架构说明

## 请求链路

```text
PDF 上传
  → PyMuPDF 提取文本与页码
  → 800 字切片 / 100 字重叠
  → 每 6 个切片生成一段摘要
  → 本地向量化
  → Chroma 持久化

用户提问
  → 查询扩展
  → Chroma Top-K 召回
  → 去重与轻量重排
  → 拼接受限上下文
  → 在线模型 / 本地摘录
  → SSE token 流
  → 引用、页码、延迟事件
```

## SSE 事件

| 事件 | 内容 |
| --- | --- |
| `meta` | 回答模式、模型、文档数与召回数 |
| `retrieval` | 命中的片段、页码与相关度 |
| `citations` | 回答引用列表 |
| `token` | 增量文本 |
| `warning` | 在线模型失败后切换到本地模式 |
| `done` | 总延迟、首字延迟、引用数 |
| `error` | 不可恢复错误 |

## 默认检索参数

- 切片长度：800 字符
- 相邻重叠：100 字符
- 默认 Top-K：5
- 候选池：Top-K × 4，至少 16
- 上下文上限：12,000 字符

参数可通过 `.env` 中的 `RAG_CHUNK_SIZE`、`RAG_CHUNK_OVERLAP`、`RAG_TOP_K` 和 `RAG_MAX_CONTEXT_CHARS` 修改。

## 本地向量设计

`HashEmbedding` 将中文单字、双字、三字组合以及英文词哈希到 768 维向量并做 L2 归一化。优点是无需下载模型、启动稳定、结果可复现；它仍是实际文本检索，而非随机占位。

生产升级时可保持 `VectorStore` 和 `RagEngine` 接口不变，只替换 embedding 实现。
