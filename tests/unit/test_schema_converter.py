"""Tests for SchemaConverter — MCP ↔ LLM provider formats."""

import pytest

from src.core.models import ToolCall
from src.providers.mcp.models import ToolInfo
from src.providers.mcp.schema_converter import SchemaConverter


def _tool(**overrides) -> ToolInfo:
    defaults = dict(
        name="create_issue",
        namespace="mcp:github",
        description="Create a new issue in a GitHub repository",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["title"],
        },
    )
    defaults.update(overrides)
    return ToolInfo(**defaults)


@pytest.fixture
def converter() -> SchemaConverter:
    return SchemaConverter()


# --- Anthropic format ---


class TestToAnthropic:
    def test_basic_structure(self, converter: SchemaConverter):
        result = converter.to_anthropic(_tool())
        assert "name" in result
        assert "description" in result
        assert "input_schema" in result

    def test_name_sanitized(self, converter: SchemaConverter):
        result = converter.to_anthropic(_tool())
        assert result["name"] == "github__create_issue"

    def test_description_has_namespace(self, converter: SchemaConverter):
        result = converter.to_anthropic(_tool())
        assert result["description"].startswith("[mcp:github]")

    def test_schema_preserved(self, converter: SchemaConverter):
        result = converter.to_anthropic(_tool())
        assert result["input_schema"]["required"] == ["title"]
        assert "title" in result["input_schema"]["properties"]

    def test_empty_schema_gets_defaults(self, converter: SchemaConverter):
        result = converter.to_anthropic(_tool(input_schema={}))
        assert result["input_schema"]["type"] == "object"
        assert result["input_schema"]["properties"] == {}


# --- OpenAI format ---


class TestToOpenAI:
    def test_wrapped_in_function(self, converter: SchemaConverter):
        result = converter.to_openai(_tool())
        assert result["type"] == "function"
        assert "function" in result
        assert "name" in result["function"]
        assert "parameters" in result["function"]

    def test_name_sanitized(self, converter: SchemaConverter):
        result = converter.to_openai(_tool())
        assert result["function"]["name"] == "github__create_issue"

    def test_schema_in_parameters(self, converter: SchemaConverter):
        result = converter.to_openai(_tool())
        assert "title" in result["function"]["parameters"]["properties"]


# --- Dispatch ---


class TestConvert:
    def test_anthropic_dispatch(self, converter: SchemaConverter):
        result = converter.convert(_tool(), "anthropic")
        assert "input_schema" in result

    def test_openai_dispatch(self, converter: SchemaConverter):
        result = converter.convert(_tool(), "openai")
        assert result["type"] == "function"

    def test_groq_uses_openai_format(self, converter: SchemaConverter):
        result = converter.convert(_tool(), "groq")
        assert result["type"] == "function"

    def test_unknown_provider_raises(self, converter: SchemaConverter):
        with pytest.raises(ValueError, match="Unsupported"):
            converter.convert(_tool(), "unknown_provider")


class TestConvertBatch:
    def test_batch(self, converter: SchemaConverter):
        tools = [_tool(name="a"), _tool(name="b")]
        results = converter.convert_batch(tools, "anthropic")
        assert len(results) == 2


# --- Parse LLM tool call back ---


class TestFromLLMToolCall:
    def test_anthropic_format(self, converter: SchemaConverter):
        raw = {"id": "tc1", "name": "github__create_issue", "input": {"title": "Bug"}}
        tc = converter.from_llm_tool_call(raw, "anthropic")
        assert isinstance(tc, ToolCall)
        assert tc.id == "tc1"
        assert tc.arguments == {"title": "Bug"}

    def test_openai_format(self, converter: SchemaConverter):
        raw = {
            "id": "tc2",
            "function": {
                "name": "github__create_issue",
                "arguments": '{"title": "Bug"}',
            },
        }
        tc = converter.from_llm_tool_call(raw, "openai")
        assert tc.name == "github__create_issue"
        assert tc.arguments == {"title": "Bug"}

    def test_openai_dict_arguments(self, converter: SchemaConverter):
        raw = {
            "id": "tc3",
            "function": {"name": "search", "arguments": {"q": "test"}},
        }
        tc = converter.from_llm_tool_call(raw, "openai")
        assert tc.arguments == {"q": "test"}

    def test_unknown_provider_raises(self, converter: SchemaConverter):
        with pytest.raises(ValueError):
            converter.from_llm_tool_call({}, "unknown")


# --- Name sanitization ---


class TestSanitizeName:
    def test_namespace_prefix(self, converter: SchemaConverter):
        assert converter._sanitize_name("query", "mcp:database") == "database__query"

    def test_no_namespace(self, converter: SchemaConverter):
        assert converter._sanitize_name("search", "") == "search"

    def test_special_chars_replaced(self, converter: SchemaConverter):
        assert converter._sanitize_name("my tool!", "ns:test") == "test__my_tool"

    def test_max_64_chars(self, converter: SchemaConverter):
        long_name = "a" * 100
        result = converter._sanitize_name(long_name, "")
        assert len(result) <= 64

    def test_no_description_namespace(self, converter: SchemaConverter):
        tool = _tool(namespace="")
        result = converter.to_anthropic(tool)
        assert not result["description"].startswith("[")
