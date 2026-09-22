# 企业知识库问答 Agent（RAG + Function Calling）

> 基于大模型 Function Calling 的自研企业知识库问答 Agent。模型根据用户问题**自主决策**：查制度文档走语义检索、查表格数据走 SQL 精确查询、闲聊直接回答——而非走一条固定的处理流水线（Chain）。

演示场景为虚构企业「华辰集团」的员工制度助手，覆盖考勤、差旅、报销、福利、放假通知、人事任免、公共资源查询等内部问答。

---

## 目录

1. [核心特性](#核心特性)
2. [架构总览](#架构总览)
3. [技术选型](#技术选型)
4. [演示数据](#演示数据)
5. [快速开始（本地）](#快速开始本地)
6. [接口说明](#接口说明)
7. [Windows 一键脚本](#windows-一键脚本)
8. [评估](#评估)
9. [目录结构](#目录结构)
10. [自定义知识库](#自定义知识库)
11. [Docker 部署](#docker-部署)
12. [环境变量说明](#环境变量说明)
13. [切换大模型](#切换大模型)
14. [设计思路与适用边界](#设计思路与适用边界)
15. [常见问题](#常见问题)

---

## 核心特性

- **两类知识、两种工具**：长文本（制度 / 标准 / 通知 PDF、TXT）→ 向量语义检索；结构化数据（通讯录、会议室、车辆、项目、供应商、产品、资产台账）→ SQL 精确查询。
- **Agent 自主决策**：不预设 Chain。模型自行选择工具、决定调用次数与停止时机；后端按问题复杂度动态分配最大轮数（闲聊 1 轮、单事实查询 2 轮、多事实 / 对比 / 汇总 3 轮），防止死循环或过度调用。
- **双层防幻觉**：检索层用相似度阈值（默认 0.5）+ 关键词重排 + 领域实体严格过滤拦截无关结果；生成层 Prompt 约束「查不到就明说、禁止编造」；工具执行出错（如 SQL 写错）会把错误回传模型自行修正，不抛 500。
- **引用可溯源**：回答附带参考来源（文件名、原文片段、相似度），Web 前端可展开查看「答案出自哪份文件」。
- **多轮对话**：前端自动携带对话历史，追问、指代（"那条""再具体说说"）无需重述；后端保持无状态。
- **可量化评估**：19 条测试集覆盖向量 / SQL / 拒答 / 闲聊四类，一键输出检索命中率、答案正确率、拒答准确率。
- **零重型框架**：Agent 循环、向量检索、SQL 工具全部原生 Python 实现（不用 LangChain / LlamaIndex），逻辑透明，阈值与 Prompt 可直接修改。
- **一键部署**：Docker Compose 启动，自动入库、数据持久化、健康检查；支持任意 OpenAI 兼容大模型（DeepSeek / Kimi / 火山 Ark / OpenAI…），切换只改 `.env`。

---

## 架构总览

```
                  ┌──────────────────────┐
                  │   用户 / 调用方        │
                  └──────────┬───────────┘
                             │ POST /query {question, history}
                  ┌──────────▼───────────┐
                  │  FastAPI（main.py）   │  GET /        聊天界面
                  └──────────┬───────────┘  GET /docs     接口文档
                             │             GET /health    健康检查
                  ┌──────────▼───────────┐
                  │ Agent 循环（agent.py） │  大模型 Function Calling
                  │ 复杂度判定 → 选工具 →  │  自主决策：调哪个工具、调几次、何时停
                  │ 结果回传 → 出最终答案  │
                  └──────┬───────┬───────┘
                         │       │
             ┌───────────▼──┐ ┌──▼────────────┐
             │ vector_search│ │    sql_query    │
             │ 语义检索      │ │    只读 SELECT   │
             │ retrieve.py  │ │    sql_tool.py  │
             │ numpy 余弦相似 │ │    (SQLite)     │
             │ 度+关键词重排  │ └──┬────────────┘
             └───────┬──────┘    │
                     │           │
             ┌───────▼──────┐ ┌──▼────────────┐
             │  长文本知识库  │ │  结构化知识库   │
             │ PDF/TXT      │ │  CSV/XLSX     │
             │ →条款分块向量化│ │ →SQLite 建表   │
             │ bge-small-zh │ │（通讯录等7张表）│
             │ →numpy 向量库 │ └──────────────┘
             └──────────────┘
```

**一次请求的完整流程：**

1. 请求进入 FastAPI `/query`，携带问题与可选对话历史；
2. Agent 先判定问题类型：问候 / 闲聊 / 系统说明 → 直接回答、不调工具；事实查询 → 进入 Function Calling 循环；
3. 循环内把「系统提示 + 历史 + 问题 + 工具说明书」交给大模型，模型返回「调用工具」或「直接作答」；工具执行结果（含来源与相似度）回传模型继续推理，直到给出答案或达到最大轮数；
4. 回答附带的 `sources`（引用来源）原样返回给前端渲染「参考来源」面板。

**两个工具的分工：**

| 工具 | 适用场景 | 实现 |
|---|---|---|
| `vector_search(query, top_k)` | 规章制度、管理办法、报销标准、放假通知等**长文本** | 问题向量化 → numpy 余弦相似度检索（召回 2×top_k）→ 关键词重排 + 领域实体严格过滤 → 返回 Top-N 片段 |
| `sql_query(sql)` | 通讯录、会议室、车辆、项目等**表格数据** | 仅允许只读 `SELECT`；表结构与列名通过工具描述动态告知模型，模型自行编写 SQL（参数化入库，无注入风险） |

---

## 技术选型

| 层 | 选择 | 理由 |
|---|---|---|
| Web 框架 | FastAPI + uvicorn | 轻量、原生异步，自带 `/docs` 交互式接口文档 |
| 大模型 | OpenAI 兼容接口（DeepSeek / Kimi / 火山 Ark / OpenAI 等） | 任一套 `chat.completions + tools` 的服务均可接入，切换只改 `.env` |
| Embedding | fastembed + `BAAI/bge-small-zh-v1.5` | 本地 ONNX 推理，CPU 即可，无需 GPU |
| 向量检索 | numpy 手写余弦相似度 | 小体量够用，实现透明，便于理解原理 |
| 结构化查询 | SQLite（内置）+ CSV/XLSX 导入 | 零部署、零额外服务 |
| 文档解析 | pypdf（文字型 PDF）+ openpyxl | 纯 Python，支持文字型 PDF 与 Excel |
| Agent 编排 | 自写 ReAct 循环（不用 LangChain） | 完整展示 Function Calling 链路，阈值与 Prompt 可控 |

---

## 演示数据

知识库假定为虚构企业「**华辰信息产业集团有限公司**」（简称华辰集团），`data/` 下共 **18 份**仿真实公文的 PDF（文字型，均带红色公章）：

| 类型 | 文件 |
|---|---|
| 制度（10） | 员工考勤 / 差旅费 / 薪酬与绩效保密 / 费用报销 / 会议管理 / 员工培训 / 员工福利 / 消防安全 / 网络与信息安全 / 车辆与公务用车 |
| 放假通知（3） | 2026 年国庆 / 中秋 / 元旦 |
| 通告（3） | 办公区搬迁 / 门禁考勤系统 / 网络系统升级维护 |
| 人事（2） | 人事任免 / 表彰优秀员工和先进集体 |

另有 **7** 张结构化表格（`data/` 下的 `.csv` / `.xlsx`）：通讯录、产品目录、项目台账、供应商名录、固定资产台账、会议室资源、车辆台账——这些走 **SQL 精确查询**，不走向量检索。

---

## 快速开始（本地）

### 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.10 ~ 3.12（推荐 3.11，与 Docker 镜像一致） |
| 操作系统 | Windows / Linux / macOS |
| GPU | 不需要，Embedding 为本地 ONNX CPU 推理 |
| 网络 | 首次需联网（安装依赖 + 下载 Embedding 模型）；运行时需能访问大模型 API |
| 磁盘 | 建议预留 2 GB 以上（含模型缓存、向量库、SQLite） |

### 安装与启动

```bash
# 1. 创建并激活虚拟环境（首次运行才需要，之后可跳过）
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 2. 安装依赖
pip install -r requirements.txt

# 3. 创建环境变量文件并填入 API Key
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

# 4. 编辑 .env，至少配置 LLM_API_KEY（默认 DeepSeek，可切换其它服务，见「切换大模型」）

# 5. 入库（先向量库，后 SQLite）
python scripts/ingest_demo.py    # TXT + PDF → 向量库（先清空再重建）
python scripts/ingest_tables.py  # CSV/XLSX → SQLite（按文件名自动建表）

# 6. 启动服务
uvicorn app.main:app --reload
```

> 首次运行 `ingest_demo.py` 时，fastembed 会自动从 HuggingFace 下载 `BAAI/bge-small-zh-v1.5`（约 100 MB）；国内网络可先设置环境变量 `HF_ENDPOINT=https://hf-mirror.com` 加速。

启动后浏览器打开 `http://127.0.0.1:8000/` 即可使用聊天界面。

---

## 接口说明

### 快速测试（4 类场景）

```bash
# 语义检索（调 vector_search）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"员工出差住宿标准是多少\"}"

# SQL 精确查询（调 sql_query）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"张伟的邮箱是多少\"}"

# 应拒答的场景（检索不到 → 明确拒答不编造）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"公司明年的营收目标是多少\"}"

# 闲聊（不调工具，直接回答）
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"question\": \"你好\"}"
```

### 请求体

```json
{
  "question": "国庆节放假怎么安排？",
  "history": [
    {"role": "user", "content": "……"},
    {"role": "assistant", "content": "……"}
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `question` | string | 必填，本次提问 |
| `history` | array | 可选，之前对话的 `[{role, content}]`，仅保留纯文本用于多轮上下文 |

### 响应体

| 字段 | 类型 | 说明 |
|---|---|---|
| `answer` | string | 模型生成的最终回答 |
| `trajectory` | array | 本次请求调用的工具及参数，便于追踪 Agent 决策过程 |
| `sources` | array | 引用来源，每项含 `source`（文件名）、`text`（原文片段）、`similarity`（相似度，SQL 查询为 `null`） |

语义检索示例：

```json
{
  "answer": "根据《差旅费管理办法》，员工出差住宿标准为：一线城市每晚不超过 500 元，二线城市不超过 400 元，其他地区不超过 300 元。",
  "trajectory": ["vector_search({\"query\": \"员工出差住宿标准\", \"top_k\": 3})"],
  "sources": [
    {"source": "差旅费管理办法.pdf", "text": "第X条 员工出差住宿费标准……", "similarity": 0.8234}
  ]
}
```

SQL 查询示例：

```json
{
  "answer": "张伟的邮箱是 zhangwei@example.com。",
  "trajectory": ["sql_query({\"sql\": \"SELECT email FROM contacts WHERE name='张伟'\"})"],
  "sources": [
    {"source": "通讯录数据库", "text": "email\nzhangwei@example.com", "similarity": null}
  ]
}
```

> FastAPI 自带的交互式文档位于 `http://127.0.0.1:8000/docs`，健康检查为 `GET /health`。

---

## Windows 一键脚本

项目根目录提供两个 Windows 批处理脚本（无需手动敲命令）：

| 脚本 | 作用 |
|---|---|
| `启动.bat` | 自动打开浏览器并启动服务（要求已装好依赖并完成入库） |
| `重新入库.bat` | 重新执行向量与 SQLite 入库脚本，完成后需重启服务 |

要求已创建 `.venv` 虚拟环境（脚本内直接调用 `.venv\Scripts\python.exe`）。

---

## 评估

```bash
python eval/evaluate.py
```

测试集共 **19 条**（9 向量 / 5 SQL / 4 拒答 / 1 闲聊），输出三项指标：

- **检索命中率**：vector 类问题，检索到的片段（`sources`）是否包含全部答案关键词（AND 逻辑，比 OR 更严格）；
- **答案正确率**：vector + SQL 类问题，最终回答是否包含全部答案关键词；
- **拒答准确率**：refuse 类问题，是否真的按「未查询到相关信息」拒答而非编造。

闲聊类不参与统计，仅要求有回应。项目开发时在演示集上三项指标均达到 **100%**；结果依赖所选大模型与阈值，可作上线前的回归基线。

另有免费离线调参脚本（不调用大模型，只扫检索层）：

```bash
python eval/tune_threshold.py
```

它会扫 0.30 ~ 0.80 各阈值下的「检索命中率 / 拒答率」，并输出关键分界点（命中片段的最低分、噪声的最高分），为 `SIM_THRESHOLD` 取值提供数据依据。

---

## 目录结构

```
knowledge-qa-agent/
├── app/                    # 核心代码
│   ├── main.py             # FastAPI 入口：聊天界面 / /query / /health
│   ├── agent.py            # Agent 循环（核心）：Function Calling 决策 + 工具执行
│   ├── retrieve.py         # 语义检索：向量召回 + 关键词重排 + 实体严格过滤
│   ├── store.py            # numpy 向量库（embeddings.npy + meta.json 持久化）
│   ├── sql_tool.py         # SQLite 结构化工具：CSV/XLSX 导入 + 只读 SELECT
│   ├── embedding.py        # 本地 Embedding（fastembed / bge-small-zh）
│   ├── ingest.py           # 入库解析：PDF/TXT → 条款分块 → 向量化
│   ├── llm.py              # 大模型基础封装（OpenAI 兼容接口）
│   └── config.py           # 配置：从 .env 读取，改配置不改代码
├── scripts/                # 一键脚本
│   ├── ingest_demo.py      # TXT/PDF → 向量库（先清空再重建）
│   └── ingest_tables.py    # CSV/XLSX → SQLite（按文件名建表）
├── eval/                   # 评估
│   ├── questions.json      # 19 条测试集（vector/sql/refuse/chat）
│   ├── evaluate.py         # 评估脚本（三项指标）
│   └── tune_threshold.py   # 阈值调优（离线扫描）
├── data/                   # 知识库文件（PDF/TXT/CSV/XLSX）
├── static/                 # 前端聊天界面（单页 HTML）
├── vector_store/           # numpy 向量库数据（运行时生成）
├── sqlite_db/              # SQLite 数据库（运行时生成）
├── 启动.bat / 重新入库.bat # Windows 一键脚本
├── requirements.txt
├── Dockerfile              # Docker 镜像构建（含健康检查）
├── docker-compose.yml      # Docker Compose 一键启动
├── docker-entrypoint.sh    # 容器启动脚本（幂等自动入库 + 启动服务）
├── .dockerignore           # 构建忽略（排除 .env 等）
└── .env.example            # 环境变量样例
```

---

## 自定义知识库

### 替换长文本知识库

将自有文档放入 `data/`，支持 `.txt` 与 `.pdf`（**文字型** PDF；图片型扫描件需 OCR，本项目不支持），然后重建向量库：

```bash
python scripts/ingest_demo.py
```

脚本会先清空旧向量库再重新解析入库。`ingest.py` 对规章制度类文本优先按「第 X 条」条款切分（条款是语义自足单元，避免把多档标准切碎），无条款结构的文本退回按句分块。

### 替换结构化数据

将表格文件放入 `data/`，支持 `.csv` 与 `.xlsx`，**文件名即表名**（如 `products.xlsx` → 表 `products`），然后重新导入：

```bash
python scripts/ingest_tables.py
```

### Docker 方式重建知识库

```bash
# Linux / macOS
rm -rf vector_store sqlite_db
# Windows: 手动删除 vector_store 和 sqlite_db 文件夹

docker compose restart
# entrypoint 检测到数据为空，会自动重新入库
```

---

## Docker 部署

已提供 `Dockerfile`、`docker-compose.yml` 与 `docker-entrypoint.sh`，可在 Windows（WSL2 后端）、Linux、macOS 上通过 Docker Compose 启动，避免宿主机 Python 环境 / 依赖版本 / 操作系统差异带来的问题。

### 前置条件

1. 安装 Docker Desktop（Windows 11 推荐 WSL2 后端），启动后等状态栏图标稳定；
2. 验证命令可用：

   ```bash
   docker --version
   docker compose version
   ```

### 快速开始

```bash
# 1. 进入项目目录
cd knowledge-qa-agent

# 2. 创建环境变量文件
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

# 3. 编辑 .env，填入 LLM_API_KEY（默认 DeepSeek，可切换其它服务）

# 4. 构建镜像并后台启动（首次构建 + 入库约 1-5 分钟）
docker compose up --build -d

# 5. 查看启动日志，看到「启动 FastAPI 服务...」即就绪
docker compose logs -f

# 6. 验证
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d '{"question": "员工出差住宿标准是多少"}'

# 7. 浏览器打开聊天界面：http://127.0.0.1:8000/
```

> 若 Docker 版本较旧不支持 `docker compose` 子命令，改用 `docker-compose up --build -d`。

### 离线 / 内网部署

若目标环境无法访问外网，可先将整个项目文件夹迁移过去（U 盘 / 内网共享 / 压缩包），再执行 Docker 部署：

```bash
cd knowledge-qa-agent
copy .env.example .env          # 若迁移后不存在 .env
# 编辑 .env 填入 API Key

docker compose up --build -d
```

> 迁移时一并携带 `vector_store/` 与 `sqlite_db/` 目录：entrypoint 检测到数据非空会自动跳过入库，直接启动服务，无需联网拉取 Embedding 模型。若需要在离线环境**重新入库**，则需预先准备好模型缓存（见「常见问题」）。

### 常用命令

```bash
docker compose ps          # 查看容器状态
docker compose logs -f     # 实时日志
docker compose restart     # 重启
docker compose down        # 停止并删除容器（数据保留在宿主机卷中）
docker compose up -d       # 重新启动（不用 --build）
docker exec -it knowledge-qa-agent bash   # 进入容器
```

### Docker 关键设计

- **自动入库（幂等）**：`docker-entrypoint.sh` 启动服务前检查向量库与 SQLite 是否为空，仅在首次启动时自动执行入库脚本；可用环境变量 `AUTO_INGEST=false` 关闭。已入库的数据不会因重启而清空重建。
- **数据持久化**：`vector_store/` 与 `sqlite_db/` 通过 `volumes` 挂载到宿主机，重建容器不丢数据。
- **模型拉取**：镜像内不内置 Embedding 模型文件，首次入库时由 fastembed 自动下载；`docker-compose.yml` 已通过 `HF_ENDPOINT=https://hf-mirror.com` 使用国内镜像加速。
- **依赖加速**：Dockerfile 内 pip 使用清华镜像源（`pypi.tuna.tsinghua.edu.cn`），适合国内网络。
- **密钥安全**：`.env` 通过 `env_file` 挂载，不进入镜像层；`.dockerignore` 已排除 `.env`。
- **健康检查**：内置 `HEALTHCHECK`（30s 间隔、180s 启动宽限），容器自动上报健康状态。
- **稳定性**：固定 `onnxruntime==1.19.2`，并设置 `OMP_NUM_THREADS=1` 规避部分环境多线程推理崩溃。

---

## 环境变量说明

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `LLM_API_KEY` | 是 | - | 大模型 API Key |
| `LLM_BASE_URL` | 是 | `https://api.deepseek.com` | 大模型接口基地址（OpenAI 兼容） |
| `LLM_MODEL` | 是 | `deepseek-chat` | 模型名称 |
| `EMBED_MODEL` | 否 | `BAAI/bge-small-zh-v1.5` | 本地 Embedding 模型 |
| `CHUNK_SIZE` | 否 | `400` | 单块文本长度上限（条款优先切分，超长条款再按句合并） |
| `CHUNK_OVERLAP` | 否 | `50` | 兼容保留（条款分块模式下已不使用重叠） |
| `TOP_N` | 否 | `3` | 向量检索最终返回片段数（召回时放大 2 倍再做重排） |
| `SIM_THRESHOLD` | 否 | `0.5` | 相似度阈值，低于视为无关（配合关键词重排抑制误命中） |
| `STORE_DIR` | 否 | `./vector_store` | 向量库本地存储目录 |
| `SQLITE_PATH` | 否 | `./sqlite_db/contacts.db` | SQLite 数据库文件路径 |
| `MAX_AGENT_ROUNDS` | 否 | `3` | 最大轮数上限（当前由问题复杂度自适应：闲聊 1 / 单事实 2 / 多事实与对比 3，此为预留兜底值） |

> Docker 模式额外支持 `AUTO_INGEST`（是否自动入库，默认 `true`）与 `HF_ENDPOINT`（HuggingFace 镜像地址，默认 `https://hf-mirror.com`）。

---

## 切换大模型

项目使用 OpenAI 兼容接口，任何支持 `chat.completions` 与 `tools`（Function Calling）的服务均可接入，Agent 代码无需改动，只改 `.env`：

```env
# DeepSeek（默认）
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# Moonshot / Kimi
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k        # 具体模型名以官方文档为准

# 火山引擎 Ark（需填推理接入点 ID）
LLM_API_KEY=sark-xxxxxxxxxxxxxxxx
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=ep-xxxxxxxxxxx

# OpenAI
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

`config.py` 同时兼容旧变量名 `DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL`，便于老配置平滑迁移。

---

## 设计思路与适用边界

Agent 的核心链路（工具决策循环、向量检索、SQL 查询）以原生 Python 实现，仅在文本解析、分块、Embedding 推理等环节使用成熟库。这样设计的原因：

- **实现透明**：可清晰看到 Function Calling 的完整流程，便于学习 RAG 与 Agent 的工作原理；
- **可控性强**：阈值、Prompt、工具定义、循环策略全部直接可改，不受框架约束；
- **依赖精简**：不引入 LangChain / LlamaIndex 等重型框架，降低理解与部署成本。

**适用边界（已知取舍）：**

- 向量检索为 numpy 全量线性扫描，适合**中小规模**知识库（万级分块以内）；更大规模建议换 FAISS 或向量数据库；
- 文档解析仅支持**文字型 PDF**，图片型扫描件需额外接入 OCR；
- 演示阈值（0.5）针对演示语料调校，接入自有知识库后建议运行 `eval/tune_threshold.py` 重新校准。

若目标是快速搭建生产级 Agent，使用 LangChain、LlamaIndex 等框架同样可行；本项目更适合作为理解底层机制的参考实现或轻量内网部署方案。

---

## 常见问题

### 1. 启动后访问 `http://127.0.0.1:8000` 无响应

- 检查服务是否启动：`docker compose ps`，或本地 `uvicorn` 进程是否在运行；
- 检查日志：`docker compose logs -f` 或本地终端输出；
- 检查端口是否被占用：可在 `docker-compose.yml` 中改端口映射（如 `"8080:8000"`），本地模式用 `--port` 指定。

### 2. 首次 Docker 启动卡在入库阶段

首次启动需解析 PDF、下载 Embedding 模型并生成向量，通常需要 1-5 分钟，取决于文档数量、网络与机器性能。可查看 `docker compose logs -f` 中的进度；若长时间无进展，确认网络可访问 `hf-mirror.com`。

### 3. 回答总是说「未查询到相关信息」

- 检查 `.env` 中 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 是否配置正确；
- 检查向量库是否已生成：`vector_store/embeddings.npy` 是否存在且非空；
- 确认问题与知识库内容相关：可运行 `python eval/tune_threshold.py` 看检索层的命中分布，必要时调整 `SIM_THRESHOLD`（比如对该类问题统一偏低时下调）。

### 4. 想清空知识库重新入库

本地模式：

```bash
python scripts/ingest_demo.py    # 向量库先清空再重建
python scripts/ingest_tables.py  # SQLite 先清空再重建
```

Docker 模式：删除宿主机上的 `vector_store/` 与 `sqlite_db/` 后 `docker compose restart`，entrypoint 会自动重新入库（需能联网下载 Embedding 模型）。

### 5. ONNX Runtime 初始化失败或段错误

部分环境（尤其某些 Windows 安全软件场景）下 onnxruntime 多线程推理会异常。项目已固定 `onnxruntime==1.19.2` 并在 `embedding.py` 中强制 `OMP_NUM_THREADS=1`。若仍复现，可在启动前手动设置：

```bash
export OMP_NUM_THREADS=1         # Windows: set OMP_NUM_THREADS=1
```

### 6. 离线环境重新入库时模型下载失败

镜像内不内置模型文件。方案一：在**有网**机器上先构建镜像并执行一次入库（首次入库会下载模型到容器缓存层），再导出镜像迁移到目标环境；方案二：自行在 `Dockerfile` 中追加预下载步骤（如 `RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-zh-v1.5')"`），把模型烘焙进镜像。