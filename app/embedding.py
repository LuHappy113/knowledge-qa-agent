"""Embedding：把文字变成向量（本地 ONNX 模型，无需 GPU）。"""
import os

# 必须先于 onnxruntime 加载设置：这台机器上多线程推理会段错误，单线程最稳。
os.environ.setdefault("OMP_NUM_THREADS", "1")

from fastembed import TextEmbedding
from app import config

_embedder = None


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=config.EMBED_MODEL)
    return _embedder


def embed_texts(texts):
    """把一串文本转成向量列表。"""
    model = get_embedder()
    return [e.tolist() for e in model.embed(list(texts))]
