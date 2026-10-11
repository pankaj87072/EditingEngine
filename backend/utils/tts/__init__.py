"""
utils/tts/__init__.py
---------------------
TTS Provider Factory.
Call get_tts_provider() anywhere to get the configured provider instance.
"""

from core.config import settings
from core.exceptions import UnsupportedTTSProviderError
from models.schema import TTSProvider
from utils.tts.base_tts import BaseTTSProvider
from utils.tts.google_tts import GoogleTTSProvider
from utils.tts.elevenlabs_tts import ElevenLabsTTSProvider


_PROVIDER_MAP = {
    TTSProvider.AUTO:       GoogleTTSProvider,   # placeholder; AUTO is resolved by resolve_chain()
    TTSProvider.GOOGLE:     GoogleTTSProvider,
    TTSProvider.ELEVENLABS: ElevenLabsTTSProvider,
}


def resolve_chain(requested: TTSProvider | None = None) -> list[BaseTTSProvider]:
    """
    Providers to try, in order. ElevenLabs is preferred whenever it is configured (for AUTO and
    ELEVENLABS); Google is always the last, reliable fallback. Choosing GOOGLE uses only Google.
    """
    chosen = requested or TTSProvider(settings.TTS_PROVIDER)
    el, gg = _PROVIDER_MAP[TTSProvider.ELEVENLABS], _PROVIDER_MAP[TTSProvider.GOOGLE]
    chain: list[BaseTTSProvider] = []
    if chosen in (TTSProvider.AUTO, TTSProvider.ELEVENLABS) and el.configured():
        chain.append(el())
    chain.append(gg())
    return chain


def get_tts_provider(
    provider: TTSProvider | None = None,
) -> BaseTTSProvider:
    """
    Return an instance of the requested TTS provider.

    If provider is None, the value from settings.TTS_PROVIDER is used.
    """
    chosen = provider or TTSProvider(settings.TTS_PROVIDER)
    if chosen == TTSProvider.AUTO:
        return resolve_chain(chosen)[0]
    cls = _PROVIDER_MAP.get(chosen)
    if cls is None:
        raise UnsupportedTTSProviderError(
            f"TTS provider '{chosen}' is not supported. "
            f"Available: {list(_PROVIDER_MAP.keys())}"
        )
    return cls()
