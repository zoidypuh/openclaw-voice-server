from .base import BaseConversationAgent, ConversationAgent
from .hermes import HermesConversationAgent, validate_hermes_connection
from .openai_chat import OpenAIChatAgent
from ..catalog import DEFAULT_HERMES_PROFILE, normalize_agent_backend
from ..gateway import resolve_voice_session_key


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
        agent_settings = settings.get("agent") or {}
        return hermes_agent_cls(
            project_root=str(agent_settings.get("hermes_root") or "").strip() or None,
            profile=str(agent_settings.get("hermes_profile") or DEFAULT_HERMES_PROFILE).strip(),
            api_url=str(agent_settings.get("hermes_api_url") or "").strip() or None,
            api_key=str((settings.get("secrets") or {}).get("hermes_api_key") or "").strip(),
            api_model=str(agent_settings.get("hermes_api_model") or "").strip() or None,
            use_context_files=bool(agent_settings.get("use_context_files", True)),
            use_memory=bool(agent_settings.get("use_memory", True)),
            enabled_toolsets=agent_settings.get("toolsets", []),
            reply_sanity_check=bool(agent_settings.get("reply_sanity_check", True)),
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
