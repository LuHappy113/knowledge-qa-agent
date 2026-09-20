#!/bin/bash
set -e

# 是否自动执行入库脚本（默认开启，可通过环境变量关闭）
AUTO_INGEST=${AUTO_INGEST:-true}

if [ "$AUTO_INGEST" = "true" ]; then
    echo "==> 正在初始化向量库..."
    python scripts/ingest_demo.py

    echo "==> 正在初始化 SQLite 结构化数据..."
    python scripts/ingest_tables.py
fi

echo "==> 启动 FastAPI 服务..."
exec "$@"
