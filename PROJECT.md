# Agent Platform

## Overview
Nền tảng phục vụ AI Agent (Agent Serving Platform) — tạo, triển khai, và vận hành AI agent ở quy mô production.

## Documentation

### Background
- [`init.md`](init.md) — Giới thiệu khái niệm Agent Platform (tài liệu nền tảng)

### Research
- [`docs/research/01-problem-analysis.md`](docs/research/01-problem-analysis.md) — Phân tích bài toán
- [`docs/research/02-market-research.md`](docs/research/02-market-research.md) — Nghiên cứu thị trường
- [`docs/research/03-architecture-patterns.md`](docs/research/03-architecture-patterns.md) — Mẫu kiến trúc

### Scope
- [`docs/scope/01-project-scope.md`](docs/scope/01-project-scope.md) — Phạm vi dự án
- [`docs/scope/02-user-personas.md`](docs/scope/02-user-personas.md) — Đối tượng sử dụng
- [`docs/scope/03-requirements.md`](docs/scope/03-requirements.md) — Yêu cầu hệ thống

### Architecture
- [`docs/architecture/00-overview.md`](docs/architecture/00-overview.md) — Kiến trúc tổng quan (high-level)
- [`docs/architecture/guardrails/design.md`](docs/architecture/guardrails/design.md) — Thiết kế chi tiết: Guardrails Engine
- [`docs/architecture/memory/design.md`](docs/architecture/memory/design.md) — Thiết kế chi tiết: Memory System
- [`docs/architecture/planning/design.md`](docs/architecture/planning/design.md) — Thiết kế chi tiết: Planning & Execution Engine
- [`docs/architecture/mcp-tools/design.md`](docs/architecture/mcp-tools/design.md) — Thiết kế chi tiết: MCP & Tool System

## Tech Stack (Phase 1)
- **Language:** Python 3.12+
- **Framework:** FastAPI
- **Database:** PostgreSQL 16 + pgvector
- **Cache/Queue:** Redis 7 (Streams)
- **Tracing:** OpenTelemetry
- **Container:** Docker / Kubernetes
- **Tool Protocol:** MCP (Model Context Protocol)

## Phase Roadmap
1. **Phase 1 (MVP):** Core runtime, MCP tools, session management, observability, Python SDK
2. **Phase 2 (Scale):** Multi-tenant, multi-agent, RBAC, TypeScript SDK, on-premise
3. **Phase 3 (Ecosystem):** Marketplace, visual builder, A2A, edge runtime
