# Hướng dẫn sử dụng Service Controller

> CLI tool quản lý shared Docker infrastructure cho nhiều project trên 1 máy dev.

---

## 1. Giới thiệu

Service Controller (`sc`) là một CLI tool giúp:

- **Tập trung infrastructure** — PostgreSQL, Redis, Milvus, Elasticsearch, MinIO... chỉ chạy 1 instance duy nhất, chia sẻ cho tất cả project.
- **Tránh port conflict** — Không còn tình trạng nhiều project tranh nhau port 5432, 6379, 9200...
- **Tiết kiệm RAM** — Thay vì mỗi project chạy infra riêng (~3-5GB), tất cả dùng chung 1 bộ infra (~14GB cho toàn bộ).
- **Data isolation** — Mỗi project có namespace riêng (database name, Redis DB number, collection prefix, bucket name).
- **Quản lý đơn giản** — 1 lệnh `sc up` khởi động tất cả, 1 lệnh `sc down` dừng tất cả.

---

## 2. Cài đặt

### 2.1 Yêu cầu hệ thống

- **Docker** và **Docker Compose** (v2+)
- **Python** >= 3.11
- **RAM**: 32GB khuyến nghị (tối thiểu 16GB)
- **OS**: Windows (WSL/Docker Desktop), macOS, Linux

### 2.2 Cài đặt Service Controller

```bash
# Clone hoặc cd vào thư mục service_controller
cd C:\Projects\service_controller

# Cài đặt (editable mode)
pip install -e .
```

Sau khi cài đặt, lệnh `sc` sẽ khả dụng trong terminal.

---

## 3. Khởi tạo lần đầu

```bash
# Di chuyển đến thư mục workspace chứa tất cả project
cd C:\Projects

# Khởi tạo service controller
sc init --workspace C:\Projects
```

Lệnh `sc init` sẽ:
1. Tạo file `registry.yaml` — cơ sở dữ liệu trung tâm chứa thông tin infra và project.
2. Tạo thư mục `shared-infra/` với đầy đủ cấu hình:
   - `docker-compose.yml` — định nghĩa tất cả infrastructure services
   - `.env` — credentials mặc định
   - `init-scripts/postgres/01-create-databases.sql` — tự động tạo database cho các project
   - `config/` — cấu hình PostgreSQL, Prometheus, Grafana

---

## 4. Quản lý Infrastructure

### 4.1 Khởi động infrastructure

```bash
# Khởi động tất cả services
sc infra up

# Chỉ khởi động một số service cụ thể
sc infra up postgres redis milvus
```

### 4.2 Dừng infrastructure

```bash
# Dừng tất cả (giữ data)
sc infra down

# Dừng và XÓA TOÀN BỘ DATA (cẩn thận!)
sc infra down --volumes
```

### 4.3 Restart service

```bash
# Restart tất cả
sc infra restart

# Restart 1 service cụ thể
sc infra restart postgres
```

### 4.4 Xem trạng thái

```bash
sc infra status
```

Output bảng hiển thị trạng thái, health check, port của từng service:

```
┌──────────────── Infrastructure Services ────────────────┐
│ Service        │ Container          │ Status  │ Health  │
├────────────────┼────────────────────┼─────────┼─────────┤
│ postgres       │ infra-postgres     │ running │ healthy │
│ redis          │ infra-redis        │ running │ healthy │
│ milvus         │ infra-milvus       │ running │ healthy │
│ elasticsearch  │ infra-elasticsearch│ running │ healthy │
│ ...            │ ...                │ ...     │ ...     │
└──────────────────────────────────────────────────────────┘
```

### 4.5 Liệt kê services đã đăng ký

```bash
sc infra list
```

### 4.6 Thêm infrastructure service mới

```bash
sc infra add langfuse \
  --image langfuse/langfuse:2 \
  --port 3001:3000 \
  --env DATABASE_URL=postgresql://postgres:postgres@infra-postgres:5432/langfuse_db \
  --env NEXTAUTH_SECRET=mysecret \
  --depends-on postgres \
  --memory 1024M \
  --cpus 0.5 \
  --isolation none
```

