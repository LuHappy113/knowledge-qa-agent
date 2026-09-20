# 企业知识库问答 Agent（RAG + Tool Calling）

一个「真 Agent」：大模型用 function calling **自主决定**调「语义检索」还是「SQL 精确查询」还是「直接回答」，而不是写死的流水线（Chain）。

## 核心能力

- **两类数据、两类工具**：长文本（制度/标准/PDF/TXT）走向量语义检索；结构化表格（通讯录/CSV）走 SQL 精确查询。
- **Agent 自主决策**：DeepSeek 根据问题自己选工具、决定调几次、何时停（最多 5 轮防死循环）。
- **双层防幻觉**：检索层相似度阈值（0.6）拦截无关结果 + 生成层 Prompt 约束，无资料时拒答不编造。
- **可量化评估**：19 条测试集，统计检索命中率 / 答案正确率 / 拒答准确率三项指标（当前均 100%）。

## 架构图

```
                          ┌───────────────────────┐
                          │       用户 / 调用方      │
                          └───────────┬───────────┘
                                      │ POST /query
                          ┌───────────▼───────────┐
                          │   FastAPI（main.py）   │
                          └───────────┬───────────┘
                                      │
                          ┌───────────▼───────────┐
                          │  Agent 循环（agent.py） │
                          │  DeepSeek function     │
                          │  calling 自主决策       │
                          └─────┬───────────┬─────┘
                  ┌─────────────▼───┐   ┌───▼─────────────┐
                  │  vector_search  │   │    sql_query     │
                  │  语义检索(numpy) │   │  精确查询(SQLite) │
                  └───────┬─────────┘   └───┬─────────────┘
                          │                 │
                  ┌───────▼─────────┐   ┌───▼─────────────┐
                  │ 知识库A：长文本   │   │ 知识库B：结构化表  │
                  │ PDF/TXT→分块→向量 │   │ CSV→通讯录       │
                  │ (bge-small-zh)   │   └─────────────────┘
                  └─────────────────┘
```

一句话：**模型是大脑，两个工具是手**——查「报销怎么报」伸手去向量库捞资料，查「张伟邮箱」伸手去 SQL 精确查，闲聊则不动手直接答。

## 技术选型（简）

| 层 | 选择 | 理由 |
|---|---|---|
| Web 框架 | FastAPI + uvicorn | 轻量、自带 `/docs` 交互文档 |
| 大模型 | Moonshot Kimi-2.7（OpenAI 兼容接口） | function calling 成熟，长文本能力强 |
| Embedding | fastembed + `bge-small-zh-v1.5` | 本地 ONNX 推理，无需 GPU |
| 向量检索 | numpy 手写余弦相似度 | 小体量够用，实现透明、易于理解 |
| 结构化查询 | SQLite（内置）+ csv | 零部署 |
| 文档解析 | pypdf | 纯 Python，支持文字型 PDF |
| Agent 编排 | 自写 ReAct 循环（不用 LangChain） | 实现透明，便于理解工具调用完整流程 |

## 演示数据

知识库假定为一家虚构企业「**华辰信息产业集团有限公司**」（简称华辰集团）服务，`data/` 下有 18 份仿照真实公文版式的红头文件（PDF），均带红色公章：

| 类型 | 文件 |
|---|---|
| 制度（10） | 员工考勤 / 差旅费 / 薪酬保密 / 费用报销 / 会议 / 培训 / 消防安全 / 信息安全 / 员工福利 / 公务用车 |
| 放假通知（3） | 国庆 / 中秋 / 元旦 |
| 通告（3） | 办公区搬迁 / 门禁系统 / 网络维护 |
| 人事（2） | 任免 / 表彰 |

公章为矢量绘制（外圈 + 弧排公司名 + 五角星），非贴图。生成这些 PDF 的脚本 `make_redhead_docs.py` 已移到项目外 `工具脚本/` 目录（仅造数据用，需 reportlab；运行时解析用 pypdf）。

另有 7 张结构化表格（`data/` 下的 `.csv`/`.xlsx`）：通讯录、产品目录、项目台账、供应商名录、固定资产台账、会议室资源、车辆台账——这些走 **SQL 精确查询**，不是向量检索。生成它们的脚本 `make_sample_tables.py` 已移到项目外 `工具脚本/` 目录（需 openpyxl）。

## 快速开始

### 1. 环境准备

```bash
python -m venv .venv            # 首次运行才需要，之后可跳过
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # 填入你的 Moonshot API Key
```

