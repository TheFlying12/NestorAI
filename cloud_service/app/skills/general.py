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
