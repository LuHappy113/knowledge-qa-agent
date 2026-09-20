# 企业知识库问答 Agent 的 Docker 镜像
# 注意：本机未装 Docker/WSL，此文件在有 Docker 的环境构建运行。
FROM python:3.11-slim

WORKDIR /app

# 安装系统级编译依赖（部分 Python 包安装时需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 设置 ONNX 运行时单线程，避免某些 Linux 容器里的初始化问题
ENV OMP_NUM_THREADS=1

# 先单独复制依赖文件，利用 Docker 缓存层加速重建
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载 Embedding 模型，避免容器首次启动时下载耗时
# 模型会缓存到 /root/.cache/fastembed，随镜像一起发布
RUN python - <<'PY'
from fastembed import TextEmbedding
_ = list(TextEmbedding(model_name="BAAI/bge-small-zh-v1.5").embed(["预热"]))
PY

# 复制应用代码和演示数据
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY static/ ./static/
COPY eval/ ./eval/
COPY .env.example .

# 创建向量库和 SQLite 目录（运行时会挂载 volume，这里先占位）
RUN mkdir -p vector_store sqlite_db

# 暴露 FastAPI 服务端口
EXPOSE 8000

# 健康检查：服务启动后每 30 秒检查一次 /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# 启动脚本：负责自动入库 + 启动服务
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
