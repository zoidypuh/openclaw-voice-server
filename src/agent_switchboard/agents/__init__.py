from .base import BaseConversationAgent, ConversationAgent
from .hermes import HermesConversationAgent, validate_hermes_connection
from .openai_chat import OpenAIChatAgent
from ..catalog import normalize_agent_backend
from ..gateway import normalize_gateway_url, resolve_voice_session_key


def _hermes_gateway_settings(settings: dict) -> dict[str, str | None]:
    gateway_token = str((settings.get("secrets") or {}).get("gateway_token") or "").strip()
    gateway_model = str((settings.get("gateway") or {}).get("model") or "").strip()
    gateway_url = str((settings.get("gateway") or {}).get("url") or "").strip()
    return {
        "gateway_url": normalize_gateway_url(gateway_url) if gateway_url and gateway_token and gateway_model else None,
        "gateway_token": gateway_token or None,
        "gateway_model": gateway_model or None,
    }


def _gateway_agent_settings(settings: dict) -> dict[str, str]:
    return {
        "url": settings["gateway"]["url"],
        "token": settings["secrets"]["gateway_token"],
        "model": settings["gateway"]["model"],
        "session_key": resolve_voice_session_key(settings["gateway"]["session_key"]),
    }


def build_conversation_agent(
    settings: dict,
    *,
    hermes_agent_cls=HermesConversationAgent,
    direct_agent_cls=OpenAIChatAgent,
) -> BaseConversationAgent:
    backend = normalize_agent_backend((settings.get("agent") or {}).get("backend"))
    if backend == "hermes":
        return hermes_agent_cls(
            project_root=str((settings.get("agent") or {}).get("hermes_root") or "").strip() or None,
            **_hermes_gateway_settings(settings),
        )
    return direct_agent_cls(**_gateway_agent_settings(settings))

__all__ = [
    "BaseConversationAgent",
    "ConversationAgent",
    "OpenAIChatAgent",
    "build_conversation_agent",
    "HermesConversationAgent",
    "validate_hermes_connection",
]
