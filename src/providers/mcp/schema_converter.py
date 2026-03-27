"""Schema Converter — MCP tool schemas ↔ LLM provider formats.

Converts MCP JSONSchema-based tool definitions to the format
required by each LLM provider (Anthropic, OpenAI, Google).

See docs/architecture/06-mcp-tools.md Section 2.1.3.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.core.models import ToolCall
from src.providers.mcp.models import ToolInfo


class SchemaConverter:
    """Bidirectional converter between MCP tool schemas and LLM formats."""

    # --- MCP → LLM provider ---

    def convert(self, tool: ToolInfo, provider: str) -> dict[str, Any]:
        """Convert a single tool to the target LLM provider format."""
        match provider:
            case "anthropic":
                return self.to_anthropic(tool)
            case "openai" | "groq" | "lmstudio":
                return self.to_openai(tool)
            case _:
                raise ValueError(f"Unsupported LLM provider for schema conversion: {provider}")

    def convert_batch(self, tools: list[ToolInfo], provider: str) -> list[dict[str, Any]]:
        """Convert multiple tools for a single LLM call."""
        return [self.convert(t, provider) for t in tools]

    def to_anthropic(self, tool: ToolInfo) -> dict[str, Any]:
        """Convert MCP tool to Anthropic tool_use format.

        Anthropic accepts JSONSchema directly for input_schema.
        """
        schema = dict(tool.input_schema)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})

        return {
            "name": self._sanitize_name(tool.name, tool.namespace),
            "description": self._build_description(tool),
            "input_schema": schema,
        }

    def to_openai(self, tool: ToolInfo) -> dict[str, Any]:
        """Convert MCP tool to OpenAI function calling format.

        OpenAI wraps schema in {"type": "function", "function": {...}}.
        """
        schema = dict(tool.input_schema)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})

        return {
            "type": "function",
            "function": {
                "name": self._sanitize_name(tool.name, tool.namespace),
                "description": self._build_description(tool),
                "parameters": schema,
            },
        }

    # --- LLM response → ToolCall ---

    def from_llm_tool_call(self, raw_call: dict[str, Any], provider: str) -> ToolCall:
        """Parse an LLM tool_call response back into a canonical ToolCall."""
        match provider:
            case "anthropic":
                return ToolCall(
                    id=raw_call.get("id", ""),
                    name=raw_call.get("name", ""),
                    arguments=raw_call.get("input", {}),
                )
            case "openai" | "groq" | "lmstudio":
                func = raw_call.get("function", {})
                args_raw = func.get("arguments", "{}")
                arguments = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                return ToolCall(
                    id=raw_call.get("id", ""),
                    name=func.get("name", ""),
                    arguments=arguments,
                )
            case _:
                raise ValueError(f"Unsupported LLM provider for parsing: {provider}")

    # --- Internal helpers ---

    def _sanitize_name(self, name: str, namespace: str) -> str:
        """Create a unique, valid tool name for LLMs.

        Format: {short_namespace}__{name}, max 64 chars.
        Allowed: [a-zA-Z0-9_-]
        """
        short_ns = namespace.split(":")[-1] if namespace else ""
        if short_ns:
            full = f"{short_ns}__{name}"
        else:
            full = name

        # Replace invalid characters with underscore
        sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", full)
        # Collapse runs of 3+ underscores, but preserve double underscore (separator)
        sanitized = re.sub(r"_{3,}", "__", sanitized).strip("_")
        # Truncate to 64 chars
        return sanitized[:64]

    def _build_description(self, tool: ToolInfo) -> str:
        """Build description with namespace prefix for LLM context."""
        if tool.namespace:
            return f"[{tool.namespace}] {tool.description}"
        return tool.description
