from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator, Protocol


class ConversationAgent(Protocol):
    async def stream_reply(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[str]:
        ...


class BaseConversationAgent(ABC):
    @abstractmethod
    async def stream_reply(self, text: str, abort_event: asyncio.Event) -> AsyncIterator[str]:
        raise NotImplementedError
