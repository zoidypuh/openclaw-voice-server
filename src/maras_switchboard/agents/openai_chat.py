from __future__ import annotations

import asyncio

from ..gateway import DirectGatewayClient
from .base import BaseConversationAgent


class OpenAIChatAgent(BaseConversationAgent):
    def __init__(self, *, url: str, token: str, model: str, session_key: str):
        self._client = DirectGatewayClient(
            url=url,
            token=token,
            model=model,
            session_key=session_key,
        )

    async def stream_reply(self, text: str, abort_event: asyncio.Event):
        async for chunk in self._client.stream_reply(text, abort_event):
            yield chunk
