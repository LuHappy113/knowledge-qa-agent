"""配置：从 .env 读取，改配置不用改代码。"""
import os
from dotenv import load_dotenv

load_dotenv()

# 大模型：支持任意 OpenAI 兼容接口（DeepSeek、Moonshot/Kimi、OpenAI 等）
# 旧变量名 DEEPSEEK_* 仍兼容读取，但推荐使用通用 LLM_* 变量
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Embedding
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")

# 分块 / 检索
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "400"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
TOP_N = int(os.getenv("TOP_N", "3"))
# 相似度阈值：0.5 在制度条款与放假通知等场景中更均衡。
# 评估集原始扫描结果（条款类）噪声最高 0.4998、命中最低 0.5368，但节日通知类
# 短 query（如"国庆节时"）命中分数会落在 0.55~0.60 区间，0.6 会导致漏检。
# 配合 retrieve.py 的关键词重排，可在放宽阈值的同时抑制不相关结果上浮。
SIM_THRESHOLD = float(os.getenv("SIM_THRESHOLD", "0.5"))

# 向量库（numpy 本地存储目录）
STORE_DIR = os.getenv("STORE_DIR", "./vector_store")

# SQLite（结构化数据，如通讯录）
SQLITE_PATH = os.getenv("SQLITE_PATH", "./sqlite_db/contacts.db")

# Agent 循环
MAX_AGENT_ROUNDS = int(os.getenv("MAX_AGENT_ROUNDS", "3"))
