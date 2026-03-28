# Huong dan project moi su dung infrastructure cua Service Controller

> Huong dan tao project moi tu dau, tan dung toan bo shared infrastructure co san.

---

## 1. Tong quan

Service Controller cung cap san cac infrastructure services sau. Project moi chi can ket noi va su dung, khong can tu cai dat hay cau hinh bat ky service nao.

| Service | Mo ta | Ket noi (trong Docker) | Ket noi (tu host) |
|---------|-------|------------------------|-------------------|
| PostgreSQL + pgvector | Relational DB, ho tro vector | `infra-postgres:5432` | `localhost:5432` |
| Redis | Cache, message queue | `infra-redis:6379` | `localhost:6379` |
| MinIO | Object storage (S3-compatible) | `infra-minio:9000` | `localhost:9000` |
| Milvus | Vector database | `infra-milvus:19530` | `localhost:19530` |
| Elasticsearch | Full-text search | `infra-elasticsearch:9200` | `localhost:9200` |
| Langfuse | LLM observability | `infra-langfuse:3000` | `localhost:3001` |
| Grafana | Monitoring dashboard | — | `localhost:3000` |
| Prometheus | Metrics | — | `localhost:9090` |

---

## 2. Tao project moi — Quick Start

### Buoc 1: Tao thu muc project

```bash
mkdir C:\Projects\MyNewProject
cd C:\Projects\MyNewProject
```

### Buoc 2: Dang ky voi Service Controller

```bash
sc project add C:\Projects\MyNewProject --name my_new_project
```

Output:

```
Registered project: my_new_project
  Path: C:\Projects\MyNewProject
  Namespaces:
    postgres: my_new_project_db
    redis: 3
    minio: my_new_project-bucket
    milvus: my_new_project_
    elasticsearch: my_new_project_
  Port range: 8030-8039
```

**Ghi nho cac gia tri nay** — day la namespace rieng cua project, dam bao data khong lan voi project khac.

### Buoc 3: Tao file .env

```bash
sc project env my_new_project --output C:\Projects\MyNewProject\.env
```

### Buoc 4: Tao docker-compose.yml

```yaml
# C:\Projects\MyNewProject\docker-compose.yml
services:
  app:
    build: .
    container_name: my-new-project-app
    ports:
      - "8030:8000"                   # Port tu allocated range
    env_file: .env
    deploy:
      resources:
        limits:
          memory: 2048M
          cpus: "1.0"
        reservations:
          memory: 256M
          cpus: "0.25"
    networks:
      - infra-net

networks:
  infra-net:
    external: true                    # Join vao shared infra network
```

### Buoc 5: Tao Dockerfile

```dockerfile
# C:\Projects\MyNewProject\Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Buoc 6: Khoi dong

```bash
# Tu dong khoi dong shared infra (neu chua chay) va project
sc project up my_new_project
```

---

## 3. Su dung tung service cu the

### 3.1 PostgreSQL + pgvector

**Dac diem:**
- Image: `pgvector/pgvector:0.8.1-pg18-trixie` (PostgreSQL 18 + pgvector 0.8.1)
- Extension `vector` da duoc enable san trong database cua project
- Connection limit: 40 connections/database
- Credentials: `postgres:postgres` (dev environment)

**Connection string:**

```
DATABASE_URL=postgresql://postgres:postgres@infra-postgres:5432/my_new_project_db
```

**Python (SQLAlchemy):**

```python
import os
from sqlalchemy import create_engine

engine = create_engine(
    os.getenv("DATABASE_URL"),
    pool_size=15,         # So connections giu san
    max_overflow=10,      # Them toi da 10 khi busy → tong max 25
    pool_timeout=30,      # Cho 30s neu pool het
    pool_recycle=1800,    # Recycle connection sau 30 phut
)
```

**Su dung pgvector:**

```python
from sqlalchemy import text

