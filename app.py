import asyncio
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kokoro_onnx import Kokoro

BASE = Path(__file__).resolve().parent
CACHE_DIR = BASE / "cache"
OUT_DIR = BASE / "audio_out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

MODEL_PATH = BASE / "kokoro-v1.0.onnx"
VOICES_PATH = BASE / "voices-v1.0.bin"
MAX_CHARS = 8000

LANG_META = {
    "af_": ("en-us", "English (US)"),
    "am_": ("en-us", "English (US)"),
    "bf_": ("en-gb", "English (UK)"),
    "bm_": ("en-gb", "English (UK)"),
    "ef_": ("es", "Spanish"),
    "em_": ("es", "Spanish"),
    "ff_": ("fr-fr", "French"),
    "hf_": ("hi", "Hindi"),
    "hm_": ("hi", "Hindi"),
    "if_": ("it", "Italian"),
    "im_": ("it", "Italian"),
    "jf_": ("ja", "Japanese"),
    "jm_": ("ja", "Japanese"),
    "pf_": ("pt-br", "Portuguese (BR)"),
    "pm_": ("pt-br", "Portuguese (BR)"),
    "zf_": ("zh", "Mandarin"),
    "zm_": ("zh", "Mandarin"),
}

VOICE_NAMES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    "ef_dora", "em_alex", "em_santa",
    "ff_siwis",
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola",
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
]

SAMPLES = {
    "en-us": "Hi there! This is how I sound. Not bad for a tiny model, right?",
    "en-gb": "Good day! This is a sample of my voice. Lovely weather, isn't it?",
    "es": "Hola! Asi suena mi voz. Que te parece?",
    "fr-fr": "Bonjour ! Voici un petit echantillon de ma voix.",
    "hi": "Namaste! Yeh meri awaaz ka namoona hai.",
    "it": "Ciao! Questo e un esempio della mia voce.",
    "ja": "Konnichiwa! Kore ga watashi no koe no sanpuru desu.",
    "pt-br": "Ola! Esta e uma amostra da minha voz.",
    "zh": "Ni hao! Zhe shi wo de shengyin yangben.",
}

_kokoro = None
_init_lock = threading.Lock()


def get_kokoro() -> Kokoro:
    global _kokoro
    with _init_lock:
        if _kokoro is None:
            _kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        return _kokoro


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=get_kokoro, daemon=True).start()
    yield


app = FastAPI(title="Kokoro Studio", lifespan=lifespan)


class VoiceReq(BaseModel):
    voice: str


class GenerateReq(BaseModel):
    text: str
    voice: str
    speed: float = 1.0


def voice_meta(name: str) -> dict:
    prefix = name[:3]
    code, lang = LANG_META[prefix]
    gender = "Female" if prefix[1] == "f" else "Male"
    display = name[3:].replace("_", " ").capitalize()
    return {
        "name": name,
        "display": display,
        "lang_code": code,
        "lang": lang,
        "gender": gender,
    }


def _check_voice(name: str) -> str:
    if not re.fullmatch(r"[a-z]{2}_[a-z]+", name) or name not in VOICE_NAMES:
        raise HTTPException(400, f"Unknown voice '{name}'")
    return LANG_META[name[:3]][0]


@app.get("/api/voices")
def list_voices():
    return [voice_meta(v) for v in VOICE_NAMES]


@app.post("/api/preview")
async def preview(req: VoiceReq):
    lang_code = _check_voice(req.voice)
    cached = CACHE_DIR / f"{req.voice}.wav"
    if cached.exists():
        return {"url": f"/cache/{req.voice}.wav", "cached": True}
    text = SAMPLES.get(lang_code, SAMPLES["en-us"])
    kokoro = await asyncio.to_thread(get_kokoro)
    samples, sr = await asyncio.to_thread(
        kokoro.create, text, voice=req.voice, speed=1.0, lang=lang_code
    )
    sf.write(str(cached), samples, sr)
    return {"url": f"/cache/{req.voice}.wav", "cached": False}


@app.post("/api/generate")
async def generate(req: GenerateReq):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Script is empty")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Script too long ({MAX_CHARS} characters max)")
    lang_code = _check_voice(req.voice)
    speed = min(2.0, max(0.5, req.speed))

    kokoro = await asyncio.to_thread(get_kokoro)
    samples, sr = await asyncio.to_thread(
        kokoro.create, text, voice=req.voice, speed=speed, lang=lang_code
    )
    fname = f"gen_{int(time.time())}_{uuid.uuid4().hex[:6]}_{req.voice}.wav"
    sf.write(str(OUT_DIR / fname), samples, sr)
    return {
        "url": f"/audio_out/{fname}",
        "duration": round(len(samples) / sr, 1),
        "voice": req.voice,
    }


app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/audio_out", StaticFiles(directory=OUT_DIR), name="audio_out")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
