# RAG+MCP 项目起步手册（个人项目版）

> 目标：在本地用 **FastAPI + Qdrant + Postgres** 起一个最小可跑通的 RAG，并把检索/SQL 封成 **MCP servers** 让编排服务按统一协议调用。

---

## 0. 先决条件
- 操作系统：Windows + **WSL2 (Ubuntu 22.04)** 或原生 Linux/Mac
- 安装：Docker Desktop（或 docker + docker compose）、Python 3.10+、Node.js 18+
- 端口预留：`5432` (Postgres), `6333` (Qdrant), `8000` (FastAPI), `9001/9002` (MCP servers)

---

## 1. 仓库结构
```
rag-mcp-starter/
├─ .env.example
├─ docker-compose.yml
├─ orchestrator/           # FastAPI 对话编排
│  ├─ app.py
│  ├─ requirements.txt
│  └─ config.py
├─ ingestion/              # 语料清洗 + 嵌入 + 入库
│  ├─ ingest.py
│  ├─ requirements.txt
│  └─ sample_docs/         # 放若干 md/txt 示例
├─ mcp-rag-vector/         # MCP: 向量检索
│  ├─ package.json
│  ├─ src/server.ts
│  └─ tsconfig.json
├─ mcp-kb-sql/             # MCP: 结构化查询
│  ├─ server.py
│  └─ requirements.txt
└─ sql/
   └─ init.sql             # Postgres 初始化（元信息/演示表）
```

---

## 2. 环境变量模板（`.env.example`）
```
POSTGRES_USER=kc
POSTGRES_PASSWORD=kc_pass
POSTGRES_DB=kc
QDRANT_URL=http://qdrant:6333
EMBED_MODEL=BAAI/bge-m3
OPENAI_API_KEY=sk-xxx        # 如用 API，可留空
```
> 复制为 `.env` 后自行修改。

---

## 3. docker-compose（`docker-compose.yml`）
```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16
    env_file: .env
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_storage:/qdrant/storage

  orchestrator:
    build: ./orchestrator
    env_file: .env
    depends_on:
      - postgres
      - qdrant
    ports:
      - "8000:8000"

  mcp-rag-vector:
    build: ./mcp-rag-vector
    env_file: .env
    depends_on:
      - qdrant
    ports:
      - "9001:9001"

  mcp-kb-sql:
    build: ./mcp-kb-sql
    env_file: .env
    depends_on:
      - postgres
    ports:
      - "9002:9002"

volumes:
  pgdata: {}
  qdrant_storage: {}
```

---

## 4. Postgres 初始化（`sql/init.sql`）
```sql
-- 元信息表示例
CREATE TABLE IF NOT EXISTS docs (
  id SERIAL PRIMARY KEY,
  doc_id TEXT UNIQUE,
  title TEXT,
  url TEXT,
  lang TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 演示结构化表（比如掉落信息）
CREATE TABLE IF NOT EXISTS drops (
  id SERIAL PRIMARY KEY,
  ship TEXT,
  map TEXT,
  node TEXT,
  difficulty TEXT,
  rate_estimate TEXT,
  source_url TEXT,
  asof_date DATE
);

INSERT INTO drops (ship,map,node,difficulty,rate_estimate,source_url,asof_date)
VALUES ('榛名','2-4','Boss','乙','~2%','https://example.com/haruna','2025-08-01');
```

---

