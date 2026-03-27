"""Tests for ResultProcessor — MCP result normalization."""

import pytest

from src.providers.mcp.models import ToolInfo
from src.providers.mcp.result_processor import ResultProcessor


def _tool(**overrides) -> ToolInfo:
    defaults = dict(name="query", server_id="db-server", estimated_cost=0.001)
    defaults.update(overrides)
    return ToolInfo(**defaults)


@pytest.fixture
def proc() -> ResultProcessor:
    return ResultProcessor(max_result_chars=200)


# --- Basic extraction ---


class TestExtraction:
    def test_text_content(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "Hello world"}], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert result.content == "Hello world"
        assert result.is_error is False

    def test_multiple_text_blocks(self, proc: ResultProcessor):
        raw = {
            "content": [
                {"type": "text", "text": "Line 1"},
                {"type": "text", "text": "Line 2"},
            ],
            "isError": False,
        }
        result = proc.process(raw, "tc1", _tool())
        assert "Line 1" in result.content
        assert "Line 2" in result.content

    def test_error_flag_preserved(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "Error occurred"}], "isError": True}
        result = proc.process(raw, "tc1", _tool())
        assert result.is_error is True

    def test_empty_content(self, proc: ResultProcessor):
        raw = {"content": [], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert result.content == ""

    def test_empty_content_with_error(self, proc: ResultProcessor):
        raw = {"content": [], "isError": True}
        result = proc.process(raw, "tc1", _tool())
        assert "empty" in result.content.lower()
        assert result.is_error is True

    def test_image_block(self, proc: ResultProcessor):
        raw = {"content": [{"type": "image", "mimeType": "image/png"}], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert "Image" in result.content

    def test_resource_block(self, proc: ResultProcessor):
        raw = {
            "content": [{"type": "resource", "resource": {"uri": "file:///data.csv", "text": "a,b,c"}}],
            "isError": False,
        }
        result = proc.process(raw, "tc1", _tool())
        assert "data.csv" in result.content
        assert "a,b,c" in result.content

    def test_string_blocks(self, proc: ResultProcessor):
        raw = {"content": ["plain text"], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert result.content == "plain text"


# --- Truncation ---


class TestTruncation:
    def test_truncates_long_content(self, proc: ResultProcessor):
        long_text = "x" * 500
        raw = {"content": [{"type": "text", "text": long_text}], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert len(result.content) < 500
        assert "truncated" in result.content

    def test_truncation_metadata(self, proc: ResultProcessor):
        long_text = "x" * 500
        raw = {"content": [{"type": "text", "text": long_text}], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert result.metadata.get("truncated") is True

    def test_no_truncation_for_short(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "short"}], "isError": False}
        result = proc.process(raw, "tc1", _tool())
        assert "truncated" not in result.metadata


# --- Metadata ---


class TestMetadata:
    def test_server_id_in_metadata(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        result = proc.process(raw, "tc1", _tool(server_id="my-server"))
        assert result.metadata["server_id"] == "my-server"

    def test_tool_call_id(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        result = proc.process(raw, "tc42", _tool())
        assert result.tool_call_id == "tc42"

    def test_tool_name(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        result = proc.process(raw, "tc1", _tool(name="search"))
        assert result.tool_name == "search"

    def test_cost_from_tool_info(self, proc: ResultProcessor):
        raw = {"content": [{"type": "text", "text": "ok"}], "isError": False}
        result = proc.process(raw, "tc1", _tool(estimated_cost=0.05))
        assert result.cost_usd == 0.05
