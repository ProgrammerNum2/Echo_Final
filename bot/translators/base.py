from __future__ import annotations
from abc import ABC, abstractmethod

class TranslationError(Exception):
    pass

class RetryableTranslationError(TranslationError):
    """A temporary provider/API failure that is safe to retry once."""


class Translator(ABC):
    name = "base"
    @abstractmethod
    async def translate(self, text: str, source: str, targets: list[str]) -> dict[str, str]:
        raise NotImplementedError
    async def close(self) -> None:
        return None