Các tùy chọn:

| Option | Mô tả | Mặc định |
|--------|-------|----------|
| `--image` | Docker image (bắt buộc) | — |
| `--port`, `-p` | Port mapping (lặp lại được) | — |
| `--env`, `-e` | Biến môi trường KEY=VALUE | — |
| `--depends-on`, `-d` | Phụ thuộc service khác | — |
| `--memory` | Giới hạn RAM | 512M |
| `--cpus` | Giới hạn CPU | 0.5 |
| `--isolation` | Loại isolation: `none`, `database`, `db_number`, `prefix`, `bucket`, `api_key` | none |
| `--volume`, `-v` | Volume mount | — |
| `--command` | Container command | — |

### 4.7 Xóa infrastructure service

```bash
sc infra remove langfuse
```

### 4.8 Tái tạo config files

Khi thay đổi `registry.yaml` thủ công hoặc sau khi thêm/xóa service:

```bash
sc infra generate
```

---

## 5. Quản lý Project

### 5.1 Đăng ký project mới

```bash
# Tự động lấy tên thư mục làm project name
sc project add C:\Projects\MyNewProject

# Hoặc chỉ định tên
sc project add C:\Projects\MyNewProject --name my_project
```

Khi đăng ký, controller tự động cấp phát:
- **PostgreSQL database**: `my_project_db`
- **Redis DB number**: số tiếp theo chưa dùng (vd: `3`)
- **Milvus collection prefix**: `my_project_`
- **Elasticsearch index prefix**: `my_project_`
- **MinIO bucket**: `my_project-bucket`
- **Port range**: 10 port liên tiếp (vd: `8030-8039`)

### 5.2 Liệt kê project

```bash
sc project list
```

### 5.3 Xóa project khỏi registry

```bash
sc project remove my_project
```

> Lưu ý: Lệnh này chỉ xóa khỏi registry, không xóa code hay data thực tế.

### 5.4 Khởi động project

```bash
# Tự động khởi động infra nếu chưa chạy
sc project up rag_single_agent
```

### 5.5 Dừng project

```bash
sc project down rag_single_agent
```

### 5.6 Xem/tạo file .env

```bash
# In ra terminal
sc project env rag_single_agent

# Ghi ra file
sc project env rag_single_agent --output C:\Projects\Rag_Service\.env
```

File `.env` được tạo tự động có dạng:

```env
# Auto-generated by service-controller for: rag_single_agent

DATABASE_URL=postgresql://postgres:postgres@infra-postgres:5432/rag_single_agent_db
REDIS_URL=redis://infra-redis:6379/0
MILVUS_HOST=infra-milvus
MILVUS_PORT=19530
MILVUS_COLLECTION_PREFIX=rag_single_agent_
ELASTICSEARCH_URL=http://infra-elasticsearch:9200
ELASTICSEARCH_INDEX_PREFIX=rag_single_agent_
MINIO_ENDPOINT=infra-minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=rag_single_agent-bucket
```

---

## 6. Các lệnh tắt tiện lợi

### 6.1 Khởi động tất cả (infra + projects)

```bash
# Tất cả project enabled
sc up

# Chỉ định project cụ thể
sc up rag_single_agent llmops
```

### 6.2 Dừng tất cả

```bash
sc down
```

### 6.3 Xem tổng quan

```bash
sc status
```

Hiển thị cả trạng thái infrastructure lẫn project trong 1 màn hình.

---

## 7. Infrastructure Services có sẵn

