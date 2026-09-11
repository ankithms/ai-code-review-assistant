import os
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv


DEFAULT_AI_PROVIDER = "gemini"
DEFAULT_AI_MODEL = "gemini-2.5-flash"

ModelFactory = Callable[[str], Any]


def _create_gemini_model(model_name: str):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        request_timeout=60,
        retries=2,
    )


_PROVIDER_FACTORIES: dict[str, ModelFactory] = {
    "gemini": _create_gemini_model,
}


def create_ai_model():
    """Create the configured provider model without exposing it to review logic."""
    load_dotenv()
    provider = os.getenv("AI_PROVIDER", DEFAULT_AI_PROVIDER).strip().lower()
    model_name = os.getenv("AI_MODEL", DEFAULT_AI_MODEL).strip()

    if not provider:
        raise RuntimeError("AI_PROVIDER must not be empty")
    if not model_name:
        raise RuntimeError("AI_MODEL must not be empty")

    factory = _PROVIDER_FACTORIES.get(provider)
    if factory is None:
        supported = ", ".join(sorted(_PROVIDER_FACTORIES))
        raise RuntimeError(
            f"Unsupported AI_PROVIDER '{provider}'. Supported providers: {supported}"
        )
    return factory(model_name)


def create_structured_model(schema: type[Any]):
    return create_ai_model().with_structured_output(schema, method="json_schema")
