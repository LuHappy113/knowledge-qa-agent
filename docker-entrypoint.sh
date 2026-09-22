#!/bin/bash
set -e

# 是否自动执行入库脚本（默认开启，可通过环境变量关闭）
AUTO_INGEST=${AUTO_INGEST:-true}

# 确保数据目录存在（volume 挂载空目录时也适用）
mkdir -p "${STORE_DIR:-./vector_store}"
mkdir -p "$(dirname "${SQLITE_PATH:-./sqlite_db/contacts.db}")"

if [ "$AUTO_INGEST" = "true" ]; then
    # 仅在向量库为空时执行入库，避免每次重启都清空重建
    if [ ! -f "${STORE_DIR}/embeddings.npy" ] || [ ! -s "${STORE_DIR}/embeddings.npy" ]; then
        echo "==> 向量库为空，正在初始化向量库..."
        python scripts/ingest_demo.py
    else
        echo "==> 向量库已存在，跳过向量入库（如需重建请删除 ${STORE_DIR} 后重启）"
    fi

    # SQLite 同理：只有数据库文件不存在或为空时才重新导入
    if [ ! -f "${SQLITE_PATH}" ] || [ ! -s "${SQLITE_PATH}" ]; then
        echo "==> SQLite 数据库为空，正在初始化结构化数据..."
        python scripts/ingest_tables.py
    else
        echo "==> SQLite 数据库已存在，跳过结构化数据导入"
    fi
fi

echo "==> 启动 FastAPI 服务..."
exec "$@"
