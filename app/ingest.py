"""入库：读文件 → 分块 → 向量化 → 存入本地向量库。"""
import os
import re

from pypdf import PdfReader

from app import config, embedding, store


# 中文条款：规章制度里「第X条」是语义自足的最小单元（如「第三条 …」）
_ARTICLE_RE = re.compile(r"第[一二三四五六七八九十百\d]+条")


def _strip_header(text):
    """去掉红头文件的通知头部（红头标题、文号、通知标题、主送、通知套话）。
    正文从第一个「第X条」开始，取该位置往后。没有条款结构的文本原样返回。"""
    m = _ARTICLE_RE.search(text)
    return text[m.start():] if m else text


def _sentence_chunks(text, chunk_size):
    """兜底分块：按中文句末标点切句，贪心合并到接近 chunk_size，保证句子完整。"""
    sentences = [s.strip() for s in re.split(r"(?<=[。；！？])", text) if s.strip()]
    chunks, buf = [], ""
    for s in sentences:
        if not buf:
            buf = s
        elif len(buf) + len(s) <= chunk_size:
            buf += s
        else:
            chunks.append(buf)
            buf = s
    if buf:
        chunks.append(buf)
    return chunks


def split_text(text, chunk_size=None, overlap=None):
    """按「条款」分块：先把换行统一成空格（PDF 的换行是排版换行、不是段落边界），
    再去掉红头文件头部，然后优先按「第X条」切分，每条独立成块。

    为什么按条款而不是按固定字数：
    ① 固定字数会把「住宿标准 500/400/300」「年休假 5/10/15」这种多档条款切碎；
    ② 按字数且块太大时，头部套话会稀释「双休」这类短事实。
    条款是规章制度的自然语义单元，切成整条最聚焦、也不切断。
    没有条款结构的文本退回按句子分块兜底。
    overlap 参数保留仅为兼容，本模式下不再需要。
    """
    chunk_size = chunk_size or config.CHUNK_SIZE
    text = re.sub(r"\s+", " ", text).strip()          # 换行 → 空格
    if not text:
        return []
    text = _strip_header(text)                        # 去红头头部，只索引正文
    articles = [p.strip() for p in re.split(r"(?=" + _ARTICLE_RE.pattern + r")", text) if p.strip()]
    # 全文只有一处条款（或根本没有条款）→ 退回按句子分块
    if len(articles) <= 1:
        return _sentence_chunks(text, chunk_size)
    # 个别超长条款（罕见）→ 对该条再按句子分块兜底
    chunks = []
    for art in articles:
        if len(art) <= chunk_size:
            chunks.append(art)
        else:
            chunks.extend(_sentence_chunks(art, chunk_size))
    return chunks


def ingest_text(text, source):
    """把一段文本入库，返回分块数量。"""
    chunks = split_text(text)
    if not chunks:
        return 0
    vectors = embedding.embed_texts(chunks)
    metadatas = [{"source": source, "chunk": i} for i in range(len(chunks))]
    store.add(chunks, metadatas, vectors)
    return len(chunks)


def ingest_file(filepath):
    """读取一个文本文件并入库。"""
    with open(filepath, encoding="utf-8") as f:
        text = f.read()
    source = os.path.basename(filepath)
    return ingest_text(text, source)


def extract_pdf_text(filepath):
    """用 pypdf 提取 PDF 正文。只支持文字型 PDF；图片型扫描件需 OCR，本项目不做。"""
    reader = PdfReader(filepath)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def ingest_pdf_file(filepath):
    """读取一个 PDF 文件并入库。"""
    text = extract_pdf_text(filepath)
    source = os.path.basename(filepath)
    return ingest_text(text, source)
