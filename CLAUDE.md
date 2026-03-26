# Development Rules — Agent Serving Platform

> Các quy tắc dưới đây là **BẮT BUỘC**. Claude Code phải tuân thủ 100% trong mọi thao tác code.

---

## 1. Architecture-First: Đối chiếu tài liệu trước khi code

**TRƯỚC KHI viết bất kỳ dòng code nào**, bắt buộc phải:

1. Xác định module/component liên quan (Execution Engine, Memory, Guardrails, MCP Tools, LLM Gateway, Planning, Governance, ...).
2. Đọc tài liệu kiến trúc tương ứng trong `docs/architecture/` để nắm rõ thiết kế:
   - Tổng quan: `docs/architecture/00-overview.md`
   - Data Models: `docs/architecture/01-data-models.md`
   - Foundation: `docs/architecture/02-foundation.md`
   - Planning: `docs/architecture/03-planning.md`
   - LLM Gateway: `docs/architecture/04-llm-gateway.md`
   - Memory: `docs/architecture/05-memory.md`
   - MCP & Tools: `docs/architecture/06-mcp-tools.md`
   - Guardrails: `docs/architecture/07-guardrails.md`
   - Event Bus: `docs/architecture/08-event-bus.md`
   - Governance: `docs/architecture/09-governance.md`
   - API Contracts: `docs/architecture/10-api-contracts.md`
3. Đảm bảo code sắp viết **khớp** với interface, data flow, và contract đã mô tả trong tài liệu.
4. Nếu tài liệu chưa có thiết kế chi tiết (`design.md`) cho module đó, phải báo cho người dùng biết trước khi code.

---

## 2. Khai báo Next Action trước khi thực thi

**KHÔNG ĐƯỢC** bắt tay vào code ngay. Phải trình bày rõ cho người dùng:

- **Thêm mới (Add):** Liệt kê file/function/class sẽ tạo mới.
- **Cập nhật (Update):** Liệt kê file/function/class sẽ sửa đổi và mô tả thay đổi.
- **Xoá (Delete):** Liệt kê file/function/class sẽ bị xoá và lý do.
- **Module liên quan:** Ghi rõ thay đổi thuộc module nào trong kiến trúc.

Chỉ bắt đầu code **SAU KHI** người dùng xác nhận đồng ý kế hoạch.

---

## 3. Từ chối yêu cầu ngoài phạm vi kiến trúc

Nếu yêu cầu của người dùng:

- Thêm component/module **chưa có** trong tài liệu kiến trúc, hoặc
- Thay đổi data flow/interface **khác** với thiết kế đã document, hoặc
- Sử dụng công nghệ/pattern **ngoài** tech stack đã quy định

→ **DỪNG LẠI**, thông báo cho người dùng:

> "Yêu cầu này vượt quá phạm vi kiến trúc hiện tại. Vui lòng cập nhật tài liệu kiến trúc tương ứng trong `docs/architecture/` trước, sau đó tôi sẽ implement theo tài liệu mới."

Ghi rõ:
- Tài liệu nào cần cập nhật.
- Phần nào cần bổ sung/thay đổi.
- Gợi ý nội dung nếu có thể.

---

## 4. Unit Test bắt buộc sau khi implement

Sau khi hoàn thành code, **BẮT BUỘC** phải:

1. Viết unit test cho mọi function/class/module vừa tạo hoặc sửa.
2. Test phải kiểm tra đúng behavior được mô tả trong tài liệu kiến trúc — không chỉ test "code chạy được" mà test "code hoạt động đúng theo thiết kế".
3. Chạy test và đảm bảo **PASS** trước khi báo hoàn thành.
4. Nếu test fail, phải fix code cho đến khi pass — không được bỏ qua test fail.

---

## 5. Báo cáo thay đổi sau khi hoàn thành

Sau khi hoàn thành toàn bộ (code + test pass), phải trình bày **bảng tổng kết thay đổi**:

| File | Hành động | Module | Mô tả |
|------|-----------|--------|-------|
| `path/to/file.py` | Add / Update / Delete | Tên module | Mô tả ngắn gọn |

---

## 6. Auto-commit & push khi thay đổi logic

Sau khi hoàn thành thay đổi, **TỰ ĐỘNG commit và push** nếu thay đổi thuộc một trong các loại sau:

- Thay đổi **nội dung logic** trong tài liệu kiến trúc (`docs/architecture/`)
- Thêm / sửa / xoá **function, class, module** trong source code
- Thay đổi **data model, interface, contract, hoặc flow**

**KHÔNG cần auto-commit** khi:
- Fix lỗi nhỏ (typo, formatting, comment) không ảnh hưởng đến kiến trúc hoặc logic
- Thay đổi chỉ trong phạm vi debug/thử nghiệm chưa hoàn chỉnh

---

## Reference

- Tổng quan dự án: `PROJECT.md`
- Tài liệu kiến trúc: `docs/architecture/`
- Scope & Requirements: `docs/scope/`
- Tech Stack: Python 3.12+, FastAPI, PostgreSQL 16, Redis 7, OpenTelemetry, Docker/K8s, MCP
