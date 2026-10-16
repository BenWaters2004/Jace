"""Phase C1: real adapter contract tests without live provider calls or secrets.

Run: python -m unittest discover -s backend/tests -p 'test_cloud_provider_c1.py' -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import BaseModel

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from jace.model_gateway.providers.cloud_common import (
    CloudProviderError, anthropic_messages, anthropic_tools, iter_sse,
    openai_messages, normalized_tool_call, parsed_args, validate_structured,
)
from jace.model_gateway.providers.openai import OpenAIProvider
from jace.model_gateway.providers.anthropic import AnthropicProvider


class StructuredValue(BaseModel):
    answer: int


async def chunks(lines: list[str]):
    for line in lines:
        yield line


class TransportFixture:
    def __init__(self, payload: str, content_type: str = "text/event-stream") -> None:
        self.payload = payload
        self.requests: list[dict] = []
        self.content_type = content_type

    def client(self):
        async def respond(request: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, text=self.payload, headers={"Content-Type": self.content_type})
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="https://mock-provider.invalid")


class CloudContracts(unittest.TestCase):
    def test_sse_multiline(self):
        async def run():
            events = []
            async for item in iter_sse(chunks(["event: delta", "data: {\"value\":", "data:  3}", "", "data: [DONE]", ""])):
                events.append(item)
            return events
        self.assertEqual(asyncio.run(run()), [("delta", {"value": 3})])

    def test_provider_transcript_tool_correspondence(self):
        call = normalized_tool_call(name="get_info", arguments={"item": "x"}, call_id="call_42")
        messages = [
            {"role": "user", "content": "Find something"},
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "tool_name": "get_info", "tool_call_id": "call_42", "content": "ok"},
        ]
        oa = openai_messages(messages, "You are Jace")
        self.assertEqual(oa[-1]["tool_call_id"], "call_42")
        self.assertEqual(oa[2]["tool_calls"][0]["function"]["name"], "get_info")
        an = anthropic_messages(messages)
        self.assertEqual(an[1]["content"][0]["id"], "call_42")
        self.assertEqual(an[-1]["content"][0]["tool_use_id"], "call_42")

    def test_invalid_tool_results_fail_closed(self):
        with self.assertRaises(CloudProviderError):
            anthropic_messages([{"role": "tool", "tool_name": "x", "content": "orphan"}])
        with self.assertRaises(CloudProviderError):
            openai_messages([{"role": "user", "content": "hi", "images": ["base64..."]}], "")
        with self.assertRaises(CloudProviderError):
            parsed_args("{invalid-json")

    def test_distinct_tool_call_ids_are_preserved(self):
        calls = [
            normalized_tool_call(name="lookup", arguments={"x": 1}, call_id="call_a"),
            normalized_tool_call(name="lookup", arguments={"x": 1}, call_id="call_b"),
        ]
        transcript = [
            {"role": "user", "content": "two lookups"},
            {"role": "assistant", "content": "", "tool_calls": calls},
            {"role": "tool", "tool_call_id": "call_a", "content": "one"},
            {"role": "tool", "tool_call_id": "call_b", "content": "two"},
        ]
        oa = openai_messages(transcript, "")
        an = anthropic_messages(transcript)
        self.assertEqual([x["id"] for x in oa[1]["tool_calls"]], ["call_a", "call_b"])
        self.assertEqual([x["tool_use_id"] for x in an[2]["content"]], ["call_a", "call_b"])

    def test_schema_validation(self):
        self.assertEqual(validate_structured('{"answer": 42}', StructuredValue).answer, 42)
        with self.assertRaises(CloudProviderError):
            validate_structured('{"answer": "banana"}', StructuredValue)

    def test_anthropic_tool_schema(self):
        tools = [{"type": "function", "function": {"name": "hello", "description": "greet", "parameters": {"type": "object", "properties": {}}}}]
        self.assertEqual(anthropic_tools(tools)[0]["input_schema"]["type"], "object")


class ProviderStreaming(unittest.IsolatedAsyncioTestCase):
    async def test_openai_stream_text(self):
        payload = (
            'data: {"choices":[{"delta":{"content":"Hello "},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"Jace"},"finish_reason":"stop"}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n\n'
            'data: [DONE]\n\n'
        )
        fx = TransportFixture(payload)
        provider = OpenAIProvider()
        with patch.object(provider, "_client", fx.client):
            result = [part async for part in provider.stream_chat(model="fixture", messages=[{"role": "user", "content": "hi"}], system_prompt="You are Jace", reasoning_mode="fast", temperature=.4, tools=None)]
        self.assertEqual("".join(x.get("message", {}).get("content", "") for x in result), "Hello Jace")
        self.assertEqual(result[-1]["prompt_eval_count"], 12)
        self.assertEqual(result[-1]["eval_count"], 3)
        self.assertEqual(fx.requests[0]["messages"][0]["role"], "developer")

    async def test_openai_stream_tool_call(self):
        payload = (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"read_web_page","arguments":"{\\\"url\\\":\\\"https://example.com\\\"}"}}]},"finish_reason":"tool_calls"}]}\n\n'
            'data: [DONE]\n\n'
        )
        fx = TransportFixture(payload)
        provider = OpenAIProvider()
        with patch.object(provider, "_client", fx.client):
            result = [part async for part in provider.stream_chat(model="fixture", messages=[{"role": "user", "content": "look"}], system_prompt="", reasoning_mode="fast", temperature=.3, tools=[{"type":"function","function":{"name":"read_web_page","description":"read","parameters":{"type":"object","properties":{"url":{"type":"string"}}}}}])]
        self.assertEqual(result[0]["message"]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(result[0]["message"]["tool_calls"][0]["function"]["arguments"]["url"], "https://example.com")

    async def test_anthropic_stream_text(self):
        payload = (
            'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":15}}}\n\n'
            'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n'
            'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        )
        fx = TransportFixture(payload)
        provider = AnthropicProvider()
        with patch.object(provider, "_client", fx.client):
            result = [part async for part in provider.stream_chat(model="fixture", messages=[{"role":"user","content":"hi"}], system_prompt="You are Jace", reasoning_mode="fast", temperature=.4, tools=None)]
        self.assertEqual("".join(x.get("message", {}).get("content", "") for x in result), "Hello")
        self.assertEqual(result[-1]["eval_count"], 2)
        self.assertEqual(fx.requests[0]["system"], "You are Jace")

    async def test_anthropic_tool_call(self):
        payload = (
            'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":15}}}\n\n'
            'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_1","name":"read_web_page","input":{}}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\\"url\\\":\\\"https://example.com\\\"}"}}\n\n'
            'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":22}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        )
        fx = TransportFixture(payload)
        provider = AnthropicProvider()
        with patch.object(provider, "_client", fx.client):
            result = [part async for part in provider.stream_chat(model="fixture", messages=[{"role":"user","content":"hi"}], system_prompt="", reasoning_mode="fast", temperature=.4, tools=[{"type":"function","function":{"name":"read_web_page","description":"read","parameters":{"type":"object","properties":{}}}}])]
        self.assertEqual(result[0]["message"]["tool_calls"][0]["id"], "toolu_1")
        self.assertEqual(result[-1]["done_reason"], "tool_calls")


if __name__ == "__main__":
    unittest.main()
