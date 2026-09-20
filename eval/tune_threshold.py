"""阈值调优：不调大模型，只扫检索层，看哪个阈值能同时保证「该命中的命中、该拒答的拒答」。

只跑本地 embedding + numpy 检索，快且免费。
用法：python eval/tune_threshold.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import retrieve  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "questions.json")


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as f:
        return json.load(f)


def contains_all(text, keywords):
    return all(k in (text or "") for k in keywords)


def main():
    qs = load_questions()
    vector_qs = [q for q in qs if q["type"] == "vector"]
    refuse_qs = [q for q in qs if q["type"] == "refuse"]

    print(f"vector 题 {len(vector_qs)} 条 / refuse 题 {len(refuse_qs)} 条\n")
    print("=== 各阈值下：检索命中率 / 拒答率 ===\n")
    thresholds = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
    for t in thresholds:
        vhit = 0
        for q in vector_qs:
            docs, sims, _ = retrieve.retrieve(q["question"], top_n=3, threshold=t)
            if contains_all("".join(docs), q["expected"]):
                vhit += 1
        rok = 0
        for q in refuse_qs:
            docs, sims, _ = retrieve.retrieve(q["question"], top_n=3, threshold=t)
            if not docs:
                rok += 1
        print(f"  阈值 {t:.2f}  ->  检索命中 {vhit}/{len(vector_qs)}    拒答 {rok}/{len(refuse_qs)}")

    # 关键分界点：该命中的题，其「命中片段」的最低相似度；该拒答的题，其「噪声」的最高相似度
    print("\n=== 关键分界点 ===")
    hit_scores = []
    for q in vector_qs:
        docs, sims, _ = retrieve.retrieve(q["question"], top_n=10, threshold=-1.0)
        keep = [s for d, s in zip(docs, sims) if any(k in d for k in q["expected"])]
        if keep:
            hit_scores.append(min(keep))
    noise_scores = []
    for q in refuse_qs:
        docs, sims, _ = retrieve.retrieve(q["question"], top_n=3, threshold=-1.0)
        noise_scores.append(sims[0] if sims else 0.0)

    if hit_scores:
        print(f"  命中片段最低分 = {min(hit_scores):.4f}")
    if noise_scores:
        print(f"  噪声最高分     = {max(noise_scores):.4f}")


if __name__ == "__main__":
    main()
