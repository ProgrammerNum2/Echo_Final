from __future__ import annotations
import asyncio
from .base import RetryableTranslationError, TranslationError, Translator
from .http import HttpClient
from ..languages import code_for

class DeepLTranslator(Translator):
    name = "deepl"
    def __init__(self, api_key: str, base_url: str = "https://api-free.deepl.com", client: HttpClient | None = None):
        self._key, self._base = api_key, base_url.rstrip("/")
        self._http = client or HttpClient()

    async def _one(self, text: str, source: str, target: str) -> tuple[str, str]:
        target_code = _deepl_code(target)
        if not target_code:
            raise TranslationError(f"DeepL does not support target language {target!r}")
        params = {"text": text, "target_lang": target_code}
        source_code = _deepl_code(source)
        if source_code:
            params["source_lang"] = source_code
        # DeepL expects form data, while the common HttpClient is JSON-only.
        try:
            import httpx
            r = await self._http.client.post(f"{self._base}/v2/translate",
                                             headers={"Authorization": f"DeepL-Auth-Key {self._key}"},
                                             data=params)
            if r.status_code != 200:
                error = f"DeepL HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code in {408, 429, 500, 502, 503, 504}:
                    raise RetryableTranslationError(error)
                raise TranslationError(error)
            data = r.json()
            text_out = data["translations"][0]["text"]
            return target, text_out
        except TranslationError:
            raise
        except Exception as e:
            raise RetryableTranslationError(f"DeepL request failed: {e}") from e

    async def translate(self, text: str, source: str, targets: list[str]) -> dict[str, str]:
        results = await asyncio.gather(*(self._one(text, source, t) for t in targets), return_exceptions=True)
        out = {}
        errors = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                out[result[0]] = result[1]
        if errors or len(out) != len(targets):
            message = "; ".join(errors) or "DeepL returned incomplete results"
            if any(isinstance(result, RetryableTranslationError) for result in results):
                raise RetryableTranslationError(message)
            raise TranslationError(message)
        return out

    async def close(self):
        await self._http.close()

def _deepl_code(language: str) -> str | None:
    code = code_for(language)
    mapping = {
        "en": "EN", "ru": "RU", "uk": "UK", "es": "ES", "de": "DE", "fr": "FR",
        "it": "IT", "pt": "PT-PT", "nl": "NL", "pl": "PL", "ja": "JA", "zh": "ZH",
        "tr": "TR", "sv": "SV", "da": "DA", "no": "NB", "fi": "FI", "el": "EL",
        "cs": "CS", "ro": "RO", "bg": "BG", "hu": "HU", "sk": "SK", "sl": "SL",
    }
    return mapping.get(code or "")
