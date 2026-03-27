"""Result Processor — normalize and post-process MCP tool results.

Converts raw MCP JSON-RPC results into the platform's ToolResult model.
Handles truncation for large results and error mapping.

See docs/architecture/06-mcp-tools.md Section 2.2.6.
"""

from __future__ import annotations

from typing import Any

from src.core.models import ToolResult
from src.providers.mcp.models import ToolInfo

# Default max chars for tool result content (~4k tokens)
DEFAULT_MAX_RESULT_CHARS = 16000


class ResultProcessor:
    """Normalizes raw MCP results into platform ToolResult."""

    def __init__(self, max_result_chars: int = DEFAULT_MAX_RESULT_CHARS) -> None:
        self._max_chars = max_result_chars

    def process(
        self,
        raw_result: dict[str, Any],
        tool_call_id: str,
        tool_info: ToolInfo,
    ) -> ToolResult:
        """Process a raw MCP result into a ToolResult.

        MCP result format: {"content": [{"type": "text", "text": "..."}], "isError": bool}
        """
        # 1. Extract content and error flag
        content, is_error = self._extract_content(raw_result)

        # 2. Truncate if too large
        truncated = False
        if len(content) > self._max_chars:
            content = self._truncate(content)
            truncated = True

        # 3. Compute cost
        cost_usd = tool_info.estimated_cost

        # 4. Build metadata
        metadata: dict[str, Any] = {
            "server_id": tool_info.server_id,
        }
        if truncated:
            metadata["truncated"] = True
            metadata["original_length"] = len(content)

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=tool_info.name,
            content=content,
            is_error=is_error,
            metadata=metadata,
            cost_usd=cost_usd,
        )

    def _extract_content(self, raw_result: dict[str, Any]) -> tuple[str, bool]:
        """Extract text content and error flag from MCP result."""
        is_error = raw_result.get("isError", False)
        content_blocks = raw_result.get("content", [])

        if not content_blocks:
            return ("" if not is_error else "Tool returned empty result"), is_error

        # Concatenate all text blocks
        parts: list[str] = []
        for block in content_blocks:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append(f"[Image: {block.get('mimeType', 'unknown')}]")
                elif block.get("type") == "resource":
                    uri = block.get("resource", {}).get("uri", "unknown")
                    text = block.get("resource", {}).get("text", "")
                    parts.append(f"[Resource: {uri}]\n{text}" if text else f"[Resource: {uri}]")
                else:
                    parts.append(str(block))
            elif isinstance(block, str):
                parts.append(block)

        return "\n".join(parts), is_error

    def _truncate(self, content: str) -> str:
        """Truncate content keeping 60% head + 40% tail with marker."""
        head_budget = int(self._max_chars * 0.6)
        tail_budget = self._max_chars - head_budget - 50  # 50 chars for marker
        if tail_budget < 0:
            tail_budget = 0

        marker = "\n\n[...truncated, full result stored...]\n\n"
        head = content[:head_budget]
        tail = content[-tail_budget:] if tail_budget > 0 else ""
        return head + marker + tail
