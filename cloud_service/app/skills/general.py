"""General assistant skill — direct LLM pass-through.

No domain-specific logic; just routes context messages to the user's LLM.
When shared tools (send_sms, send_email) are injected by the router, the skill
switches to the agentic loop so the LLM can invoke those tools on request.
"""
from typing import Any, Callable, Dict, List, Optional

from cloud_service.app.skills.agent_loop import run as agent_run

_GENERAL_SYSTEM_PROMPT = (
    "You are Nestor, a practical assistant. Answer directly and concisely. "
    "Use the send_sms or send_email tools only when the user explicitly asks "
    "you to send a message to someone — never proactively."
)


async def handle(
    user_id: str,
    text: str,
    context_messages: List[Dict[str, str]],
    llm_complete,  # async callable: (messages) -> str
) -> str:
    """Return LLM reply for general assistant queries."""
    return await llm_complete(context_messages)


async def handle_stream(
    user_id: str,
    text: str,
    context_messages: List[Dict[str, str]],
    llm_stream,  # async generator: (messages) -> AsyncIterator[str]
):
    """Stream LLM tokens for general assistant queries."""
    async for token in llm_stream(context_messages):
        yield token


async def handle_stream_with_tools(
    user_id: str,
    text: str,
    context_messages: List[Dict[str, str]],
    llm_stream,
    llm_complete_with_tools,
    db: Any,
    tools: List[Dict],
    tool_executor: Callable,
):
    """Agentic streaming path — used when shared tools (send_sms/send_email) are available."""
    messages = [{"role": "system", "content": _GENERAL_SYSTEM_PROMPT}]
    messages.extend(context_messages)
    messages.append({"role": "user", "content": text})

    async for token in agent_run(
        messages=messages,
        tools=tools,
        tool_executor=tool_executor,
        llm_complete_with_tools=llm_complete_with_tools,
        llm_stream=llm_stream,
        db=db,
        user_id=user_id,
    ):
        yield token
