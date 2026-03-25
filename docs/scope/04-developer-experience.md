# Developer Experience: Agent Serving Platform

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect
> **Bối cảnh:** Bổ sung sau review — gap lớn nhất trong tài liệu gốc là thiếu DX spec

---

## 1. Mục Tiêu DX

### 1.1 "15-Minute Test"

Developer phải có thể đi từ `pip install` đến **agent chạy được, gọi tool, nhận response** trong 15 phút. Nếu không đạt được, cần redesign.

### 1.2 DX Principles

| # | Nguyên tắc | Ý nghĩa |
|---|-----------|---------|
| 1 | **Zero boilerplate** | Tạo agent chạy được < 10 dòng code |
| 2 | **Sensible defaults** | Config chỉ cần khi muốn customize, không bắt buộc |
| 3 | **Opinionated thin SDK** | SDK handle plumbing (auth, session, streaming, tool registration), developer tự viết agent logic |
| 4 | **Fail loud, fix fast** | Error messages rõ ràng, actionable, có link đến docs |
| 5 | **Local-first development** | Có thể dev/test local trước khi deploy lên platform |

---

## 2. SDK Positioning: "Opinionated Thin"

### 2.1 Vấn đề cần giải quyết

SDK quá thin (chỉ là HTTP client wrapper) → developer không có lý do dùng platform thay vì gọi thẳng LLM API.
SDK quá thick (nhiều abstractions) → thành framework, cạnh tranh với LangGraph — đây không phải bài toán của chúng ta.

### 2.2 Giải pháp: "Opinionated Thin"

**SDK handle (platform plumbing):**
- Authentication (API key setup)
- Session lifecycle (create, send message, stream, pause, resume)
- Tool registration (khai báo MCP servers hoặc custom tools)
- Event streaming (real-time nhận từng step)
- Cost tracking (xem usage)
- Error handling (structured errors, retries)

**Developer tự viết (agent logic):**
- System prompt / agent behavior
- Tool selection & configuration
- Business rules & workflow
- Response post-processing

**Tương tự:** Docker SDK. Thin, nhưng ai cũng dùng vì nó là cách duy nhất nói chuyện với Docker daemon — và Docker daemon cung cấp infrastructure mà bạn không muốn tự build.

---

## 3. "Hello World" — Agent Đầu Tiên

### 3.1 Minimal Agent (5 dòng)

```python
from agent_platform import AgentPlatform

platform = AgentPlatform(api_key="sk-...")

agent = platform.agents.create(
    name="hello-agent",
    system_prompt="You are a helpful assistant.",
    model="claude-sonnet-4-6",
)

response = platform.sessions.run(agent_id=agent.id, message="Hello!")
print(response.content)
```

**Kết quả:** Agent chạy 1 turn, không tool, trả text response. Đây là "Hello World" — phải chạy được trong < 2 phút.

### 3.2 Agent với Tool (10 dòng thêm)

```python
agent = platform.agents.create(
    name="search-agent",
    system_prompt="You answer questions using web search.",
    model="claude-sonnet-4-6",
    mcp_servers=[
        {"name": "brave-search", "url": "http://localhost:3000/mcp"},
    ],
)

# Streaming session
session = platform.sessions.create(agent_id=agent.id)

for event in session.stream("What is the latest news about AI agents?"):
    if event.type == "text_delta":
        print(event.content, end="", flush=True)
    elif event.type == "tool_call":
        print(f"\n[Calling: {event.tool_name}]")
    elif event.type == "tool_result":
        print(f"[Result received]")
```

### 3.3 Multi-Turn Conversation

```python
session = platform.sessions.create(agent_id=agent.id)

# Turn 1
session.send("Find restaurants near me in Hanoi")

# Turn 2 (session tự giữ context)
session.send("Which one has the best reviews?")

# Turn 3
response = session.send("Book a table for 2 at 7pm")
print(response.content)

# Xem full trace
trace = session.get_trace()
for step in trace.steps:
    print(f"Step {step.index}: {step.type} → {step.status} ({step.duration_ms}ms)")
```

### 3.4 Agent Definition qua YAML (optional, cho deployment)

```yaml
# agents/customer-support.yaml
name: customer-support-v1
model: claude-sonnet-4-6
system_prompt: |
  You are a customer support agent for Acme Corp.
  Always be polite and helpful. If you don't know the answer,
  escalate to a human agent.

mcp_servers:
  - name: crm
    url: ${CRM_MCP_URL}
  - name: knowledge-base
    url: ${KB_MCP_URL}

config:
  max_steps: 20
  max_tokens: 30000
  max_duration_seconds: 300

guardrails:
  tool_permissions:
    - pattern: "crm:read_*"
    - pattern: "crm:update_*"
    - pattern: "crm:delete_*"
      requires_approval: true
  budget:
    max_cost_per_session_usd: 2.0
```

```python
# Deploy từ YAML
agent = platform.agents.deploy_from_file("agents/customer-support.yaml")
```

