"""Translation Service — DeepL + GPT fallback"""
import logging
from typing import Tuple
import httpx
from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)
DEEPL_MAP = {"ja":"JA","zh":"ZH","ko":"KO","es":"ES","pt":"PT-BR","fr":"FR","de":"DE"}
GPT_ONLY = {"th"}

class TranslationService:
    def __init__(self):
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def translate(self, text: str, source: str = "auto") -> Tuple[str, str]:
        if settings.DEEPL_API_KEY and source not in GPT_ONLY:
            try: return await self._deepl(text, source)
            except: logger.warning("DeepL failed, using GPT")
        return await self._gpt(text, source)

    async def detect(self, text: str) -> str:
        try:
            r = await self.openai.chat.completions.create(
                model="gpt-4o-mini", temperature=0, max_tokens=5,
                messages=[{"role":"system","content":"Return ONLY ISO 639-1 code."},
                          {"role":"user","content":text[:500]}])
            return r.choices[0].message.content.strip().lower()[:2]
        except: return "auto"

    async def _deepl(self, text, src) -> Tuple[str, str]:
        p = {"text": [text], "target_lang": "EN-US"}
        if src != "auto" and src in DEEPL_MAP: p["source_lang"] = DEEPL_MAP[src]
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{settings.DEEPL_API_URL}/translate", json=p,
                headers={"Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}", "Content-Type": "application/json"})
            r.raise_for_status()
            d = r.json()["translations"][0]
            return d["text"], d.get("detected_source_language","").lower()

    async def _gpt(self, text, src) -> Tuple[str, str]:
        if src == "auto": src = await self.detect(text)
        names = {"ja":"Japanese","zh":"Chinese","ko":"Korean","th":"Thai","es":"Spanish","pt":"Portuguese","fr":"French","de":"German"}
        r = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL, temperature=0.15, max_tokens=settings.OPENAI_MAX_TOKENS,
            messages=[{"role":"system","content":f"Translate {names.get(src,'the text')} to English. Preserve all numbers, formulas, citations. ONLY translation."},
                      {"role":"user","content":text}])
        return r.choices[0].message.content.strip(), src

_t = None
def get_translator():
    global _t
    if _t is None: _t = TranslationService()
    return _t
