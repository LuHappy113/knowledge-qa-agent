"""调用大模型（OpenAI 兼容接口，默认 Moonshot/Kimi）。"""
from openai import OpenAI
from app import config


def answer_with_context(question, context_chunks):
    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    context_text = "\n\n".join(
        f"[参考{i + 1}]\n{c}" for i, c in enumerate(context_chunks)
    )
    prompt = (
        "你是企业内部知识库问答助手。请仅依据下面提供的资料回答用户问题。\n"
        "如果资料中没有相关信息，请直接回答：\"在当前知识库中未查询到相关信息。\"，不要编造。\n\n"
        f"【资料】\n{context_text}\n\n"
        f"【用户问题】\n{question}\n\n"
        "【回答】"
    )
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content