---

## 4. Developer Workflow

### 4.1 Lifecycle tổng thể

```
1. Install     →  pip install agent-platform
2. Configure   →  agent-platform init (tạo config file, API key)
3. Define      →  Viết agent (Python hoặc YAML)
4. Test local  →  agent-platform run --local (chạy agent với mock/real LLM)
5. Deploy      →  agent-platform deploy (push lên platform)
6. Monitor     →  Dashboard / CLI / API xem traces, costs
7. Iterate     →  Sửa prompt/tools → redeploy
```

### 4.2 CLI Tool

```bash
# Setup
pip install agent-platform
agent-platform init                          # Interactive setup: API key, project name

# Development
agent-platform run agent.yaml               # Chạy local, interactive chat trong terminal
agent-platform run agent.yaml --test        # Chạy test cases
agent-platform run agent.yaml --verbose     # Show từng step: thought → action → observation

# Deploy
agent-platform deploy agent.yaml            # Deploy lên platform
agent-platform list                          # List deployed agents
agent-platform logs <agent-id>              # Xem logs
agent-platform trace <session-id>           # Xem execution trace chi tiết

# Debug
agent-platform replay <session-id>          # Replay một session từ checkpoint
agent-platform replay <session-id> --step 5 # Replay từ step 5
```

### 4.3 Debug Experience

**Vấn đề:** Agent fails ở step 7 của 12 steps. Developer cần hiểu tại sao.

**Trải nghiệm debug:**

```bash
$ agent-platform trace sess_abc123

Session: sess_abc123
Agent: customer-support-v2
Status: FAILED (step 7/12)
Duration: 45.2s | Cost: $0.034 | Tokens: 12,450

Step 1  [THOUGHT]    0.8s   "User wants to check order status..."
Step 2  [TOOL_CALL]  1.2s   crm:get_order(order_id="ORD-789")  ✅
Step 3  [THOUGHT]    0.6s   "Order is delayed, need shipping info..."
Step 4  [TOOL_CALL]  0.9s   crm:get_shipping(order_id="ORD-789")  ✅
Step 5  [THOUGHT]    0.7s   "Carrier API shows delay. Update customer..."
Step 6  [TOOL_CALL]  0.3s   crm:update_ticket(id="T-456", status="in_progress")  ✅
Step 7  [TOOL_CALL]  ---    email:send_notification(...)  ❌ DENIED
  └─ Reason: Tool 'email:send_notification' not in agent's allowed tool list
  └─ Fix: Add "email:send_notification" to agent's mcp_servers or tool_permissions

$ agent-platform replay sess_abc123 --step 7 --fix
# Opens interactive session from step 7 with agent definition editable
```

**Key DX insight:** Error message phải nói **tại sao fail** và **cách fix**, không chỉ error code.

---

## 5. Onboarding Journey (15-Minute Getting Started)

### Phút 0-2: Install & Auth

```bash
pip install agent-platform
agent-platform init
# → Prompts: API key, default model, project name
# → Creates .agent-platform/config.yaml
```

### Phút 2-5: First Agent

```python
# quickstart.py
from agent_platform import AgentPlatform

platform = AgentPlatform()  # auto-reads config

agent = platform.agents.create(
    name="my-first-agent",
    system_prompt="You are a helpful assistant that can search the web.",
    model="claude-sonnet-4-6",
)

response = platform.sessions.run(
    agent_id=agent.id,
    message="What happened in tech news today?",
)
print(response.content)
```

```bash
python quickstart.py
# → Agent responds with answer (no tools yet, just LLM)
```

### Phút 5-10: Add Tools

```python
# Thêm MCP server
agent = platform.agents.update(
    agent_id=agent.id,
    mcp_servers=[
        {"name": "brave-search", "transport": "stdio", "command": "npx @anthropic/mcp-brave-search"},
    ],
)

# Chạy lại — lần này agent sẽ dùng tool
for event in platform.sessions.stream(agent_id=agent.id, message="Latest AI news?"):
    if event.type == "text_delta":
        print(event.content, end="")
    elif event.type == "tool_call":
        print(f"\n🔧 {event.tool_name}({event.input})")
```

### Phút 10-15: Multi-turn + Trace

```python
session = platform.sessions.create(agent_id=agent.id)
session.send("Search for recent AI agent frameworks")
session.send("Compare the top 3")
response = session.send("Which one is best for production use?")

# Xem trace
trace = session.get_trace()
print(f"Steps: {trace.total_steps}, Cost: ${trace.total_cost:.3f}")
for step in trace.steps:
    print(f"  {step.index}. [{step.type}] {step.summary} ({step.duration_ms}ms)")
```

**Kết quả sau 15 phút:** Developer đã có agent chạy multi-turn với tool use, có thể xem execution trace. Từ đây, developer khám phá thêm: guardrails, streaming, deployment.

---

## 6. SDK Interface Design (Python)

