"""FastAPI 入口：/ 聊天界面 + /query 问答接口 + /health 健康检查。"""
import os

from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import agent

app = FastAPI(title="企业知识库问答 Agent")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


class QueryRequest(BaseModel):
    question: str
    history: Optional[list] = None  # 之前对话的 [{role, content}]，用于多轮


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query")
def query(req: QueryRequest):
    try:
        return agent.answer(req.question, req.history)
    except Exception as e:
        # 最后一道防线：即使大模型彻底调用失败，也返回友好提示而不是 500
        return {"answer": f"服务暂时出错，请稍后重试。（{e}）", "trajectory": [], "sources": []}
