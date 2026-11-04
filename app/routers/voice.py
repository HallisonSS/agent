"""Rota de voz (opcional). Se você tiver STT/TTS próprios, coloque em
app/ia/voice/stt.py e app/ia/voice/tts.py (a pasta é `ia`, NÃO `ai`) e
importe aqui DENTRO da função, para nunca derrubar a API no boot."""
from fastapi import APIRouter, Depends

from app.security.auth import require_key

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(require_key)])


@router.get("/status")
async def voice_status():
    return {"enabled": False, "detail": "STT/TTS não configurados neste build"}
