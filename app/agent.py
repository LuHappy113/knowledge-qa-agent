"""Agent 循环（核心）：大模型用 function calling 自主决定调哪个工具。

流程：把「问题 + 工具说明书」发给 DeepSeek → 模型返回"要调工具/直接答"的决策
→ 若要调工具，代码执行并把结果回传 → 再问模型，直到它给出最终答案或达到最大轮数。
"""
import json

from openai import OpenAI

from app import config, retrieve, sql_tool

SYSTEM_PROMPT = (
    "你是企业内部知识库问答助手。你可以调用以下工具，也可以不调用直接回答：\n"
    "1. vector_search：在【文档知识库】里语义检索，适合查制度、流程、标准等长文本内容；\n"
    "2. sql_query：在【结构化数据库】上执行只读 SELECT，适合查表格数据（通讯录、产品、项目、供应商、资产、会议室、车辆等）。\n\n"
    "规则：\n"
    "- 涉及具体事实（人名、电话、邮箱、价格、负责人、日期、数字、条款等），必须先调用工具查询，禁止凭常识、猜测或上一轮对话里的旧答案直接回答；\n"
    "- 能查到就依据工具结果回答，禁止编造工具结果里没有的信息；\n"
    "- 检索或查询不到相关信息时，直接回答：\"在当前知识库中未查询到相关信息。\"；\n"
    "- 闲聊（问候、自我介绍）不需要调工具，直接回答。"
)


def _schema_desc():
    """把数据库里所有表及列拼成一句话，喂给模型，让它知道能查哪些表、每表有哪些列。"""
    schema = sql_tool.get_schema()
    if not schema:
        return "（暂无可用表）"
    return "；".join(f'表"{t}"（列：{", ".join(cols)}）' for t, cols in schema.items())


def _tool_defs():
    """工具的 JSON 说明书，模型靠它理解每个工具能干什么、要什么参数。"""
    return [
        {
            "type": "function",
            "function": {
                "name": "vector_search",
                "description": "在文档知识库中语义检索，返回最相关的文档片段。适合查规章制度、报销标准、流程说明等长文本内容。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索关键词或问句"},
                        "top_k": {"type": "integer", "description": "返回片段数量，默认 3"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sql_query",
                "description": f"在结构化数据库上执行只读 SELECT 查询。可用表：{_schema_desc()}。适合查某人的邮箱电话、某产品价格、某项目负责人、某会议室容量、某供应商联系人等。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "只读 SELECT 语句，例如 SELECT email FROM contacts WHERE name='张伟'"},
                    },
                    "required": ["sql"],
                },
            },
        },
    ]


def _execute_tool(name, args):
    """真正执行工具，返回 (给模型看的结果文本, 引用来源列表)。

    引用来源是 [{"source": 来源文件名, "text": 原文, "similarity": 相似度}]，
    既喂给模型做引用，也原样返回给前端展示「答案出自哪个文件」。
    """
    try:
        if name == "vector_search":
            docs, sims, metas = retrieve.retrieve(args.get("query", ""), top_n=args.get("top_k", 3))
            if not docs:
                return "未找到相关资料。", []
            parts, refs = [], []
            for i, (d, s, m) in enumerate(zip(docs, sims, metas)):
                src = (m or {}).get("source", "未知文件")
                parts.append(f"[参考{i + 1}]（来源：{src}，相似度 {s}）\n{d}")
                refs.append({"source": src, "text": d, "similarity": s})
            return "\n\n".join(parts), refs

        if name == "sql_query":
            cols, rows = sql_tool.run_query(args.get("sql", ""))
            if not rows:
                return "查询结果为空。", []
            lines = [" | ".join(cols)]
            for r in rows:
                lines.append(" | ".join(str(x) for x in r))
            text = "\n".join(lines)
            return text, [{"source": "通讯录数据库", "text": text, "similarity": None}]

        return "未知工具", []
    except Exception as e:
        # 工具执行出错（如 SQL 写错、参数非法）不崩溃，而是把错误回传给模型，让模型自己改
        return f"工具执行出错：{e}。请检查参数或 SQL 后重新调用。", []


def _client():
    return OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)


def _call_llm(messages, tools=None):
    """调用大模型，带超时与重试（应对偶发超时/限流）。失败抛出最后一次异常，由上层兜底。"""
    client = _client()
    kwargs = {"temperature": 0.3, "timeout": 60}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    last_err = None
    for _ in range(3):
        try:
            return client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,
                **kwargs,
            )
        except Exception as e:
            last_err = e
    raise last_err


def answer(question, history=None):
    """Agent 主循环：返回 {answer, trajectory, sources}。

    history：之前的对话 [{"role": "user"/"assistant", "content": 文本}]，
    拼进上下文，让模型理解「他 / 那条 / 再具体说说」这类指代，实现多轮对话。
    历史由前端每次提问时一并带来（后端保持无状态，谁问的都临时拼一次）。

    sources 是引用来源列表，每项为 {"source": 文件名, "text": 原文, "similarity": 相似度}，
    方便前端展示「答案出自哪个文件、原文是什么」。
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # 把之前的对话历史拼进去（只保留 user/assistant 的纯文本，工具调用细节不入上下文）
    for h in history or []:
        role, content = h.get("role"), h.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    trajectory = []
    sources = []

    for _ in range(config.MAX_AGENT_ROUNDS):
        resp = _call_llm(messages, tools=_tool_defs())
        msg = resp.choices[0].message

        # 模型决定直接回答（不调工具）
        if not msg.tool_calls:
            return {
                "answer": msg.content or "",
                "trajectory": trajectory,
                "sources": sources,
            }

        # 记下 assistant 这轮的"要调工具"决策
        assistant = {"role": "assistant", "content": msg.content or ""}
        assistant["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
        messages.append(assistant)

        # 逐个执行工具，把结果回传给模型
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as e:
                # 模型偶尔给出坏 JSON，不崩溃，回传错误让它重写
                result = f"工具参数不是合法 JSON（{e}），请重新生成。"
                refs = []
                trajectory.append(f"{name}(参数解析失败)")
            else:
                result, refs = _execute_tool(name, args)
                trajectory.append(f"{name}({tc.function.arguments})")
            sources.extend(refs)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # 超过最大轮数：强制用已有信息总结，不再调用工具
    messages.append({"role": "user", "content": "请基于以上所有信息直接给出最终回答，不要再调用工具。"})
    resp = _call_llm(messages)
    return {
        "answer": resp.choices[0].message.content or "",
        "trajectory": trajectory,
        "sources": sources,
    }
