"""Agent 循环（核心）：大模型用 function calling 自主决定调哪个工具。

流程：把「问题 + 工具说明书」发给大模型 → 模型返回"要调工具/直接答"的决策
→ 若要调工具，代码执行并把结果回传 → 再问模型，直到它给出最终答案或达到最大轮数。
"""
import json
import re

from openai import OpenAI

from app import config, retrieve, sql_tool

SYSTEM_PROMPT = (
    "你是华辰集团企业智能问答助手，专为集团员工提供制度查询、流程指引、公共资源及基础人事信息服务。\n\n"
    "【服务范围】\n"
    "- 企业制度：考勤管理、差旅报销、费用报销、会议管理、员工培训、薪酬福利、信息安全、消防安全、公务用车等；\n"
    "- 行政通知：放假安排、办公区搬迁、系统维护、门禁启用、人事任免、表彰通报等；\n"
    "- 公共资源：会议室、公务车辆、固定资产、产品目录、供应商名录、项目台账等；\n"
    "- 基础人事：员工姓名、所属部门、岗位职务、企业邮箱等公开信息。\n\n"
    "【可调用工具】\n"
    "1. vector_search：在制度文档库中进行语义检索，适用于查询规章制度、管理办法、流程说明、行政通知等长文本内容；\n"
    "2. sql_query：在结构化数据库中执行只读 SELECT 查询，适用于查询通讯录、会议室、车辆、项目、供应商、资产等表格数据。\n\n"
    "【工作准则】\n"
    "- 涉及具体事实（如人名、部门、日期、金额、条款、负责人、联系方式等），必须先调用工具查询，禁止凭常识、记忆或推测回答；\n"
    "- 能查到信息时，应清晰、准确地回答，并引用工具返回的来源；\n"
    "- 通讯录查询以 sql_query 返回的行数为准：返回几行就是几个人；若只返回 1 行，说明该员工仅此一名，禁止臆测存在同名多人或多部门，也禁止把历史对话里先前的错误说法当作事实延续；\n"
    "- 无法查到相关信息时，明确回答：\"在当前知识库中未查询到相关信息，建议您联系相关部门确认。\"，禁止编造；\n"
    "- 对于员工问候、自我介绍、系统说明等一般性问题，无需调用工具，可直接礼貌回复。"
)


# 无需调用工具即可直接回答的问候/闲聊/系统说明类关键词
_GREETING_PATTERNS = {
    "你好", "您好", "hello", "hi", "嗨", "hey",
    "早上好", "上午好", "下午好", "晚上好",
    "谢谢", "谢谢你", "感谢", "不客气", "再见", "拜拜",
    "你是谁", "你叫什么", "自我介绍一下", "介绍一下", "你能做什么",
    "有什么功能", "怎么用", "可以帮我吗",
}

# 复杂问题特征词：出现这些词通常需要跨文档/跨表/多步查询
_COMPLEX_MARKERS = {
    "对比", "比较", "区别", "差异", "vs", "versus",
    "分别", "各自", "以及", "还有", "另外", "其次",
    "多", "哪些", "所有", "全部", "列出", "汇总", "统计",
}


def _is_greeting(question):
    """判断问题是否属于问候/闲聊/系统说明，可直接回答而无需调用工具。

    只做「整句精确匹配」：问句去掉两端空白/标点后，若恰好等于某个问候短语才算闲聊。
    不做包含匹配、也不按长度猜测——"张伟""李娜"这类两字人名、"国庆""调休"这类
    两字关键词都是真实查询，必须走工具；否则模型无法查到数据，只能凭空编造
    （曾因此把唯一的张伟答成"两个部门"，重启后又答成"查无此人"）。
    """
    q = question.strip().lower().strip(" ?？，,。！!～~")
    if not q:
        return True  # 空输入按闲聊处理，礼貌回应即可
    return q in _GREETING_PATTERNS


def _estimate_complexity(question):
    """根据问题复杂度决定策略。

    返回 (max_rounds, use_tools)：
    - 问候类：1 轮，不调工具；
    - 单事实查询：最多 2 轮，调工具；
    - 多事实/对比/汇总：最多 3 轮，调工具。
    """
    if _is_greeting(question):
        return 1, False

    q = question.lower()
    if any(m in q for m in _COMPLEX_MARKERS):
        return 3, True

    # 默认按单事实处理
    return 2, True


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
    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)


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
                model=config.LLM_MODEL,
                messages=messages,
                **kwargs,
            )
        except Exception as e:
            last_err = e
    raise last_err


def answer(question, history=None):
    """Agent 主循环：返回 {answer, trajectory, sources}。

    根据问题复杂度动态决定最大轮数：
    - 问候/闲聊/系统说明：直接回答，不调工具；
    - 单事实查询（如"国庆放几天"）：最多 2 轮；
    - 多事实/对比/汇总（如"国庆和元旦哪个长"）：最多 3 轮。

    history：之前的对话 [{"role": "user"/"assistant", "content": 文本}]，
    拼进上下文，让模型理解「他 / 那条 / 再具体说说」这类指代，实现多轮对话。
    历史由前端每次提问时一并带来（后端保持无状态，谁问的都临时拼一次）。

    sources 是引用来源列表，每项为 {"source": 文件名, "text": 原文, "similarity": 相似度}，
    方便前端展示「答案出自哪个文件、原文是什么」。
    """
    max_rounds, use_tools = _estimate_complexity(question)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # 把之前的对话历史拼进去（只保留 user/assistant 的纯文本，工具调用细节不入上下文）
    for h in history or []:
        role, content = h.get("role"), h.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    trajectory = []
    sources = []

    # 问候/闲聊类：直接回答，不调工具，1 次 LLM 调用即可
    if not use_tools:
        resp = _call_llm(messages)
        return {
            "answer": resp.choices[0].message.content or "",
            "trajectory": trajectory,
            "sources": sources,
        }

    # 事实查询类：启用 Agent 循环，按复杂度限制最大轮数
    for _ in range(max_rounds):
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