| Service | Container | Port(s) | Mô tả | Isolation |
|---------|-----------|---------|-------|-----------|
| PostgreSQL + pgvector | infra-postgres | 5432 | Relational DB chính | database name |
| Redis | infra-redis | 6379 | Cache, message queue | DB number (0-15) |
| MinIO | infra-minio | 9000, 9001 | Object storage (S3-compatible) | bucket name |
| Milvus | infra-milvus | 19530, 9091 | Vector database | collection prefix |
| Elasticsearch | infra-elasticsearch | 9200 | Full-text search | index prefix |
| etcd | infra-etcd | internal | Metadata cho Milvus | none |
| cAdvisor | infra-cadvisor | 8080 | Docker container metrics | none |
| Prometheus | infra-prometheus | 9090 | Time-series metrics | none |
| Grafana | infra-grafana | 3000 | Dashboard | none |
| Langfuse | infra-langfuse | 3001 | LLM trace monitoring | none |

---

## 8. Monitoring

| Tool | URL | Credentials | Mục đích |
|------|-----|-------------|----------|
| Grafana | http://localhost:3000 | admin / admin | Dashboard tổng quan |
| Prometheus | http://localhost:9090 | — | Query metrics (PromQL) |
| cAdvisor | http://localhost:8080 | — | Realtime container stats |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin | Quản lý object storage |
| Langfuse | http://localhost:3001 | (đăng ký tại UI) | LLM observability |

### Prometheus queries hữu ích

```promql
# Container nào đang dùng hơn 80% RAM limit?
container_memory_usage_bytes{name=~"infra-.*"}
  / container_spec_memory_limit_bytes{name=~"infra-.*"} > 0.8

# Top 5 container dùng nhiều CPU nhất
topk(5, rate(container_cpu_usage_seconds_total{name=~"infra-.*"}[5m]))
```

---

## 9. Phân bổ tài nguyên (máy 32GB RAM)

```
Tổng RAM máy:              32 GB
├── OS + IDE + browser:      6 GB  (reserved)
├── Infra services:        ~14 GB  (limit, thực tế dùng ít hơn)
├── App services:           ~6 GB  (2GB × 3 project)
├── Monitoring:              1 GB
└── Free:                   ~5 GB  (headroom)
```

| Kịch bản | RAM thực tế | RAM còn trống |
|----------|-------------|---------------|
| 1 project | ~8-10 GB | ~22 GB |
| 2 project | ~12-14 GB | ~18 GB |
| 3 project + monitoring | ~16-18 GB | ~14 GB |

---

## 10. Cấu hình nâng cao

### 10.1 Thay đổi đường dẫn registry

```bash
# Dùng biến môi trường
export SC_REGISTRY=/path/to/registry.yaml

# Hoặc dùng flag
sc --registry /path/to/registry.yaml status
```

### 10.2 Chỉnh sửa registry.yaml trực tiếp

File `registry.yaml` là nguồn dữ liệu chính (single source of truth). Có thể chỉnh sửa trực tiếp, sau đó chạy:

```bash
sc infra generate
sc infra restart
```

### 10.3 Kết nối từ host (ngoài Docker)

Khi kết nối từ IDE hoặc tool trên máy host (không trong Docker container), dùng `localhost` thay vì container name:

```
PostgreSQL:    localhost:5432
Redis:         localhost:6379
MinIO:         localhost:9000 (API), localhost:9001 (Console)
Milvus:        localhost:19530
Elasticsearch: localhost:9200
```

---

## 11. Troubleshooting

### Port đã bị chiếm

```bash
# Kiểm tra port nào đang bị dùng
# Windows
netstat -ano | findstr :5432

# Linux/macOS
lsof -i :5432
```

Giải pháp: Dừng process đang chiếm port, hoặc thay đổi port trong `registry.yaml`.

### Container không start được

```bash
# Xem logs
docker logs infra-postgres
docker logs infra-milvus

# Xem chi tiết
docker inspect infra-postgres
```

### Database chưa được tạo

Nếu postgres đã chạy trước khi thêm project mới, database sẽ được tạo tự động khi chạy `sc project up`. Hoặc tạo thủ công:

```bash
docker exec -it infra-postgres psql -U postgres -c "CREATE DATABASE my_project_db;"
docker exec -it infra-postgres psql -U postgres -d my_project_db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Reset toàn bộ

```bash
sc down
sc infra down --volumes   # XÓA TOÀN BỘ DATA
sc init --workspace C:\Projects
sc up
```
