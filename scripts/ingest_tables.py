"""一键入库：把 data/ 目录下的 CSV / Excel(.xlsx) 文件导入 SQLite（结构化知识库）。

每个文件按文件名自动建一张表（如 products.xlsx → 表 products），
Agent 会根据问题自己选该查哪张表。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import sql_tool  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def main():
    files = [f for f in os.listdir(DATA_DIR) if f.lower().endswith((".csv", ".xlsx"))]
    if not files:
        print("data/ 目录下没有 .csv 或 .xlsx 文件")
        return
    for name in files:
        path = os.path.join(DATA_DIR, name)
        n = sql_tool.import_table(path)
        print(f"导入完成：{name}，共 {n} 条记录")
    print("当前数据库结构：", sql_tool.get_schema())


if __name__ == "__main__":
    main()