### 2. 入库

```bash
python scripts/ingest_demo.py   # TXT + PDF → 向量库（先清空再重建）
python scripts/ingest_tables.py  # CSV/XLSX → SQLite（按文件名自动建表）
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

### 4. 测试（4 类场景）

浏览器打开 http://127.0.0.1:8000/ 聊天界面，或命令行：

```bash
# 语义检索（调 vector_search）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"员工出差住宿标准是多少\"}"

# SQL 精确查（调 sql_query）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"张伟的邮箱是多少\"}"

# 闲聊（不调工具）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"你好\"}"
```

`/query` 返回 `answer`（答案）+ `trajectory`（调用了哪些工具）+ `sources`（引用来源）+ `similarities`（相似度）。

## 评估

```bash
python eval/evaluate.py
```

输出三项指标：检索命中率、答案正确率、拒答准确率。

## 目录结构

```
knowledge-qa-agent/
├── app/                    # 核心代码
│   ├── main.py             # FastAPI 接口
│   ├── agent.py            # Agent 循环（核心）
│   ├── retrieve.py         # 向量检索
│   ├── store.py            # numpy 向量库
│   ├── sql_tool.py         # SQLite 结构化查询
│   ├── embedding.py        # 向量化
│   ├── ingest.py           # 入库（TXT/PDF 解析 + 分块）
│   ├── llm.py              # 调大模型（基础封装）
│   └── config.py           # 配置（读 .env）
├── scripts/                # 脚本（只保留运行/入库所需）
│   ├── ingest_demo.py       # 一键导入 TXT/PDF
│   └── ingest_tables.py     # 导入 CSV/XLSX 到 SQLite（按文件名建表）
├── eval/                   # 评估
│   ├── questions.json      # 测试集
│   ├── evaluate.py         # 评估脚本（三项指标）
│   └── tune_threshold.py   # 阈值调优（扫阈值，给 0.6 找依据）
├── data/                   # 知识库文件（TXT/PDF/CSV/XLSX）
├── vector_store/           # numpy 向量库数据（自动生成）
├── sqlite_db/              # SQLite 数据库（自动生成）
├── requirements.txt
├── Dockerfile              # Docker 镜像构建
├── docker-compose.yml      # Docker Compose 一键启动
├── docker-entrypoint.sh    # 容器启动脚本（自动入库 + 启动服务）
├── .dockerignore           # Docker 构建忽略
└── .env.example
```

## Docker 部署（可选）

项目已提供 `Dockerfile` 和 `docker-compose.yml`，适合在服务器或本地 Docker 环境一键拉起。

> 注意：当前开发机未安装 Docker/WSL，Docker 文件已按规范编写但未实际构建运行，推到 GitHub 后可在支持 Docker 的环境验证。

### 使用 docker-compose（推荐）

```bash
# 1. 复制环境变量并填入 DeepSeek API Key
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 构建并启动
docker-compose up --build -d

# 3. 测试
# 语义检索
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d '{"question": "员工出差住宿标准是多少"}'

# SQL 精确查询
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d '{"question": "张伟的邮箱是多少"}'
```

### 关键设计说明

- **镜像内预下载 Embedding 模型**：构建时就把 `BAAI/bge-small-zh-v1.5` 下载到 `/root/.cache/fastembed`，避免容器首次启动时联网下载，做到开箱即用。
- **数据持久化**：`vector_store/` 和 `sqlite_db/` 通过 `volumes` 挂载到宿主机，重建容器不会丢失已生成的向量库和数据库。
- **自动入库**：`docker-entrypoint.sh` 在启动服务前自动执行 `ingest_demo.py` 和 `ingest_tables.py`，可通过环境变量 `AUTO_INGEST=false` 关闭。
- **密钥安全**：`.env` 通过 `env_file` 挂载，不会进入镜像层；`.dockerignore` 已排除 `.env`。

## 为什么没用 LangChain

LangChain 这类框架把 Agent 的工具调用循环封装得较深、迭代也快，使用者往往不清楚「底层到底是怎么调工具的」。本项目刻意把核心链路（Agent 循环、工具调度、向量检索）全部手写，只把分块、解析这类机械步骤交给库，目的是让实现透明、可控，也便于理解 RAG 与 Tool Calling 的完整流程。如果只是想快速搭建 Agent，换用 LangChain / LlamaIndex 同样可行；本项目的取舍在于「展示原理」优先于「最短代码」。
