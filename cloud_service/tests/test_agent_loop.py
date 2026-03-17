"""Unit tests for the agentic loop (agent_loop.py)."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeDB:
    pass


async def _collect(gen):
    tokens = []
    async for t in gen:
        tokens.append(t)
    return tokens


async def _agen(*items):
    for item in items:
        yield item


class TestAgentLoop(unittest.IsolatedAsyncioTestCase):

    async def test_single_tool_call_then_stop(self):
        """LLM calls one tool, then streams final reply."""
        from cloud_service.app.skills.agent_loop import run

        call_count = 0

        async def llm_complete_with_tools(messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"name": "my_tool", "arguments": json.dumps({"x": 1})},
                            }
                        ],
                    },
                }
            return {"finish_reason": "stop", "message": {"content": "Done!", "tool_calls": []}}

        async def tool_executor(name, args, db, user_id):
            return f"result_of_{name}"

        async def llm_stream(messages):
            yield "Hello"
            yield " world"

        tokens = await _collect(
            run(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_executor=tool_executor,
                llm_complete_with_tools=llm_complete_with_tools,
                llm_stream=llm_stream,
                db=FakeDB(),
                user_id="u1",
            )
        )
        self.assertEqual(tokens, ["Hello", " world"])
        self.assertEqual(call_count, 2)

    async def test_max_iterations_injects_summary_prompt(self):
        """When max_iterations is hit, a summary prompt is injected."""
        from cloud_service.app.skills.agent_loop import run

        async def llm_complete_with_tools(messages, tools):
            return {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_x",
                            "function": {"name": "t", "arguments": "{}"},
                        }
                    ],
                },
            }

        async def tool_executor(name, args, db, user_id):
            return "ok"

        captured_messages = []

        async def llm_stream(messages):
            captured_messages.extend(messages)
            yield "summary"

        await _collect(
            run(
                messages=[{"role": "user", "content": "go"}],
                tools=[],
                tool_executor=tool_executor,
                llm_complete_with_tools=llm_complete_with_tools,
                llm_stream=llm_stream,
                db=FakeDB(),
                user_id="u1",
                max_iterations=2,
            )
        )
        # Last message should be the summary injection
        last_msg = captured_messages[-1]
        self.assertEqual(last_msg["role"], "user")
        self.assertIn("Summarize", last_msg["content"])

    async def test_tool_executor_exception_continues_loop(self):
        """If tool_executor throws, the error is appended as tool_result and loop continues."""
        from cloud_service.app.skills.agent_loop import run

        call_count = 0

        async def llm_complete_with_tools(messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [{"id": "c1", "function": {"name": "fail_tool", "arguments": "{}"}}],
                    },
                }
            return {"finish_reason": "stop", "message": {"content": "ok", "tool_calls": []}}

        async def tool_executor(name, args, db, user_id):
            raise RuntimeError("DB is down")

        tool_messages = []

        async def llm_stream(messages):
            tool_messages.extend(m for m in messages if m.get("role") == "tool")
            yield "recovered"

        tokens = await _collect(
            run(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_executor=tool_executor,
                llm_complete_with_tools=llm_complete_with_tools,
                llm_stream=llm_stream,
                db=FakeDB(),
                user_id="u1",
            )
        )
        self.assertEqual(tokens, ["recovered"])
        self.assertTrue(any("Error" in m["content"] for m in tool_messages))

    async def test_hard_timeout_yields_timeout_token(self):
        """When hard timeout is hit, timeout message is yielded."""
        from cloud_service.app.skills.agent_loop import run

        async def llm_complete_with_tools(messages, tools):
            await asyncio.sleep(5)  # will be cancelled
            return {"finish_reason": "stop", "message": {}}

        async def tool_executor(name, args, db, user_id):
            return "ok"

        async def llm_stream(messages):
            yield "token"

        tokens = await _collect(
            run(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}],
                tool_executor=tool_executor,
                llm_complete_with_tools=llm_complete_with_tools,
                llm_stream=llm_stream,
                db=FakeDB(),
                user_id="u1",
                hard_timeout_s=0.05,  # 50ms
            )
        )
        self.assertTrue(any("timed out" in t.lower() for t in tokens))


if __name__ == "__main__":
    unittest.main()
