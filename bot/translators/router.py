from __future__ import annotations
import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from .base import RetryableTranslationError, TranslationError, Translator

log = logging.getLogger(__name__)

class TranslatorRouter:
    def __init__(self, providers: list[Translator], names: list[str], cache_size: int = 2000):
        if not providers:
            raise ValueError("at least one configured translation provider is required")
        self.providers = providers
        self.names = names
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[str,str,str], str] = OrderedDict()
        self._call_hook: Callable[[str], Awaitable[None]] | None = None

    def set_call_hook(self, hook: Callable[[str], Awaitable[None]] | None) -> None:
        self._call_hook = hook

    @property
    def active_name(self) -> str:
        return self.providers[0].name

    def set_primary(self, name: str) -> bool:
        for i, provider in enumerate(self.providers):
            if provider.name == name:
                if i:
                    self.providers.insert(0, self.providers.pop(i))
                return True
        return False

    def _key(self, text, source, target):
        return source.casefold(), target.casefold(), text

    async def translate(self, text: str, source: str, targets: list[str]) -> dict[str, str]:
        result, missing = {}, []
        for target in dict.fromkeys(targets):
            key = self._key(text, source, target)
            if key in self._cache:
                self._cache.move_to_end(key); result[target] = self._cache[key]
            else:
                missing.append(target)
        if missing:
            fresh = await self._call(missing, text, source)
            for target, value in fresh.items():
                result[target] = value
                self._cache[self._key(text, source, target)] = value
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    async def _call(self, targets, text, source):
        last = None
        for provider in self.providers:
            for attempt in range(2):
                try:
                    if self._call_hook:
                        await self._call_hook(provider.name)
                    out = await provider.translate(text, source, targets)
                    return out
                except RetryableTranslationError as e:
                    last = e
                    if attempt == 0:
                        log.warning("Provider %s hit a temporary API error; retrying once: %s", provider.name, e)
                        await asyncio.sleep(0.75)
                        continue
                    log.warning("Provider %s failed after retry: %s", provider.name, e)
                    break
                except TranslationError as e:
                    log.warning("Provider %s failed: %s", provider.name, e)
                    last = e
                    break
        raise TranslationError(f"all translation providers failed: {last}")

    async def close(self):
        # Providers may share an HTTP client; close once per provider is okay only when
        # each owns its client. build_router creates separate clients.
        for provider in self.providers:
            await provider.close()
