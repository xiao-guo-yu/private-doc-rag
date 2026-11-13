from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "samples" / "校园私有文档RAG助手.pdf"


def register_chinese_font() -> str:
    candidates = [
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            pdfmetrics.registerFont(TTFont("Chinese", str(candidate)))
            return "Chinese"
    return "Helvetica"


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    font = register_chinese_font()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CNTitle",
        parent=styles["Title"],
        fontName=font,
        fontSize=21,
        leading=30,
        textColor=HexColor("#183D34"),
        alignment=TA_LEFT,
        spaceAfter=18,
    )
    heading_style = ParagraphStyle(
        "CNHeading",
        parent=styles["Heading2"],
        fontName=font,
        fontSize=14,
        leading=22,
        textColor=HexColor("#C85F3A"),
        spaceBefore=12,
        spaceAfter=7,
    )
    body_style = ParagraphStyle(
        "CNBody",
        parent=styles["BodyText"],
        fontName=font,
        fontSize=10.5,
        leading=18,
        textColor=HexColor("#283B34"),
        spaceAfter=9,
    )

    story = [
        Paragraph("校园私有文档 RAG 问答助手", title_style),
        Paragraph(
            "项目周期：2025 年 3 月至 2025 年 6 月。"
            "项目获得校内 AI 应用创新竞赛前十名，校内试用用户超过 100 人。",
            body_style,
        ),
        Paragraph("一、项目背景", heading_style),
        Paragraph(
            "通用大模型无法直接读取用户本地 PDF，而且开放式回答容易出现编造内容、"
            "无法说明出处的问题。团队希望通过检索增强生成，把模型回答限制在用户上传的"
            "文档内容中，并为每一段回答附上可核验的页码和原文片段。",
            body_style,
        ),
        Paragraph(
            "产品的第一目标不是生成一段听起来流畅的文字，而是让用户能够快速判断"
            "“这句话从哪里来”。因此引用、召回片段和未知问题拒答都属于核心功能。",
            body_style,
        ),
        Paragraph("二、团队分工", heading_style),
        Paragraph(
            "本人负责 Vue3 与 TypeScript 前端、FastAPI 后端、SSE 流式输出以及整体接口联调。"
            "团队共同完成检索方案、提示词约束、测试和校内推广。",
            body_style,
        ),
        Paragraph(
            "前端需要展示文档库、聊天对话、引用来源和流式状态。后端负责 PDF 解析、"
            "切块、向量写入、Top-K 检索、上下文拼接以及大模型调用。",
            body_style,
        ),
        Paragraph("三、检索方案", heading_style),
        Paragraph(
            "PDF 文本按 800 字切片，相邻切片保留 100 字重叠，减少跨段落信息被截断的问题。"
            "每个切片连同文档 ID、文件名、起止页码和切片序号写入 Chroma。",
            body_style,
        ),
        Paragraph(
            "用户提问后，系统对问题进行向量化并使用余弦相似度召回首轮 Top-K 片段。"
            "检索结果会进行去重和轻量重排，再把最相关的上下文拼接进 Prompt。",
            body_style,
        ),
        Paragraph(
            "Prompt 强制要求模型只依据资料回答，在每个事实后使用 [1]、[2] 这样的编号引用，"
            "资料不足时必须说明不知道，不能自行补充外部事实。",
            body_style,
        ),
        PageBreak(),
        Paragraph("四、长文档处理", heading_style),
        Paragraph(
            "对于长文档，系统把连续切片组合成分段摘要。宽泛问题可以优先使用摘要块提供"
            "全局背景，具体问题则使用原始切片保证细节和引用页码。上下文总长度受限，"
            "避免把整份文档无差别塞进模型。",
            body_style,
        ),
        Paragraph(
            "切片按页边界记录来源，因此回答中的引用不仅能够回到文档，还可以定位到具体页码。"
            "检索面板同时显示相关度和原文摘录，方便用户快速人工复核。",
            body_style,
        ),
        Paragraph("五、流式交互", heading_style),
        Paragraph(
            "后端使用 Server-Sent Events 逐段返回生成内容。相比一次性等待完整回答，"
            "流式输出让用户更早看到首字，降低等待焦虑，也可以随时停止生成。",
            body_style,
        ),
        Paragraph(
            "在校内测试环境中，首字延迟约为 1 秒。读取 PDF、切块和建立索引属于异步任务，"
            "前端通过任务状态展示当前阶段和处理进度。",
            body_style,
        ),
        Paragraph("六、测试与迭代", heading_style),
        Paragraph(
            "项目完成了三轮主要交互迭代。第一轮解决文档上传和基础问答；第二轮增加引用"
            "来源、页码和检索片段面板；第三轮优化流式输出、错误状态和长文档摘要。",
            body_style,
        ),
        Paragraph(
            "校内 100 多名试用用户参与了测试。反馈集中在三个方向：回答必须可核验，"
            "引用需要容易打开，系统应明确告知文档中找不到答案，而不是继续生成。",
            body_style,
        ),
        PageBreak(),
        Paragraph("七、隐私与边界", heading_style),
        Paragraph(
            "本项目面向私有资料问答。上传文件与向量索引默认保存在本机 data 目录。"
            "启用在线大模型时，只有经过检索筛选的相关片段会作为上下文发送给模型，"
            "不会上传整个文档库。",
            body_style,
        ),
        Paragraph(
            "系统不能保证回答自动正确。引用机制的目标是降低核验成本，而不是替代人工判断。"
            "对于医疗、法律、财务等高风险内容，仍需要领域专家复核。",
            body_style,
        ),
        Paragraph("八、当前限制", heading_style),
        Paragraph(
            "当前版本只支持可提取文本的 PDF。扫描版 PDF 需要先进行 OCR。"
            "默认本地模式使用确定性哈希向量和原文摘录回答；配置兼容 OpenAI 接口的"
            "大模型后，可以获得更好的归纳与跨段推理能力。",
            body_style,
        ),
        Paragraph(
            "后续可增加 OCR、权限控制、文档版本、团队空间、回答质量评测、"
            "混合检索和更强的引用一致性校验。",
            body_style,
        ),
    ]

    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title="校园私有文档 RAG 问答助手",
        author="私有文档 RAG 项目组",
    )
    document.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
