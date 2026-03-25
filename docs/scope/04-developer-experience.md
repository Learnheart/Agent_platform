# Trải Nghiệm Người Dùng: Agent Platform

> **Phiên bản:** 2.0
> **Ngày cập nhật:** 2026-03-25

---

## 1. Mục Tiêu UX

**"15-Minute Test":** Từ đăng nhập đến agent đầu tiên chạy, gọi tool, trả kết quả trong 15 phút.

**Đối tượng:** Tài liệu này mô tả trải nghiệm của **Builder** — người tạo và quản lý agent trên platform. Builder truy cập Management UI + API.

> **End User** (người dùng agent đã tạo sẵn) tương tác qua Session API — platform không cung cấp UI cho end user. Xem [03-requirements.md § FR-EU](03-requirements.md) cho End User requirements.

**Người dùng mục tiêu:** Agent Builder — có kiến thức về AI agent nhưng không cần viết code. Môi trường low/no-code.

---

## 2. Nguyên Tắc UX

| # | Nguyên tắc | Ý nghĩa |
|---|-----------|---------|
| 1 | **Zero code** | Tạo agent hoạt động chỉ bằng cấu hình trên UI |
| 2 | **Mặc định hợp lý** | Config optional, convention over configuration |
| 3 | **Phản hồi tức thì** | Mọi action có feedback ngay (loading, success, error) |
| 4 | **Lỗi rõ ràng** | Error messages có hướng dẫn sửa cụ thể |
| 5 | **Xem trước khi chạy** | Preview agent config trước khi deploy |

---

## 3. Luồng Người Dùng Phase 1

### 3.1 Tạo Agent

```
Đăng nhập → Dashboard → "Tạo Agent Mới"
    ↓
Form cấu hình:
  - Tên agent
  - System prompt (textarea với gợi ý)
  - Chọn model (dropdown: Claude Sonnet, Claude Haiku...)
  - Chọn MCP tools (checklist từ tool registry)
  - Cấu hình guardrails:
    - Budget (token limit, cost limit, step limit)
    - Tool permissions (allow/deny/require approval)
  - Cấu hình memory (context strategy dropdown)
    ↓
Preview → Tạo → Agent sẵn sàng
```

### 3.2 Test Agent (Builder Chat)

> Chat interface trên Management UI là để **Builder test agent**. End User không dùng UI này — họ tương tác qua Session API.

```
Agent detail page → "Test Chat"
    ↓
Builder chat interface (test & debug):
  - Gửi message như end user sẽ gửi
  - Xem streaming response (SSE)
  - Xem tool calls real-time (debug info — end user không thấy)
  - Xem thinking/reasoning steps (debug info)
    ↓
Session list: trạng thái, chi phí, số steps, thời gian
```

### 3.3 Monitoring & Debug

```
Session detail → Execution Trace
    ↓
Timeline view:
  - Mỗi step: thought → tool call → observation → answer
  - Chi phí mỗi step
  - Latency mỗi step
  - Guardrail checks (pass/fail)
    ↓
Nếu lỗi: hiển thị nguyên nhân + gợi ý sửa
```

---

## 4. Agent Config Model (UI Form → API)

UI form tạo ra JSON config gửi đến API:

```json
{
  "name": "customer-support-v1",
  "system_prompt": "Bạn là agent hỗ trợ khách hàng...",
  "model": "claude-sonnet-4-6",
  "mcp_servers": [
    {"name": "crm", "url": "http://crm-mcp:3000"}
  ],
  "config": {
    "max_steps": 20,
    "max_tokens_budget": 30000,
    "max_cost_usd": 2.0,
    "context_strategy": "summarize_recent"
  },
  "guardrails": {
    "tool_permissions": [
      {"tool_pattern": "crm:read_*", "actions": ["invoke"]},
      {"tool_pattern": "crm:delete_*", "requires_approval": true}
    ]
  }
}
```

---

## 5. Trang Management UI Phase 1 (Builder only)

> Tất cả trang dưới đây chỉ dành cho Builder. End User không truy cập Management UI.

| Trang | Chức năng | Đối tượng |
|-------|----------|-----------|
| **Dashboard** | Tổng quan: số agent, sessions đang chạy, chi phí tổng | Builder |
| **Agent List** | Danh sách agent, trạng thái, actions (edit, delete, test) | Builder |
| **Agent Create/Edit** | Form cấu hình agent (system prompt, model, tools, guardrails) | Builder |
| **Agent Detail** | Config hiện tại, session history, metrics, Session API endpoint | Builder |
| **Session List** | Danh sách sessions (cả builder test + end user), filter theo agent/trạng thái/thời gian | Builder |
| **Test Chat** | Chat interface để builder test agent, xem debug info (tool calls, reasoning) | Builder |
| **Session Trace** | Timeline execution trace, chi phí, guardrail checks | Builder |
| **Tool Registry** | Danh sách MCP servers và tools đã kết nối | Builder |
| **Settings** | API keys, LLM provider config, End User auth config | Builder |

---

## 6. Phase 2: Visual Workflow Builder

Phase 2 thêm drag-and-drop workflow builder cho phép:
- Kéo thả các bước (LLM call, tool call, condition, loop)
- Nối các bước thành workflow
- Cấu hình từng bước bằng form
- Preview và test workflow trước khi deploy
- Hỗ trợ Plan-then-Execute pattern qua visual interface

---

## 7. Onboarding Timeline (15 phút)

| Thời gian | Hành động |
|-----------|----------|
| 0-2 phút | Đăng ký, đăng nhập, xem dashboard |
| 2-5 phút | Tạo agent đầu tiên (chỉ system prompt + model) |
| 5-10 phút | Thêm MCP tools, cấu hình guardrails |
| 10-15 phút | Chat multi-turn, xem execution trace |

---

## 8. Tech Stack Frontend

| Thành phần | Công nghệ | Ghi chú |
|-----------|----------|---------|
| Framework | Next.js / React | SSR + SPA, ecosystem lớn |
| UI Library | shadcn/ui hoặc Ant Design | Component sẵn, phát triển nhanh |
| State | React Query (TanStack) | Server state management |
| Streaming | EventSource API (SSE) | Real-time agent response |
| Styling | Tailwind CSS | Utility-first, nhanh |
| Visual Builder (Phase 2) | React Flow | Drag-and-drop workflow editor |

Ưu tiên: framework bậc cao, phát triển nhanh nhất có thể. Frontend không phải core priority — backend là giá trị chính của platform.
