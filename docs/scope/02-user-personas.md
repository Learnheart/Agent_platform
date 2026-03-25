# Đối Tượng Sử Dụng: User Personas

> **Phiên bản:** 1.0
> **Ngày tạo:** 2026-03-25
> **Tác giả:** AI Project Manager & Lead Architect

---

## Tổng Quan

Nền tảng Agent Platform phục vụ 6 persona chính, chia thành 2 nhóm:

```
┌────────────────────────────────────────────────────────┐
│                    PRIMARY USERS                        │
│  (Trực tiếp sử dụng platform)                         │
│                                                        │
│  👤 Agent Builder     👤 AI/ML Engineer  👤 Startup CTO  │
│     (Priya)              (Marcus)            (Elena)     │
├────────────────────────────────────────────────────────┤
│                   STAKEHOLDER USERS                     │
│  (Ảnh hưởng quyết định adoption)                       │
│                                                        │
│  👤 Enterprise Arch   👤 IT Ops Lead   👤 Compliance    │
│     (Sarah)              (James)          (David)       │
└────────────────────────────────────────────────────────┘
```

---

## Persona 1: AI/ML Engineer — "Marcus"

### Profile

| Thuộc tính | Chi tiết |
|------------|----------|
| **Vai trò** | Senior AI/ML Engineer tại SaaS company trung bình (~200 người) |
| **Technical level** | Expert. Xây custom models, fine-tune LLMs, viết production Python + infra |
| **Kinh nghiệm** | 5-8 năm ML/AI, 2-3 năm với LLM agents |

### Bài toán cần giải quyết
- Tốn quá nhiều thời gian vào infrastructure (memory management, orchestration, error handling, retry logic) thay vì agent logic
- Cần agent chạy reliable trong production ở scale
- Debugging agent decision-making rất khó với tools hiện tại

### Pain Points hiện tại
- LangChain/AutoGen ổn cho prototype nhưng brittle trong production
- Multi-agent coordination khó implement reliable
- Observability vào agent reasoning gần như không có
- Manual scaling và deployment tốn effort

### Nhu cầu từ Platform
- **API-first design** (không phải GUI-first)
- **Extensible architecture** không giới hạn advanced use cases
- **Built-in tracing** cho mọi LLM call, tool invocation, memory read/write
- **Production-grade orchestration** với fault tolerance
- **Bring-your-own-model** support
- **Performance profiling** tools

### Thước đo thành công
| Metric | Target |
|--------|--------|
| Giảm infrastructure code | > 50% |
| Agent uptime | > 99.9% |
| Thời gian debug agent issues | Giảm 70% |
| Ship agent features | Weekly thay vì monthly |

### Quote
> _"Tôi không muốn viết lại retry logic, checkpoint system, hay tracing infrastructure cho mỗi project. Cho tôi một platform ổn định để tôi focus vào agent behavior."_

---

## Persona 2: Startup CTO — "Elena"

### Profile

| Thuộc tính | Chi tiết |
|------------|----------|
| **Vai trò** | CTO & co-founder, B2B startup 15 người |
| **Technical level** | Expert. Full-stack, system design, ML experience |
| **Kinh nghiệm** | 10+ năm software engineering, 3 năm AI |

### Bài toán cần giải quyết
- AI agent là core product feature, nhưng không đủ resource build infra từ đầu
- Team 4 engineers phải focus vào domain-specific value, không phải plumbing
- Cần scale từ 10 beta users → 10,000 production users không cần re-architect

### Pain Points hiện tại
- Raw LLM APIs = quá nhiều undifferentiated work
- OSS frameworks thiếu production readiness (no multi-tenancy, poor error handling, no auth)
- Lo ngại vendor lock-in với proprietary platforms
- Budget hạn chế

### Nhu cầu từ Platform
- **Generous free tier** hoặc startup pricing
- **API-first với SDKs** đầy đủ
- **Multi-tenant support** (mỗi customer = 1 tenant)
- **White-label/embeddable** UI components
- **Usage-based pricing** scales với business
- **Model provider switching** capability
- **< 100ms platform overhead**

