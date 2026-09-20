"""结构化数据工具：把 CSV 导入 SQLite，提供只读 SQL 查询。

和向量库互补：表格数据（通讯录/员工名册）用 SQL 精确查，长文本用向量语义检索。
只用 Python 内置的 csv + sqlite3，零额外依赖，且能看清每一行是怎么进表的。
"""
import csv
import os
import sqlite3

from app import config


def _connect():
    os.makedirs(os.path.dirname(config.SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row  # 让结果能按列名取值
    return conn


def _create_table(table_name, columns, rows):
    """建表并插入数据。列都存 TEXT（演示够用），用 ? 占位防注入。"""
    conn = _connect()
    col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    cols = ", ".join(f'"{c}"' for c in columns)
    conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
    conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
    for row in rows:
        values = [str(v) if v is not None else "" for v in row]
        conn.execute(f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders})', values)
    conn.commit()
    conn.close()
    return len(rows)


def import_csv(csv_path, table_name="contacts"):
    """把 CSV 导入 SQLite。CSV 第一行必须是列名，其余每行一条记录。"""
    # utf-8-sig：兼容 Excel 导出的带 BOM 的 CSV，避免第一列表头多出乱码
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = [list(r.values()) for r in reader]
    if not columns or not rows:
        return 0
    return _create_table(table_name, columns, rows)


def import_xlsx(xlsx_path, table_name):
    """把 Excel(.xlsx) 导入 SQLite。取第一个 sheet，第一行是列名，其余是数据。"""
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    raw = list(ws.iter_rows(values_only=True))
    wb.close()
    if not raw:
        return 0
    columns = [str(c).strip() if c is not None else "" for c in raw[0]]
    rows = []
    for r in raw[1:]:
        if not any(c is not None and str(c).strip() != "" for c in r):
            continue  # 跳过空行
        rows.append([str(c) if c is not None else "" for c in r])
    if not rows:
        return 0
    return _create_table(table_name, columns, rows)


def import_table(path, table_name=None):
    """按扩展名自动分派 CSV / XLSX，表名默认取文件名（去扩展名）。"""
    name = table_name or os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return import_csv(path, name)
    if ext == ".xlsx":
        return import_xlsx(path, name)
    raise ValueError(f"不支持的文件类型：{ext}")


def run_query(sql):
    """执行只读 SELECT，返回 (列名列表, 每行列表)。拒绝非 SELECT，防止误改数据。"""
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("只允许 SELECT 查询")
    conn = _connect()
    cur = conn.execute(sql)
    columns = [d[0] for d in cur.description] if cur.description else []
    rows = [list(r) for r in cur.fetchall()]
    conn.close()
    return columns, rows


def get_schema():
    """返回库里有哪些表、每张表有哪些列，供 Agent 决定怎么写 SQL。"""
    conn = _connect()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    schema = {}
    for (t,) in tables:
        cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        schema[t] = [c[1] for c in cols]
    conn.close()
    return schema
