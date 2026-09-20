"""评估脚本：跑一遍测试集，统计三个指标。

- 检索命中率：vector 类问题，检索到的片段里是否含答案关键词；
- 答案正确率：vector / sql 类问题，最终回答是否含答案关键词；
- 拒答准确率：refuse 类问题，该拒答的是否真的拒答了。

用法：python eval/evaluate.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import agent  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "questions.json")

REFUSE_PHRASES = ["未查询到", "未找到", "没有找到", "没有相关信息", "无法", "不能提供", "只能", "仅能"]


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as f:
        return json.load(f)


def is_refuse(text):
    return any(p in (text or "") for p in REFUSE_PHRASES)


def contains_all(text, keywords):
    """关键词全部命中才算对（AND 逻辑，比 OR 更严格）。"""
    return all(k in (text or "") for k in keywords)


def main():
    qs = load_questions()
    rows = []

    for q in qs:
        r = agent.answer(q["question"])
        answer = r["answer"] or ""
        sources_text = "\n".join(
            s["text"] if isinstance(s, dict) else s for s in r["sources"]
        )
        q_type = q["type"]
        expected = q.get("expected", [])

        if q_type == "refuse":
            ok = is_refuse(answer)
            verdict = "正确拒答" if ok else "该拒答却没拒"
        elif q_type == "chat":
            ok = len(answer.strip()) > 0
            verdict = "已回应" if ok else "无回应"
        else:
            ok = contains_all(answer, expected)
            verdict = "正确" if ok else "错误"

        # vector 类额外算检索命中（检索片段是否含答案关键词）
        hit = None
        if q_type == "vector":
            hit = contains_all(sources_text, expected)

        rows.append({
            "question": q["question"], "type": q_type, "ok": ok, "verdict": verdict,
            "hit": hit, "answer": answer.strip()[:50], "trajectory": r["trajectory"],
        })
        print(f"[{verdict}] ({q_type}) {q['question']}")

    # 汇总
    vector = [r for r in rows if r["type"] == "vector"]
    sql = [r for r in rows if r["type"] == "sql"]
    refuse = [r for r in rows if r["type"] == "refuse"]

    vector_sql_ok = sum(r["ok"] for r in vector + sql)
    vector_hit = sum(r["hit"] for r in vector if r["hit"] is not None)
    refuse_ok = sum(r["ok"] for r in refuse)

    print("\n========== 评估结果 ==========")
    print(f"测试集共 {len(qs)} 条（vector {len(vector)} / sql {len(sql)} / refuse {len(refuse)} / chat {len(qs)-len(vector)-len(sql)-len(refuse)}）")
    print(f"检索命中率：{vector_hit}/{len(vector)} = {vector_hit/len(vector)*100:.1f}%")
    print(f"答案正确率：{vector_sql_ok}/{len(vector)+len(sql)} = {vector_sql_ok/(len(vector)+len(sql))*100:.1f}%")
    print(f"拒答准确率：{refuse_ok}/{len(refuse)} = {refuse_ok/len(refuse)*100:.1f}%")

    # 失败的题单独列出，方便调
    bad = [r for r in rows if not r["ok"]]
    if bad:
        print("\n-- 未通过的题 --")
        for r in bad:
            print(f"  {r['question']}  →  {r['answer']}")


if __name__ == "__main__":
    main()