# Tao bang voi vector column
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            content TEXT,
            embedding vector(1536)
        )
    """))
    conn.commit()

# Tim kiem vector
with engine.connect() as conn:
    results = conn.execute(text("""
        SELECT id, content, embedding <=> :query_vec AS distance
        FROM documents
        ORDER BY distance
        LIMIT 10
    """), {"query_vec": str(embedding_list)})
```

**Alembic migration:**

```python
# alembic/env.py
import os
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))
```

```bash
# Chay migration (trong container hoac tu host)
alembic upgrade head
```

### 3.2 Redis

**Dac diem:**
- Moi project duoc cap 1 DB number rieng (0-15)
- `maxmemory`: 768MB, policy: `allkeys-lru`
- `maxclients`: 300 (chia se giua cac project)
- Ho tro: caching, pub/sub, task queue, session store

**Connection string:**

```
REDIS_URL=redis://infra-redis:6379/3
```

**Python (redis-py):**

```python
import os
import redis

# Cach 1: Tu URL
r = redis.from_url(os.getenv("REDIS_URL"))

# Cach 2: Connection pool
pool = redis.ConnectionPool.from_url(
    os.getenv("REDIS_URL"),
    max_connections=30,
)
r = redis.Redis(connection_pool=pool)

# Su dung
r.set("my_key", "value", ex=3600)  # TTL 1 gio
value = r.get("my_key")
```

**Lam task queue voi Celery:**

```python
# celery_config.py
import os

broker_url = os.getenv("REDIS_URL")
result_backend = os.getenv("REDIS_URL")
```

**Luu y:**
- Du lieu Redis la volatile (co the bi xoa khi day memory do LRU policy)
- Khong luu data quan trong trong Redis ma khong co fallback
- Prefix key voi project name de de debug: `my_project:user:123`

### 3.3 Milvus (Vector Database)

**Dac diem:**
- Su dung collection prefix de phan biet data giua cac project
- Ho tro: ANN search, hybrid search, filtering
- RAM limit: 4GB

**Environment variables:**

```
MILVUS_HOST=infra-milvus
MILVUS_PORT=19530
MILVUS_COLLECTION_PREFIX=my_new_project_
```

**Python (pymilvus):**

```python
import os
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType

# Ket noi
connections.connect(
    alias="default",
    host=os.getenv("MILVUS_HOST"),
    port=os.getenv("MILVUS_PORT"),
)

# Tao collection voi prefix
prefix = os.getenv("MILVUS_COLLECTION_PREFIX")
collection_name = f"{prefix}documents"    # → my_new_project_documents

fields = [
    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536),
]
schema = CollectionSchema(fields, description="Document embeddings")
collection = Collection(name=collection_name, schema=schema)

# Tao index
collection.create_index(
    field_name="embedding",
    index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
)

# Search
collection.load()
results = collection.search(
    data=[query_embedding],
    anns_field="embedding",
    param={"metric_type": "COSINE", "params": {"nprobe": 16}},
    limit=10,
    output_fields=["text"],
)
```

**Quy tac dat ten collection:**
- Luon dung prefix: `{MILVUS_COLLECTION_PREFIX}{ten_collection}`
- Vi du: `my_new_project_documents`, `my_new_project_chunks`, `my_new_project_qa_pairs`

### 3.4 Elasticsearch

**Dac diem:**
- Single-node, security disabled (dev environment)
- JVM heap: 2GB
- Su dung index prefix de phan biet data

**Environment variables:**

```
ELASTICSEARCH_URL=http://infra-elasticsearch:9200
ELASTICSEARCH_INDEX_PREFIX=my_new_project_
```

**Python (elasticsearch-py):**

```python
import os
from elasticsearch import Elasticsearch

es = Elasticsearch(os.getenv("ELASTICSEARCH_URL"))
prefix = os.getenv("ELASTICSEARCH_INDEX_PREFIX")

# Tao index voi prefix
index_name = f"{prefix}documents"    # → my_new_project_documents
es.indices.create(
    index=index_name,
    body={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "title": {"type": "text", "analyzer": "standard"},
                "content": {"type": "text"},
                "created_at": {"type": "date"},
            }
        }
    },
    ignore=400,  # Ignore neu da ton tai
)

# Index document
es.index(index=index_name, body={"title": "Hello", "content": "World"})

# Search
results = es.search(
    index=index_name,
    body={"query": {"match": {"content": "World"}}},
)
```

**Quy tac dat ten index:**
- Luon dung prefix: `{ELASTICSEARCH_INDEX_PREFIX}{ten_index}`
- Vi du: `my_new_project_documents`, `my_new_project_logs`

### 3.5 MinIO (Object Storage)

**Dac diem:**
- S3-compatible API
- Moi project 1 bucket rieng
- Console: http://localhost:9001 (minioadmin/minioadmin)

**Environment variables:**

```
MINIO_ENDPOINT=infra-minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=my_new_project-bucket
```

**Python (minio):**

```python
import os
from minio import Minio

client = Minio(
    os.getenv("MINIO_ENDPOINT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=False,
)

bucket = os.getenv("MINIO_BUCKET")

# Tao bucket (neu chua co)
if not client.bucket_exists(bucket):
    client.make_bucket(bucket)

# Upload file
client.fput_object(bucket, "data/file.pdf", "/local/path/file.pdf")

# Download file
client.fget_object(bucket, "data/file.pdf", "/local/download/file.pdf")

# Generate presigned URL (7 ngay)
from datetime import timedelta
url = client.presigned_get_object(bucket, "data/file.pdf", expires=timedelta(days=7))
```

**Python (boto3 — S3-compatible):**

```python
import os
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url=f"http://{os.getenv('MINIO_ENDPOINT')}",
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
)

bucket = os.getenv("MINIO_BUCKET")
s3.upload_file("/local/file.pdf", bucket, "data/file.pdf")
```

### 3.6 Langfuse (LLM Observability)

**Dac diem:**
- UI: http://localhost:3001
- Theo doi LLM calls, costs, latency
- Khong co isolation per project — dung cung 1 instance

**Python:**

```python
from langfuse import Langfuse

langfuse = Langfuse(
    public_key="pk-...",        # Lay tu Langfuse UI
    secret_key="sk-...",
    host="http://infra-langfuse:3000",  # Trong Docker
    # host="http://localhost:3001",     # Tu host
)

# Trace LLM call
trace = langfuse.trace(name="my-rag-pipeline")
generation = trace.generation(
    name="openai-call",
    model="gpt-4",
    input=[{"role": "user", "content": "Hello"}],
    output="Hi there!",
)
langfuse.flush()
```

---

## 4. Template project day du

### 4.1 Cau truc thu muc khuyen nghi

```
MyNewProject/
├── docker-compose.yml          # Chi app, khong co infra
├── Dockerfile
├── .env                        # Auto-generated boi sc
├── .env.example                # Template cho developer khac
├── requirements.txt
├── alembic/                    # Database migrations
│   ├── alembic.ini
│   └── versions/
├── src/
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Doc env variables
│   ├── database.py             # PostgreSQL connection
│   ├── cache.py                # Redis connection
│   ├── storage.py              # MinIO connection
│   └── search.py               # Elasticsearch connection
└── tests/
```

### 4.2 Config module mau

```python
# src/config.py
import os
from dataclasses import dataclass


@dataclass
class Settings:
    # PostgreSQL
    database_url: str = os.getenv("DATABASE_URL", "")

    # Redis
    redis_url: str = os.getenv("REDIS_URL", "")

    # Milvus
    milvus_host: str = os.getenv("MILVUS_HOST", "localhost")
    milvus_port: int = int(os.getenv("MILVUS_PORT", "19530"))
    milvus_prefix: str = os.getenv("MILVUS_COLLECTION_PREFIX", "")

    # Elasticsearch
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "")
    elasticsearch_prefix: str = os.getenv("ELASTICSEARCH_INDEX_PREFIX", "")

    # MinIO
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "")


settings = Settings()
```

### 4.3 File .env.example

Tao file nay de developer khac biet can nhung env variables gi:

```env
# .env.example — Copy thanh .env va dien gia tri
# Hoac chay: sc project env <project_name> -o .env

# PostgreSQL
DATABASE_URL=postgresql://postgres:postgres@infra-postgres:5432/<project_name>_db

# Redis
REDIS_URL=redis://infra-redis:6379/<db_number>

# Milvus
MILVUS_HOST=infra-milvus
MILVUS_PORT=19530
MILVUS_COLLECTION_PREFIX=<project_name>_

# Elasticsearch
ELASTICSEARCH_URL=http://infra-elasticsearch:9200
ELASTICSEARCH_INDEX_PREFIX=<project_name>_

# MinIO
MINIO_ENDPOINT=infra-minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=<project_name>-bucket
```

### 4.4 docker-compose.yml — Template nhieu services

```yaml
services:
  api:
    build: .
    container_name: my-project-api
    ports:
      - "8030:8000"
    env_file: .env
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000
    deploy:
      resources:
        limits:
          memory: 1024M
          cpus: "0.5"
    networks:
      - infra-net

  worker:
    build: .
    container_name: my-project-worker
    env_file: .env
    command: celery -A src.tasks worker --loglevel=info
    deploy:
      resources:
        limits:
          memory: 1024M
          cpus: "0.5"
    networks:
      - infra-net

  beat:
    build: .
    container_name: my-project-beat
    env_file: .env
    command: celery -A src.tasks beat --loglevel=info
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.25"
    networks:
      - infra-net

networks:
  infra-net:
    external: true
```

---

## 5. Quy tac quan trong

### 5.1 Data Isolation

| Service | Quy tac | Vi du |
|---------|---------|-------|
| PostgreSQL | Dung dung database name duoc cap | `my_new_project_db` |
| Redis | Dung dung DB number duoc cap | `3` (trong URL: `/3`) |
| Milvus | Collection name phai co prefix | `my_new_project_documents` |
| Elasticsearch | Index name phai co prefix | `my_new_project_logs` |
| MinIO | Chi dung bucket duoc cap | `my_new_project-bucket` |

**KHONG BAO GIO:**
- Truy cap database cua project khac
- Dung Redis DB number cua project khac
- Tao collection/index khong co prefix
- Ghi vao bucket cua project khac

### 5.2 Connection Pool Limits

PostgreSQL co gioi han 40 connections/database. Cau hinh pool phu hop:

| Thanh phan | pool_size | max_overflow | Tong |
|------------|-----------|--------------|------|
| API server | 15 | 10 | 25 |
| Worker | 5 | 5 | 10 |
| Migrations | — | — | 3 |
| **Tong** | | | **38** (trong limit 40) |

### 5.3 Resource Limits

Moi project nen dat resource limits trong docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      memory: 2048M     # Gioi han cung
      cpus: "1.0"
    reservations:
      memory: 256M      # Dam bao luon co it nhat 256MB
      cpus: "0.25"
```

### 5.4 Port Range

Dung port trong range duoc cap phat. Vi du range `8030-8039`:

| Port | Dung cho |
|------|----------|
| 8030 | API server |
| 8031 | gRPC server (neu co) |
| 8032 | WebSocket (neu co) |
| 8033-8039 | Du phong |

---

## 6. Dev khong Docker (optional)

Neu muon chay app truc tiep tren may (khong trong container) nhung van dung shared infra:

```bash
# Dam bao infra dang chay
sc infra up

# Tao .env cho host (thay hostname = localhost)
sc project env my_new_project > .env.docker
```

Tao `.env.local` voi `localhost`:

```env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/my_new_project_db
REDIS_URL=redis://localhost:6379/3
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION_PREFIX=my_new_project_
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX_PREFIX=my_new_project_
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=my_new_project-bucket
```

```bash
# Chay app
export $(cat .env.local | xargs)
uvicorn src.main:app --reload
```

---

## 7. Chuyen len Production

Khi deploy production, chi can thay doi `.env` — code khong can sua:

```env
# Production .env
DATABASE_URL=postgresql://user:pass@prod-postgres.example.com:5432/my_project_db
REDIS_URL=redis://:pass@prod-redis.example.com:6379/0
MILVUS_HOST=prod-milvus.example.com
MILVUS_PORT=19530
MILVUS_COLLECTION_PREFIX=my_project_
ELASTICSEARCH_URL=https://prod-es.example.com:9200
ELASTICSEARCH_INDEX_PREFIX=my_project_
MINIO_ENDPOINT=prod-s3.example.com
MINIO_ACCESS_KEY=prod_access_key
MINIO_SECRET_KEY=prod_secret_key
MINIO_BUCKET=my-project-bucket
```

Namespace logic (database name, prefix, bucket) van giu nguyen. Chi thay doi connection strings.