## 5. Ingestion（`ingestion/ingest.py`）
```python
# pip install -r ingestion/requirements.txt
# requirements: qdrant-client sentence-transformers pandas psycopg2-binary python-dotenv
import os, glob, uuid
from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams, Distance, PointStruct
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
import psycopg2

load_dotenv()
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
COLL = "kc_docs"

# 1) 准备向量库
qc = QdrantClient(url=QDRANT_URL)
try:
    qc.get_collection(COLL)
except Exception:
    qc.recreate_collection(
        collection_name=COLL,
        vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
    )

emb = SentenceTransformer(EMBED_MODEL)

# 2) 读取示例文档并切块
chunks = []
for path in glob.glob("ingestion/sample_docs/*.txt"):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    title = os.path.basename(path)
    # 简易切块：每 400 字
    for i in range(0, len(text), 400):
        chunk = text[i:i+400]
        if chunk.strip():
            chunks.append({"title": title, "text": chunk, "url": f"file://{path}"})

# 3) 嵌入并写入 Qdrant
vecs = emb.encode([c["text"] for c in chunks], normalize_embeddings=True)
points = [
    PointStruct(id=str(uuid.uuid4()),
                vector=vecs[i].tolist(),
                payload={"title": c["title"], "text": c["text"], "url": c["url"]})
    for i, c in enumerate(chunks)
]
qc.upsert(collection_name=COLL, points=points)

# 4) 把元信息写入 Postgres（可选）
conn = psycopg2.connect(
    host="localhost", port=5432, dbname=os.getenv("POSTGRES_DB","kc"),
    user=os.getenv("POSTGRES_USER","kc"), password=os.getenv("POSTGRES_PASSWORD","kc_pass")
)
cur = conn.cursor()
for p in points[:5]:
    cur.execute("INSERT INTO docs (doc_id, title, url) VALUES (%s,%s,%s) ON CONFLICT (doc_id) DO NOTHING",
                (p.id, p.payload["title"], p.payload["url"]))
conn.commit()
print(f"Ingested {len(points)} chunks into Qdrant.")
```

`ingestion/requirements.txt`
```
qdrant-client
sentence-transformers
pandas
psycopg2-binary
python-dotenv
```

在 `ingestion/sample_docs/` 放入任意几份 `.txt` 示例文本即可。

---

## 6. MCP：向量检索（`mcp-rag-vector/src/server.ts`）
```ts
// pnpm add @modelcontextprotocol/sdk qdrant-js sentence-transformers-node --save
import { Server } from "@modelcontextprotocol/sdk";
import { QdrantClient } from "@qdrant/js-client-rest";
import { pipeline } from "sentence-transformers-node"; // 简化示例：可换成自定义嵌入API

const qdrant = new QdrantClient({ url: process.env.QDRANT_URL || "http://localhost:6333" });
const embed = await pipeline("feature-extraction", { model: "BAAI/bge-m3" });

const server = new Server({ name: "rag-vector", version: "0.1.0" });

server.tool("search_docs", {
  description: "Semantic search over kc_docs",
  inputSchema: {
    type: "object",
    properties: { query: { type: "string" }, k: { type: "integer", default: 8 } },
    required: ["query"],
  },
  handler: async (input) => {
    const { query, k = 8 } = input as any;
    const v = await embed(query);
    const res = await qdrant.search("kc_docs", { vector: Array.from(v.data[0]), limit: k });
    return res.map(h => ({ id: h.id, score: h.score, payload: h.payload }));
  },
});

server.start({ port: 9001 });
```

`mcp-rag-vector/package.json`
```json
{
  "name": "mcp-rag-vector",
  "version": "0.1.0",
  "type": "module",
  "scripts": { "start": "node dist/server.js", "dev": "ts-node src/server.ts" }
}
```

---

## 7. MCP：结构化查询（`mcp-kb-sql/server.py`）
```python
# pip install fastapi uvicorn psycopg2-binary pydantic mcp[server]
from fastapi import FastAPI
from pydantic import BaseModel
import os, psycopg2

app = FastAPI(title="mcp-kb-sql")

class DropQuery(BaseModel):
    ship: str | None = None
    map: str | None = None
    node: str | None = None
    difficulty: str | None = None

@app.post("/get_drops")
def get_drops(q: DropQuery):
    conn = psycopg2.connect(host=os.getenv("PGHOST","localhost"), port=5432,
                            dbname=os.getenv("POSTGRES_DB","kc"),
                            user=os.getenv("POSTGRES_USER","kc"), password=os.getenv("POSTGRES_PASSWORD","kc_pass"))
    cur = conn.cursor()
    cond, params = [], []
    for k in ["ship","map","node","difficulty"]:
        v = getattr(q, k)
        if v:
            cond.append(f"{k} = %s")
            params.append(v)
    sql = "SELECT ship,map,node,difficulty,rate_estimate,source_url,asof_date FROM drops"
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " LIMIT 50"
    cur.execute(sql, params)
    rows = cur.fetchall()
    return [{"ship":r[0],"map":r[1],"node":r[2],"difficulty":r[3],"rate":r[4],"url":r[5],"asof":str(r[6])} for r in rows]

# 可选：把本服务适配成原生 MCP server（STDIO/TCP），此处简化用 HTTP
```

