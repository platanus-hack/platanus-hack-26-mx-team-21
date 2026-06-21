"""Anthropic adapter for the draft parser. Uses forced tool use so the model returns a
structured object, which is then validated as a PlanDraft. Provider errors (rate limit,
timeout, unavailable) map to stable 502/503 ApiErrors without leaking raw provider bodies,
and invalid structured output is rejected — never applied to the frontend form."""
from __future__ import annotations
from typing import Any

from citycrawl_api.config import Settings
from citycrawl_api.errors import ApiError, upstream_bad_gateway, upstream_unavailable
from citycrawl_api.logging import get_logger
from citycrawl_api.modules.llm.models import (
    DraftChatRequest,
    DraftChatResponse,
    DraftParseRequest,
    PlanDraft,
)

logger = get_logger("citycrawl_api.llm")

_DRAFT_PROPERTIES: dict[str, Any] = {
    "issueType": {
        "type": ["string", "null"],
        "description": "Slug of the recognized issue type, or null.",
    },
    "budget": {
        "type": ["number", "null"],
        "description": "Budget in MXN as a number, or null if not stated.",
    },
    "regionFilter": {
        "type": "array",
        "items": {"type": "string"},
        "description": "INEGI cve_mun codes for recognized regions; [] for all.",
    },
    "squadCount": {
        "type": ["integer", "null"],
        "description": "Number of squads/crews requested, or null.",
    },
    "unresolvedTerms": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Phrases referencing a type/region that could not be mapped.",
    },
    "warnings": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Short notes about ambiguous or ignored parts of the request.",
    },
}

_DRAFT_TOOL: dict[str, Any] = {
    "name": "emit_plan_draft",
    "description": "Return the structured action-plan draft parsed from the user's request.",
    "input_schema": {
        "type": "object",
        "properties": dict(_DRAFT_PROPERTIES),
        "required": ["regionFilter", "unresolvedTerms", "warnings"],
        "additionalProperties": False,
    },
}

# Chat tool: one forced call returns BOTH the Spanish conversational reply and the full
# (merged) draft state, so a turn yields a chat message and updated form fields together.
_CHAT_TOOL: dict[str, Any] = {
    "name": "emit_chat_turn",
    "description": "Return your Spanish reply to the user plus the full, updated action-plan draft.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {
                "type": "string",
                "description": (
                    "Your conversational reply to the user, in Spanish. Confirm what you "
                    "understood or ask the next concrete question."
                ),
            },
            **_DRAFT_PROPERTIES,
        },
        "required": ["reply", "regionFilter", "unresolvedTerms", "warnings"],
        "additionalProperties": False,
    },
}


def _system_prompt(request: DraftParseRequest) -> str:
    types = "\n".join(f"- {c.slug}: {c.label}" for c in request.issue_types) or "- (none)"
    regions = "\n".join(f"- {c.cve}: {c.name}" for c in request.regions) or "- (none)"
    return (
        "You parse a Spanish or English city-maintenance planning request into a structured "
        "draft. Only use issue-type slugs and region codes from the lists below; never invent "
        "codes. If the user references a type or region not in the lists, leave the field null "
        "or omit it and add the phrase to unresolvedTerms. Budget is a plain number in MXN "
        "(e.g. '2 millones' -> 2000000). Do not infer cost overrides.\n\n"
        f"Issue types:\n{types}\n\nRegions (cve_mun: name):\n{regions}"
    )


def _draft_state(draft: PlanDraft | None) -> str:
    if draft is None:
        return "(vacío)"
    d = draft.model_dump(by_alias=True)
    return "\n".join(f"- {k}: {v!r}" for k, v in d.items())


