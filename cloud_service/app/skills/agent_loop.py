"""Shared agentic loop for tool-calling skills.

Intermediate tool-call steps use non-streaming (to parse tool_calls cleanly).
Only the final LLM response streams tokens.

Compatible with Python 3.10+ (no asyncio.timeout).
"""
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger("cloud.skills.agent_loop")

AGENT_MAX_ITERATIONS = int(__import__("os").getenv("AGENT_MAX_ITERATIONS", "5"))
AGENT_HARD_TIMEOUT_S = float(__import__("os").getenv("AGENT_HARD_TIMEOUT_SECONDS", "120"))


async def run(
    messages: List[Dict],
    tools: List[Dict],
    tool_executor: Callable,
    llm_complete_with_tools: Callable,
    llm_stream: Callable,
    db: Any,
    user_id: str,
    max_iterations: int = AGENT_MAX_ITERATIONS,
    hard_timeout_s: float = AGENT_HARD_TIMEOUT_S,
) -> AsyncIterator[str]:
    """Run the agentic loop and stream final tokens.

    Args:
        messages: Initial message list (system + user).
        tools: OpenAI function-calling tool definitions.
        tool_executor: async (name, args, db, user_id) -> str
        llm_complete_with_tools: async (messages, tools) -> choice dict
        llm_stream: async generator (messages) -> yields str tokens
        db: AsyncSession
        user_id: scoped user id
        max_iterations: max tool-call rounds before forcing summary
        hard_timeout_s: wall-clock timeout for the entire loop
    """

    async def _inner():
        working_msgs = list(messages)
        for _ in range(max_iterations):
            choice = await llm_complete_with_tools(working_msgs, tools)
            finish_reason = choice.get("finish_reason", "stop")

            if finish_reason != "tool_calls":
                # LLM decided to reply directly — stream it
                break

            tool_calls = choice.get("message", {}).get("tool_calls") or []
            if not tool_calls:
                break

            # Append assistant message with tool_calls BEFORE tool results
            assistant_msg = {
                "role": "assistant",
                "content": choice.get("message", {}).get("content"),
                "tool_calls": tool_calls,
            }
            working_msgs.append(assistant_msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"].get("arguments", "{}")
                    args = json.loads(raw_args) if raw_args else {}
                    result = await tool_executor(fn_name, args, db, user_id)
                    logger.debug("tool=%s user=%s result_len=%d", fn_name, user_id, len(str(result)))
                except Exception as exc:
                    result = f"Error calling {fn_name}: {exc}"
                    logger.warning("tool=%s user=%s error=%s", fn_name, user_id, exc)
                working_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })
        else:
            # Max iterations exhausted — inject summary request
            logger.warning("agent_loop max_iterations=%d hit for user=%s", max_iterations, user_id)
            working_msgs.append({
                "role": "user",
                "content": "Summarize what you found so far. Do not call more tools.",
            })

        async for token in llm_stream(working_msgs):
            yield token

    # Wrap _inner with a hard timeout using asyncio queue + producer task
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    _ERROR = object()

    async def _producer():
        try:
            async for token in _inner():
                await queue.put(("token", token))
        except Exception as exc:
            await queue.put((_ERROR, exc))
        finally:
            await queue.put((_SENTINEL, None))

    producer_task = asyncio.create_task(_producer())
    deadline = asyncio.get_event_loop().time() + hard_timeout_s

    try:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.error("agent_loop hard timeout hit for user=%s", user_id)
                producer_task.cancel()
                yield "\n\n[Response timed out. Please try again.]"
                return
            try:
                kind, value = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                logger.error("agent_loop hard timeout hit for user=%s", user_id)
                producer_task.cancel()
                yield "\n\n[Response timed out. Please try again.]"
                return
            if kind is _SENTINEL:
                return
            if kind is _ERROR:
                raise value
            yield value
    finally:
        if not producer_task.done():
            producer_task.cancel()