### Thước đo thành công
| Metric | Target |
|--------|--------|
| Time to MVP | < 4 tuần |
| Platform cost vs total COGS | < 15% |
| Platform-caused outages | Zero |
| Scale support | 100x user growth không cần migration |

### Quote
> _"Team tôi có 4 engineers. Mỗi giờ code infrastructure là 1 giờ mất đi cho product. Platform phải là force multiplier, không phải thêm dependency."_

---

## Persona 3: Agent Builder — "Priya"

### Profile

| Thuộc tính | Chi tiết |
|------------|----------|
| **Vai trò** | Agent Builder — người tạo và quản lý AI agent trên platform |
| **Technical level** | Moderate. Có kiến thức về xây dựng agent nhưng không code. Cần môi trường low/no-code để tạo, cấu hình, và quản lý agent. |
| **Kinh nghiệm** | 8 năm business analysis, 2 năm dùng AI tools và low-code platforms |

### Bài toán cần giải quyết
- Automate document review và data extraction tốn 60% thời gian team
- Đang đợi 3-6 tháng trong IT backlog cho automation requests
- Muốn tự build agent mà không cần developer
- Cần tạo, cấu hình, và quản lý agent thông qua giao diện trực quan

### Pain Points hiện tại
- Hoàn toàn phụ thuộc engineering team cho AI automation
- Low-code tools hiện tại không có AI agent capabilities
- Không thể experiment hay iterate mà không có developer
- Frustrated bởi delivery chậm

### Nhu cầu từ Platform
- **Web UI config-based** (Phase 1) để tạo và quản lý agent qua form
- **Visual drag-and-drop workflow builder** (Phase 2)
- **Pre-built templates** cho common use cases
- **Natural language configuration** ("khi invoice đến, extract total và vendor, update spreadsheet")
- **Guardrails** prevent misconfiguration
- **Cost visibility** rõ ràng

### Thước đo thành công
| Metric | Target |
|--------|--------|
| Tạo agent đầu tiên qua Web UI | < 15 phút |
| Build & deploy working agent | < 1 ngày, không cần dev help |
| Document extraction accuracy | > 80% |
| Thời gian tiết kiệm mỗi tuần | Measurable |

### Quote
> _"Tôi biết rõ quy trình nghiệp vụ hơn bất kỳ developer nào. Nếu tool đủ đơn giản, tôi có thể tự build agent tốt hơn và nhanh hơn."_

**Note:** Priya là PRIMARY persona từ Phase 1 với Web UI config-based. Phase 2 nâng cấp trải nghiệm với visual workflow builder.

---

## Persona 4: Enterprise Architect — "Sarah"

### Profile

| Thuộc tính | Chi tiết |
|------------|----------|
| **Vai trò** | VP of Engineering / Enterprise Architect, Fortune 500 financial services |
| **Technical level** | Rất cao. 15+ năm architecture. Không viết code hàng ngày nhưng review designs |
| **Kinh nghiệm** | 15+ năm software architecture, 3 năm AI strategy |

### Bài toán cần giải quyết
- Chuẩn hóa cách AI agent được xây và deploy across 20+ business units
- Shadow AI proliferation — team khác nhau dùng framework khác nhau, không governance
- Đảm bảo data residency và compliance requirements

### Pain Points hiện tại
- Không có centralized view các AI agent deployments
- Không enforce được data governance policies
- Khó measure ROI across fragmented initiatives
- Mỗi team tự build = duplicated effort

### Nhu cầu từ Platform
- **Centralized governance console**
- **Multi-tenant với business-unit isolation**
- **Policy-as-code enforcement**
- **Model registry** với approved model list
- **Comprehensive audit logging**
- **SSO/RBAC** integration
- **On-premise / private cloud** deployment option

### Thước đo thành công
| Metric | Target |
|--------|--------|
| Time-to-deploy cho new agent use case | Months → weeks |
| Compliance với governance policies | 100% |
| Cost reduction vs manual processes | Measurable |
| Adoption rate across business units | Tăng quarter-over-quarter |

### Quote
> _"Tôi không chặn innovation. Tôi cần một platform cho phép teams innovate trong guardrails mà compliance team chấp nhận được."_

---

