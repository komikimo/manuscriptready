"""
Translation Service — DeepL API with GPT fallback
"""
import logging
from typing import Tuple
import httpx
from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)
DEEPL_MAP = {"ja":"JA","zh":"ZH","ko":"KO","es":"ES","pt":"PT-BR","fr":"FR","de":"DE"}
DEEPL_UNSUPPORTED = {"th"}

class TranslationService:
    def __init__(self):
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def translate(self, text: str, source: str = "auto") -> Tuple[str, str]:
        use_deepl = settings.DEEPL_API_KEY and source not in DEEPL_UNSUPPORTED
        if use_deepl:
            try:
                return await self._deepl(text, source)
            except Exception as e:
                logger.warning(f"DeepL failed, GPT fallback: {e}")
        return await self._gpt(text, source)

    async def detect_lang(self, text: str) -> str:
        try:
            r = await self.openai.chat.completions.create(
                model="gpt-4o-mini", temperature=0, max_tokens=5,
                messages=[{"role":"system","content":"Return ONLY the ISO 639-1 code (e.g. ja, zh, ko, th). Nothing else."},
                          {"role":"user","content":text[:500]}])
            return r.choices[0].message.content.strip().lower()[:2]
        except:
            return "auto"

    async def _deepl(self, text, source) -> Tuple[str, str]:
        params = {"text": [text], "target_lang": "EN-US"}
        dl = DEEPL_MAP.get(source)
        if dl: params["source_lang"] = dl
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{settings.DEEPL_API_URL}/translate", json=params,
                            headers={"Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}",
                                     "Content-Type": "application/json"})
            r.raise_for_status()
            d = r.json()["translations"][0]
            return d["text"], d.get("detected_source_language","").lower()

    async def _gpt(self, text, source) -> Tuple[str, str]:
        if source == "auto": source = await self.detect_lang(text)
        names = {"ja":"Japanese","zh":"Chinese","ko":"Korean","th":"Thai","es":"Spanish","pt":"Portuguese","fr":"French","de":"German"}
        name = names.get(source, "the source language")
        r = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL, temperature=0.15, max_tokens=settings.OPENAI_MAX_TOKENS,
            messages=[{"role":"system","content":f"Translate from {name} to English. Faithful, accurate translation only. Preserve all numbers, formulas, citations, technical terms. Return ONLY translation."},
                      {"role":"user","content":text}])
        return r.choices[0].message.content.strip(), source

_inst = None
def get_translator():
    global _inst
    if _inst is None: _inst = TranslationService()
    return _inst
