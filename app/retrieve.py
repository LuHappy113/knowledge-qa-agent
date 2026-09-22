"""检索：把问题转成向量，在本地向量库里找最相似的 Top-N 片段。

返回三元组 (文档片段列表, 相似度列表, 元数据列表)，元数据里带 source（来源文件名）。
"""
import re

from app import config, embedding, store


# 检索后关键词重排时过滤的通用停用词
_STOP_WORDS = {
    "什么", "怎么", "多少", "是否", "请问", "查询", "查看", "告诉", "一下",
    "公司", "企业", "集团", "制度", "通知", "安排", "放假", "假期", "节日",
    "放假安排", "放假通知", "工作安排", "值班安排", "调休安排",
    "时候", "时间", "有关", "关于", "如何", "哪里", "哪些", "谁", "哪",
    "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "的", "了", "是", "在", "有", "和", "与", "及", "或", "等", "对", "为",
    "从", "到", "把", "被", "让", "给", "向", "把", "于", "由", "把",
}

# 领域专有实体：用于触发严格过滤，避免"国庆节"问题引用元旦/中秋通知。
# 节日、常见假期类型、以及可动态加载的通讯录人名等。
_DOMAIN_ENTITIES = {
    # 法定节假日 / 节日
    "元旦", "春节", "元宵", "元宵节", "清明", "清明节", "劳动节", "五一",
    "端午", "端午节", "中秋", "中秋节", "国庆", "国庆节", "重阳", "重阳节",
    # 假期类型
    "年休假", "年假", "病假", "事假", "婚假", "产假", "陪产假", "丧假",
    "调休", "加班", "值班", "请假",
    # 制度高频主题
    "考勤", "报销", "差旅", "会议", "培训", "薪酬", "绩效", "福利",
    "消防", "安全", "信息", "网络", "车辆", "用车",
}


def _extract_keywords(question):
    """从问题中提取关键词，用于检索后重排与过滤。

    不依赖外部分词库：
    - 英文/数字取完整单词；
    - 中文用 2~4 字滑动窗口提取，避免"国庆节时"只被当成一个整体而无法命中"国庆节"。
    """
    text = question.lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    chars = re.findall(r"[一-鿿]", text)
    for length in (2, 3, 4):
        for i in range(len(chars) - length + 1):
            tokens.append("".join(chars[i:i + length]))

    seen = set()
    keywords = []
    for t in tokens:
        if t in _STOP_WORDS or len(t) < 2 or t in seen:
            continue
        seen.add(t)
        keywords.append(t)
    return keywords


def _rerank_by_keywords(docs, scores, metas, question, boost=0.04):
    """对向量检索结果做关键词命中重排，并在有把握时做严格过滤。

    向量相似度解决"语义相关"，关键词命中解决"精确匹配"。
    例如问"国庆节"时，包含"国庆节"的放假通知应排在只含"元旦"的通知前面；
    如果排名第一的结果已明确命中"国庆节"这类领域实体，则把不含该实体的结果过滤掉，
    避免"国庆节"问题反而引用元旦/中秋通知。
    """
    keywords = _extract_keywords(question)
    if not keywords:
        return docs, scores, metas

    q = question.lower()

    # 问题中出现了哪些领域实体（如"国庆"、"年休假"）
    domain_in_question = {e for e in _DOMAIN_ENTITIES if e in q}

    def hits(text):
        t = text.lower()
        return [k for k in keywords if k in t]

    results = []
    for d, s, m in zip(docs, scores, metas):
        kh = hits(d)
        adjusted = s + boost * len(kh)
        results.append({"doc": d, "score": s, "meta": m, "hits": kh, "adjusted": adjusted})

    results.sort(key=lambda x: x["adjusted"], reverse=True)

    # 当 top1 命中了问题中的某个领域实体时，启用严格过滤
    if domain_in_question and results:
        top1_text = results[0]["doc"].lower()
        triggered = {e for e in domain_in_question if e in top1_text}
        if triggered:
            filtered = [r for r in results if any(e in r["doc"].lower() for e in triggered)]
            if filtered:
                results = filtered

    return [r["doc"] for r in results], [r["score"] for r in results], [r["meta"] for r in results]


def retrieve(question, top_n=None, threshold=None):
    top_n = top_n or config.TOP_N
    threshold = config.SIM_THRESHOLD if threshold is None else threshold
    q_vec = embedding.embed_texts([question])[0]
    # 先多召回一倍候选，让关键词重排有选择空间，最终仍只返回 top_n 个
    docs, scores, metas = store.query(q_vec, top_n * 2, threshold)
    if not docs:
        return [], [], []
    docs, scores, metas = _rerank_by_keywords(docs, scores, metas, question)
    return docs[:top_n], scores[:top_n], metas[:top_n]