### 6.1 Core Classes

```python
class AgentPlatform:
    """Entry point. Handles auth, config, connection."""
    agents: AgentService
    sessions: SessionService
    tools: ToolService

class AgentService:
    def create(self, name, system_prompt, model, mcp_servers=None, config=None, guardrails=None) -> Agent
    def get(self, agent_id) -> Agent
    def update(self, agent_id, **kwargs) -> Agent
    def delete(self, agent_id) -> None
    def list(self, **filters) -> list[Agent]
    def deploy_from_file(self, path) -> Agent

class SessionService:
    def create(self, agent_id, metadata=None) -> Session
    def run(self, agent_id, message) -> Response            # One-shot: create + send + wait
    def stream(self, agent_id, message) -> Iterator[Event]  # One-shot streaming
    def get(self, session_id) -> SessionInfo

class Session:
    def send(self, message) -> Response
    def stream(self, message) -> Iterator[Event]
    def pause(self) -> None
    def resume(self) -> None
    def get_trace(self) -> Trace
    def get_cost(self) -> CostBreakdown
```

### 6.2 Event Types (streaming)

```python
@dataclass
class Event:
    type: str       # "text_delta" | "tool_call" | "tool_result" | "thought" |
                    # "step_start" | "step_end" | "error" | "done"
    content: str | None
    tool_name: str | None
    tool_input: dict | None
    tool_output: str | None
    step_index: int | None
    metadata: dict | None
```

### 6.3 Error Design

```python
class AgentPlatformError(Exception):
    code: str           # "TOOL_NOT_ALLOWED", "BUDGET_EXCEEDED", "SESSION_TIMEOUT"
    message: str        # Human-readable
    suggestion: str     # Actionable fix hint
    docs_url: str       # Link to relevant docs

# Example:
# AgentPlatformError(
#     code="TOOL_NOT_ALLOWED",
#     message="Tool 'email:send' is not in agent's allowed tool list.",
#     suggestion="Add 'email:send' to tool_permissions in your agent config.",
#     docs_url="https://docs.agentplatform.dev/guides/tool-permissions"
# )
```

---

## 7. So Sánh DX với Alternatives

| Aspect | Agent Platform | LangGraph | Direct LLM SDK |
|--------|---------------|-----------|-----------------|
| **Hello World** | 5 dòng, chạy ngay | ~30 dòng (graph nodes, edges, state) | 5 dòng, nhưng không có session/tools |
| **Add tools** | Khai báo MCP server URL | Define tool functions, bind to nodes | Tự implement tool calling loop |
| **Multi-turn** | `session.send()` — platform giữ state | Tự manage state + checkpointer | Tự manage conversation array |
| **Streaming** | `for event in session.stream()` | Callback-based, complex setup | Provider-specific streaming |
| **Debug** | `agent-platform trace <id>` | LangSmith (separate product) | Tự build logging |
| **Deploy** | `agent-platform deploy` | LangGraph Platform (paid) | Tự build infra |
| **Cost tracking** | Built-in, per-session | LangSmith (separate) | Tự track tokens |
| **Guardrails** | Config-based, built-in | Tự implement | Tự implement |

**Key differentiator:** LangGraph yêu cầu developer hiểu graph abstraction (nodes, edges, state schema). Agent Platform yêu cầu developer chỉ cần hiểu: system prompt + tools + config. Platform lo phần còn lại.

---

## 8. Documentation Structure (Phase 1)

```
docs.agentplatform.dev/
├── Getting Started
│   ├── Quickstart (15 minutes)             ← Mục 5 ở trên
│   ├── Installation
│   └── Configuration
├── Guides
│   ├── Creating Your First Agent
│   ├── Adding Tools (MCP)
│   ├── Streaming & Events
│   ├── Multi-turn Conversations
│   ├── Debugging with Traces
│   ├── Setting Budget & Guardrails
│   └── Deploying to Production
├── SDK Reference
│   ├── Python SDK
│   └── CLI Reference
├── API Reference
│   └── REST API (OpenAPI)
├── Concepts
│   ├── How Agents Execute
│   ├── Session & State
│   ├── Memory System
│   ├── Tool System (MCP)
│   └── Guardrails & Security
└── Examples
    ├── Customer Support Agent
    ├── Research Agent
    └── Data Analysis Agent
```

---

## 9. Phase 1 DX Checklist

| # | Tiêu chí | Đo lường |
|---|----------|----------|
| 1 | `pip install` → agent chạy | < 2 phút |
| 2 | Agent + tool use chạy | < 10 phút |
| 3 | Multi-turn + trace | < 15 phút |
| 4 | Error messages có suggestion | 100% of error types |
| 5 | CLI interactive mode hoạt động | agent-platform run --local |
| 6 | Quickstart guide viết xong | Trước khi code SDK |
| 7 | 3 example agents đầy đủ | Customer support, research, data analysis |
| 8 | API docs auto-generated | OpenAPI + SDK docstrings |
