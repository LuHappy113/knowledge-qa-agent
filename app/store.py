"""向量库：用 numpy 手写存储与余弦相似度检索。

小规模知识库用 numpy 足够，且能讲清"余弦相似度怎么算"的原理。
数据持久化到 store 目录：embeddings.npy（向量矩阵）+ meta.json（文本与元数据）。
"""
import os
import json
import numpy as np
from app import config

# 内存缓存（首次使用时从磁盘加载）
_embeddings = None   # np.ndarray，形状 (N, D)，已归一化
_texts = []
_metadatas = []


def _dir():
    os.makedirs(config.STORE_DIR, exist_ok=True)
    return config.STORE_DIR


def _emb_path():
    return os.path.join(_dir(), "embeddings.npy")


def _meta_path():
    return os.path.join(_dir(), "meta.json")


def load():
    global _embeddings, _texts, _metadatas
    if _embeddings is None and os.path.exists(_emb_path()):
        _embeddings = np.load(_emb_path())
        with open(_meta_path(), encoding="utf-8") as f:
            m = json.load(f)
            _texts = m["texts"]
            _metadatas = m["metadatas"]


def add(documents, metadatas, embeddings):
    global _embeddings
    load()
    arr = np.array(embeddings, dtype=np.float32)
    # 归一化，使点积等于余弦相似度
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms
    if _embeddings is None:
        _embeddings = arr
    else:
        _embeddings = np.vstack([_embeddings, arr])
    _texts.extend(documents)
    _metadatas.extend(metadatas)
    np.save(_emb_path(), _embeddings)
    with open(_meta_path(), "w", encoding="utf-8") as f:
        json.dump({"texts": _texts, "metadatas": _metadatas}, f, ensure_ascii=False)


def count():
    load()
    return 0 if _embeddings is None else len(_embeddings)


def clear():
    """清空向量库（重新入库前调用，避免重复累积旧数据）。"""
    global _embeddings, _texts, _metadatas
    _embeddings = None
    _texts = []
    _metadatas = []
    if os.path.exists(_emb_path()):
        os.remove(_emb_path())
    if os.path.exists(_meta_path()):
        os.remove(_meta_path())


def query(query_embedding, top_n, threshold=0.0):
    """检索 Top-N，返回 (文档片段列表, 相似度列表, 元数据列表)。元数据里带 source（来源文件名）。"""
    load()
    if _embeddings is None or len(_embeddings) == 0:
        return [], [], []
    q = np.array(query_embedding, dtype=np.float32)
    qn = np.linalg.norm(q)
    if qn > 0:
        q = q / qn
    sims = _embeddings @ q          # 归一化后点积 = 余弦相似度
    idx = np.argsort(-sims)          # 按相似度从高到低排序
    docs, scores, metas = [], [], []
    for i in idx:
        s = float(sims[i])
        if s < threshold:
            break                    # 已按降序，后面只会更低，直接截断
        docs.append(_texts[i])
        scores.append(round(s, 4))
        metas.append(_metadatas[i] if _metadatas else {})
        if len(docs) >= top_n:
            break
    return docs, scores, metas