## Persona 5: IT Operations Lead — "James"

### Profile

| Thuộc tính | Chi tiết |
|------------|----------|
| **Vai trò** | Director of IT Operations, large retail company |
| **Technical level** | Moderate-to-high. Infra, networking, security. Script PowerShell/Bash |
| **Kinh nghiệm** | 12 năm IT operations, 2 năm AI tools |

### Bài toán cần giải quyết
- 50,000+ IT support tickets/tháng, Tier 1 resolution rate chỉ 40%
- 60% tickets cần expensive specialist time
- Helpdesk turnover 35%/năm

### Pain Points hiện tại
- Chatbot rule-based, brittle, mỗi FAQ mới cần manual programming
- Không integration giữa chatbot và backend systems (chỉ trả lời, không thực thi)
- User không trust bot → low adoption

### Nhu cầu từ Platform
- **Pre-built IT helpdesk agent template**
- **Deep ServiceNow/Jira integration**
- **Execute actions** (reset password, provision software), không chỉ answer
- **Confidence scoring** và graceful escalation
- **Analytics dashboard**: deflection rate, resolution time, CSAT
- **SOC 2 compliance**

### Thước đo thành công
| Metric | Target |
|--------|--------|
| Tier 1 deflection rate | > 70% |
| Average resolution time | Giảm 50% |
| Employee satisfaction (CSAT) | > 4.0/5.0 |
| Annual cost savings | > $1M |

### Quote
> _"Bot hiện tại chỉ trả lời 'bạn hãy thử restart máy'. Tôi cần agent thật sự RESET được password, PROVISION được phần mềm, và biết khi nào cần chuyển cho người."_

---

## Persona 6: Compliance Officer — "David"

### Profile

| Thuộc tính | Chi tiết |
|------------|----------|
| **Vai trò** | Chief Compliance Officer, regulated financial institution |
| **Technical level** | Thấp. Hiểu regulatory frameworks sâu nhưng dựa vào tech teams |
| **Kinh nghiệm** | 20 năm compliance, 3 năm AI governance |

### Bài toán cần giải quyết
- Đảm bảo mọi AI agent deployment đáp ứng regulatory requirements
- Regulators hỏi ngày càng nhiều về AI governance
- Cần visibility vào agent đang làm gì và access data gì

### Pain Points hiện tại
- Không centralized view AI agent deployments
- Không explain được agent decisions
- Không enforce data access policies trên agents
- Audit preparation manual, tốn hàng tuần

### Nhu cầu từ Platform
- **Comprehensive audit logging** tamper-proof
- **Explainability features** (decision traces, source citations)
- **Data access controls** và DLP integration
- **Model inventory** và risk assessment
- **Compliance reporting** dashboards
- **Policy enforcement** ("no agent may access PII without explicit consent")

### Thước đo thành công
| Metric | Target |
|--------|--------|
| Deployed agents in model inventory | 100% |
| Compliance findings related to AI | Zero |
| Audit preparation time | Giảm 80% |
| Regulatory response capability | Clear and immediate |

### Quote
> _"Tôi không cần hiểu code. Tôi cần biết: agent này access data gì, quyết định thế nào, và ai chịu trách nhiệm."_

---

## Priority Matrix: Persona × Phase

| Persona | Phase 1 (MVP) | Phase 2 (Scale) | Phase 3 (Ecosystem) |
|---------|---------------|------------------|---------------------|
| **Priya** (Agent Builder) | **PRIMARY** | Primary | Primary |
| **Sarah** (Enterprise Architect) | Secondary | **PRIMARY** | Primary |
| **James** (IT Ops Lead) | Secondary | **PRIMARY** | Primary |
| **David** (Compliance Officer) | Secondary | Secondary | **PRIMARY** |
| **Marcus** (AI/ML Engineer) | Secondary | **PRIMARY** | Primary |
| **Elena** (Startup CTO) | Secondary | **PRIMARY** | Secondary |

**Phase 1 focus:** Priya (Agent Builder) — Web UI config-based, tạo và quản lý agent không cần code.
**Phase 2 focus:** Marcus và Elena (SDK users), Sarah — developer-centric SDK integration và enterprise features.
