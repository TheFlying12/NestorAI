"""General assistant skill — direct LLM pass-through.

No domain-specific logic; just routes context messages to the user's LLM.
"""
from typing import Any, Dict, List


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