`mcp-kb-sql/requirements.txt`
```
fastapi
uvicorn
psycopg2-binary
pydantic
```

---

## 8. Orchestrator（`orchestrator/app.py`）
```python
# pip install -r orchestrator/requirements.txt
# requirements: fastapi uvicorn pydantic requests
from fastapi import FastAPI
from pydantic import BaseModel
import requests, os

MCP_VECTOR = os.getenv("MCP_VECTOR", "http://mcp-rag-vector:9001")
MCP_SQL = os.getenv("MCP_SQL", "http://mcp-kb-sql:9002")

app = FastAPI(title="orchestrator")

class Ask(BaseModel):
    text: str

@app.post("/ask")
def ask(q: Ask):
    # 1) 调向量检索（MCP）
    vec = requests.post(f"{MCP_VECTOR}/tools/search_docs", json={"query": q.text, "k": 5}).json()
    # 2) 简单规则：若命中舰名关键词，顺带 SQL 查询演示
    sql_res = requests.post(f"{MCP_SQL}/get_drops", json={"ship":"榛名"}).json()

    answer = "这是一个最小演示：\n\n"
    if sql_res:
        answer += "[结构化证据]\n" + "\n".join([f"- {r['ship']} {r['map']}{r['node']} {r['difficulty']}: {r['rate']} ({r['asof']})" for r in sql_res]) + "\n\n"
    if vec:
        answer += "[检索片段]\n" + "\n".join(["- " + h["payload"]["text"][:80].replace("\n"," ") + "..." for h in vec])
    return {"answer": answer, "sources": [h["payload"].get("url") for h in vec[:3]]}
```

`orchestrator/requirements.txt`
```
fastapi
uvicorn
pydantic
requests
```

`orchestrator/Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

> 其他两个服务可用同理方式写 Dockerfile，或先本地 `pip/pnpm` 启动调通再容器化。

---

## 9. 启动顺序
```bash
# 1) 复制 .env.example 为 .env 并修改
cp .env.example .env

# 2) 启动基础设施
docker compose up -d postgres qdrant

# 3) 准备示例语料并执行 ingestion（首次）
python3 -m venv .venv && source .venv/bin/activate
pip install -r ingestion/requirements.txt
python ingestion/ingest.py

# 4) 启动两个 MCP 服务（本地调试阶段）
# 终端A：
uvicorn mcp_kb_sql:app --app-dir mcp-kb-sql --host 0.0.0.0 --port 9002
# 终端B（TS服务）：
# 在 mcp-rag-vector 目录内执行 pnpm i && pnpm dev

# 5) 启动 orchestrator（或用 docker 构建后启动）
pip install -r orchestrator/requirements.txt
uvicorn orchestrator.app:app --host 0.0.0.0 --port 8000
```

---

## 10. 验证
```bash
curl -s http://localhost:8000/ask -H 'Content-Type: application/json' \
  -d '{"text":"榛名在哪些图有掉落？"}' | jq
```
看到返回里包含 `[结构化证据]` 与 `[检索片段]` 即成功。

---

## 11. 下一步：把“对话→工具调用”做聪明
- 加一个轻量**意图路由**（LogReg/SVM）：事实/建议/新闻/术语/计算；
- 回答模板：结论 → 证据表 → 注意事项 → 来源（标题/日期/链接）；
- 增加 **Cross-Encoder 重排**（可 API 或小显卡本地）；
- 加入**别名/实体识别**（舰名/装备名中日/罗马字映射）；
- 监控：Prometheus + Grafana，记录 QPS、P95、召回数、重排耗时；
- 评测：100–300 条标注问答，算 EM/F1 与“可核查率”。

---

## 12. 常见问题
- **Q: 需要 GPU 吗？** A: 入门不需要。嵌入/生成先用 API，重排频繁再考虑 3060/4060。
- **Q: 用 MySQL 可不可以？** A: 可以。把 `sql/init.sql`/连接串改为 MySQL 即可；向量检索仍推荐 Qdrant。
- **Q: 语料多大能撑？** A: 单机 32GB RAM + NVMe，10 万段毫无压力；上百万段建议分片或上云。

---

> 有需要我可以把这份手册打包成初始仓库（含最简代码与 Compose），你直接 `git clone` 即可起跑。

