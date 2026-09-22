# 企业知识库问答 Agent 的 Docker 镜像
# 用法：
#   docker compose up --build -d
# 或手动：
#   docker build -t knowledge-qa-agent:latest .
#   docker run -p 8000:8000 --env-file .env knowledge-qa-agent:latest
FROM python:3.11-slim

WORKDIR /app

# 安装系统级编译依赖（部分 Python 包安装时需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 容器内 Python 行为优化：立即输出日志、不写 .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ONNX 运行时单线程，避免某些 Linux 容器里的初始化问题
ENV OMP_NUM_THREADS=1

# 先单独复制依赖文件，利用 Docker 缓存层加速重建
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

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
# start-period 给足 180 秒，首次启动需要解析 PDF / 生成向量入库，时间可能较长
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

# 启动脚本：负责自动入库 + 启动服务
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
