"""查询火山引擎 Ark 上当前 key 可用的模型/接入点列表。"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
base_url = os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

if not api_key:
    print("错误：LLM_API_KEY 未设置，请先配置 .env")
    sys.exit(1)

url = base_url.rstrip("/") + "/models"
headers = {"Authorization": f"Bearer {api_key}"}

try:
    resp = requests.get(url, headers=headers, timeout=30)
    print(f"状态码：{resp.status_code}")
    print(resp.json())
except Exception as e:
    print(f"请求失败：{e}")
