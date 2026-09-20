"""检索：把问题转成向量，在本地向量库里找最相似的 Top-N 片段。

返回三元组 (文档片段列表, 相似度列表, 元数据列表)，元数据里带 source（来源文件名）。
"""
from app import config, embedding, store


def retrieve(question, top_n=None, threshold=None):
    top_n = top_n or config.TOP_N
    threshold = config.SIM_THRESHOLD if threshold is None else threshold
    q_vec = embedding.embed_texts([question])[0]
    return store.query(q_vec, top_n, threshold)
