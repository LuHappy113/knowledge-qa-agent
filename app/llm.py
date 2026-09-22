"""调用大模型（OpenAI 兼容接口，默认 Moonshot/Kimi）。"""
from openai import OpenAI
from app import config


def answer_with_context(question, context_chunks):
    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    context_text = "\n\n".join(
        f"[参考{i + 1}]\n{c}" for i, c in enumerate(context_chunks)
    )
    prompt = (
        "你是华辰集团企业智能问答助手。请仅依据下面提供的集团内部资料回答员工问题。\n"
        "回答应专业、简洁、准确，优先使用条目、表格等清晰格式。\n"
        "如果资料中没有相关信息，请直接回答：\"在当前知识库中未查询到相关信息，建议您联系相关部门确认。\"，禁止编造。\n\n"
        f"【参考资料】\n{context_text}\n\n"
        f"【员工问题】\n{question}\n\n"
        "【回答】"
    )
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content
