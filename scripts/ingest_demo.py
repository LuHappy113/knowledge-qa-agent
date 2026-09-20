"""一键入库：把 data/ 目录下的 TXT / PDF 文件导入向量库（每次先清空再重建，避免重复）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import ingest, store  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def main():
    files = [f for f in os.listdir(DATA_DIR) if f.endswith((".txt", ".pdf"))]
    if not files:
        print("data/ 目录下没有 .txt 或 .pdf 文件")
        return
    store.clear()  # 清空旧数据，重新入库，防止重复累积
    for name in files:
        path = os.path.join(DATA_DIR, name)
        if name.endswith(".pdf"):
            n = ingest.ingest_pdf_file(path)
        else:
            n = ingest.ingest_file(path)
        print(f"入库完成：{name}，共 {n} 个分块")


if __name__ == "__main__":
    main()