def _chat_system_prompt(request: DraftChatRequest) -> str:
    types = "\n".join(f"- {c.slug}: {c.label}" for c in request.issue_types) or "- (ninguno)"
    regions = "\n".join(f"- {c.cve}: {c.name}" for c in request.regions) or "- (ninguno)"
    return (
        "Eres el asistente del Mapa de Prioridades de mantenimiento urbano de la CDMX. "
        "Conversas con el usuario, en español, para armar un «plan de acción» con cuatro "
        "parámetros: tipo de problema, presupuesto (MXN), regiones (alcaldías) y número de "
        "cuadrillas.\n\n"
        "Reglas:\n"
        "- Responde SIEMPRE en español, breve y claro (1-3 frases).\n"
        "- Usa únicamente los slugs de tipo y los códigos de región de las listas; nunca "
        "inventes códigos.\n"
        "- Si el usuario menciona un tipo o región que no está en las listas, déjalo sin "
        "asignar y añádelo a unresolvedTerms.\n"
        "- El presupuesto es un número en MXN (p. ej. «2 millones» -> 2000000).\n"
        "- Mantén el estado entre turnos: parte del «Borrador actual» y aplica solo los "
        "cambios que pida el usuario; devuelve SIEMPRE el borrador completo y actualizado.\n"
        "- Si falta información para un plan útil, pregunta de forma concreta "
        "(p. ej. «¿Qué presupuesto y cuántas cuadrillas?»).\n"
        "- En «reply» escribe tu respuesta conversacional para el usuario.\n"
        "- Llama SIEMPRE a la herramienta emit_chat_turn.\n\n"
        f"Borrador actual:\n{_draft_state(request.draft)}\n\n"
        f"Tipos de problema:\n{types}\n\nRegiones (cve_mun: nombre):\n{regions}"
    )


class AnthropicDraftParser:
    name = "anthropic"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client  # injectable for tests
        self._model = settings.anthropic_model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._settings.anthropic_api_key:
            raise upstream_unavailable("llm_unconfigured", "LLM provider is not configured")
        import anthropic

        self._client = anthropic.AsyncAnthropic(
            api_key=self._settings.anthropic_api_key,
            timeout=self._settings.anthropic_timeout_s,
        )
        return self._client

    async def parse(self, request: DraftParseRequest) -> PlanDraft:
        import anthropic

        client = self._get_client()
        try:
            message = await client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_system_prompt(request),
                tools=[_DRAFT_TOOL],
                tool_choice={"type": "tool", "name": "emit_plan_draft"},
                messages=[{"role": "user", "content": request.prompt}],
            )
        except anthropic.RateLimitError:
            raise upstream_unavailable("llm_rate_limited", "LLM provider is rate limited")
        except (anthropic.APITimeoutError, anthropic.APIConnectionError):
            raise upstream_unavailable("llm_unavailable", "LLM provider is unavailable")
        except anthropic.APIStatusError:
            raise upstream_bad_gateway("llm_error", "LLM provider returned an error")

        payload = _extract_tool_input(message, "emit_plan_draft")
        if payload is None:
            raise upstream_bad_gateway("llm_invalid_output", "LLM returned no structured draft")
        try:
            return PlanDraft.model_validate(payload)
        except Exception:
            # Invalid structured output is rejected and never applied to the frontend form.
            raise upstream_bad_gateway("llm_invalid_output", "LLM returned an invalid draft")

    async def chat(self, request: DraftChatRequest) -> DraftChatResponse:
        import anthropic

        client = self._get_client()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        try:
            message = await client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_chat_system_prompt(request),
                tools=[_CHAT_TOOL],
                tool_choice={"type": "tool", "name": "emit_chat_turn"},
                messages=messages,
            )
        except anthropic.RateLimitError:
            raise upstream_unavailable("llm_rate_limited", "LLM provider is rate limited")
        except (anthropic.APITimeoutError, anthropic.APIConnectionError):
            raise upstream_unavailable("llm_unavailable", "LLM provider is unavailable")
        except anthropic.APIStatusError:
            raise upstream_bad_gateway("llm_error", "LLM provider returned an error")

        payload = _extract_tool_input(message, "emit_chat_turn")
        if payload is None:
            raise upstream_bad_gateway("llm_invalid_output", "LLM returned no chat turn")
        reply = payload.pop("reply", None)
        if not isinstance(reply, str) or not reply.strip():
            raise upstream_bad_gateway("llm_invalid_output", "LLM returned no reply")
        try:
            draft = PlanDraft.model_validate(payload)
        except Exception:
            raise upstream_bad_gateway("llm_invalid_output", "LLM returned an invalid draft")
        return DraftChatResponse(reply=reply, draft=draft)


def _extract_tool_input(message: Any, name: str) -> dict[str, Any] | None:
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == name:
            payload = getattr(block, "input", None)
            return dict(payload) if isinstance(payload, dict) else payload
    return None
