from __future__ import annotations
from ..config import Config, ConfigError
from .base import TranslationError, Translator
from .gemini import GeminiTranslator
from .deepl import DeepLTranslator
from .openai_compat import OpenAICompatibleTranslator
from .router import TranslatorRouter

__all__ = ["TranslationError", "Translator", "TranslatorRouter", "build_router"]

def build_router(cfg: Config) -> TranslatorRouter:
    providers = []
    for name in cfg.providers:
        if name == "gemini":
            providers.append(GeminiTranslator(cfg.gemini_api_key, cfg.gemini_model))
        elif name == "deepl":
            providers.append(DeepLTranslator(cfg.deepl_api_key, cfg.deepl_api_base))
        elif name == "openai_compat":
            providers.append(OpenAICompatibleTranslator(cfg.openai_api_key, cfg.openai_base_url, cfg.openai_model))
        else:
            raise ConfigError(f"Unknown provider {name!r}")
    return TranslatorRouter(providers, [p.name for p in providers])
