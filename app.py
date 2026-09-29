import asyncio
import os
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
MAX_CHARS = {"kokoro": 8000, "qwen3": 2000}

# ---------------------------------------------------------------- engines

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

KOKORO_NAMES = [
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

# speaker, native language, description, gender
QWEN_VOICES = [
    ("Vivian", "Chinese", "Bright young female", "Female"),
    ("Serena", "Chinese", "Warm, gentle young female", "Female"),
    ("Uncle_Fu", "Chinese", "Seasoned male, mellow timbre", "Male"),
    ("Dylan", "Chinese", "Youthful Beijing male", "Male"),
    ("Eric", "Chinese", "Lively Chengdu male", "Male"),
    ("Ryan", "English", "Dynamic male with rhythm", "Male"),
    ("Aiden", "English", "Sunny American male", "Male"),
    ("Ono_Anna", "Japanese", "Playful Japanese female", "Female"),
    ("Sohee", "Korean", "Warm Korean female", "Female"),
]

QWEN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
# Qwen3-TTS is disabled by default: without an NVIDIA GPU it typically runs at
# ~250x real-time on CPU, which is unusable. Set QWEN_ENABLED=1 to expose it.
QWEN_ENABLED = os.environ.get("QWEN_ENABLED") == "1"

SAMPLES = {
    "kokoro": {
        "en-us": "Hi there! This is how I sound. Not bad for a tiny model, right?",
        "en-gb": "Good day! This is a sample of my voice. Lovely weather, isn't it?",
        "es": "Hola! Asi suena mi voz. Que te parece?",
        "fr-fr": "Bonjour ! Voici un petit echantillon de ma voix.",
        "hi": "Namaste! Yeh meri awaaz ka namoona hai.",
        "it": "Ciao! Questo e un esempio della mia voce.",
        "ja": "Konnichiwa! Kore ga watashi no koe no sanpuru desu.",
        "pt-br": "Ola! Esta e uma amostra da minha voz.",
        "zh": "Ni hao! Zhe shi wo de shengyin yangben.",
    },
    "qwen3": {
        "Chinese": "你好！我是你的语音助手，很高兴认识你。",
        "English": "Hi there! This is how I sound. Pretty good for a tiny model, right?",
        "Japanese": "こんにちは！これが私の声のサンプルです。",
        "Korean": "안녕하세요! 이것은 제 목소리 샘플입니다.",
    },
}

ENGINES = {
    "kokoro": {"label": "Kokoro 82M", "styles": False, "speed": True},
    "qwen3": {"label": "Qwen3-TTS 0.6B", "styles": True, "speed": False},
}

# ---------------------------------------------------------------- loaders

_kokoro = None
_kokoro_lock = threading.Lock()
_qwen = None
_qwen_lock = threading.Lock()


def get_kokoro() -> Kokoro:
    global _kokoro
    with _kokoro_lock:
        if _kokoro is None:
            _kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
        return _kokoro


def get_qwen():
    global _qwen
    with _qwen_lock:
        if _qwen is None:
            import torch
            from qwen_tts import Qwen3TTSModel

            _qwen = Qwen3TTSModel.from_pretrained(
                QWEN_MODEL_ID,
                device_map="cpu",
                dtype=torch.bfloat16,
            )
        return _qwen


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=get_kokoro, daemon=True).start()
    yield


app = FastAPI(title="Kokoro Studio", lifespan=lifespan)

# ---------------------------------------------------------------- helpers


def kokoro_meta(name: str) -> dict:
    prefix = name[:3]
    code, lang = LANG_META[prefix]
    gender = "Female" if prefix[1] == "f" else "Male"
    display = name[3:].replace("_", " ").capitalize()
    return {
        "name": name,
        "display": display,
        "lang": lang,
        "gender": gender,
        "desc": "",
    }


def qwen_meta(speaker: str, lang: str, desc: str, gender: str) -> dict:
    return {
        "name": speaker,
        "display": speaker.replace("_", " "),
        "lang": lang,
        "gender": gender,
        "desc": desc,
    }


def check_engine(engine: str) -> str:
    if engine not in ENGINES:
        raise HTTPException(400, f"Unknown engine '{engine}'")
    if engine == "qwen3" and not QWEN_ENABLED:
        raise HTTPException(
            400,
            "Qwen3-TTS is disabled on this machine (needs an NVIDIA GPU to be "
            "practical). Start the server with QWEN_ENABLED=1 to force it.",
        )
    return engine


def check_voice(engine: str, voice: str) -> None:
    if engine == "kokoro":
        if not re.fullmatch(r"[a-z]{2}_[a-z]+", voice) or voice not in KOKORO_NAMES:
            raise HTTPException(400, f"Unknown Kokoro voice '{voice}'")
    else:
        if voice not in {v[0] for v in QWEN_VOICES}:
            raise HTTPException(400, f"Unknown Qwen3 speaker '{voice}'")


# ---------------------------------------------------------------- api


class VoiceReq(BaseModel):
    engine: str = "kokoro"
    voice: str


class GenerateReq(BaseModel):
    engine: str = "kokoro"
    text: str
    voice: str
    speed: float = 1.0
    instruct: str = ""


@app.get("/api/voices")
def list_voices():
    engines = [
        {
            "id": "kokoro",
            "label": ENGINES["kokoro"]["label"],
            "styles": False,
            "speed": True,
            "enabled": True,
            "voices": [kokoro_meta(v) for v in KOKORO_NAMES],
        }
    ]
    if QWEN_ENABLED:
        engines.append(
            {
                "id": "qwen3",
                "label": ENGINES["qwen3"]["label"],
                "styles": True,
                "speed": False,
                "enabled": True,
                "voices": [qwen_meta(*v) for v in QWEN_VOICES],
            }
        )
    else:
        engines.append(
            {
                "id": "qwen3",
                "label": ENGINES["qwen3"]["label"],
                "styles": True,
                "speed": False,
                "enabled": False,
                "voices": [qwen_meta(*v) for v in QWEN_VOICES],
            }
        )
    return {"engines": engines}


def _kokoro_synth(text: str, voice: str, speed: float, lang_code: str):
    samples, sr = get_kokoro().create(text, voice=voice, speed=speed, lang=lang_code)
    return samples, sr


def _qwen_synth(text: str, voice: str, lang: str, instruct: str):
    kwargs = {"text": text, "language": lang, "speaker": voice}
    if instruct:
        kwargs["instruct"] = instruct
    wavs, sr = get_qwen().generate_custom_voice(**kwargs)
    return wavs[0], sr


@app.post("/api/preview")
async def preview(req: VoiceReq):
    engine = check_engine(req.engine)
    check_voice(engine, req.voice)
    cached = CACHE_DIR / f"{engine}_{req.voice}.wav"
    if cached.exists():
        return {"url": f"/cache/{cached.name}", "cached": True}

    if engine == "kokoro":
        lang_code = LANG_META[req.voice[:3]][0]
        text = SAMPLES["kokoro"].get(lang_code, SAMPLES["kokoro"]["en-us"])
        samples, sr = await asyncio.to_thread(
            _kokoro_synth, text, req.voice, 1.0, lang_code
        )
    else:
        meta = next(v for v in QWEN_VOICES if v[0] == req.voice)
        lang = meta[1]
        text = SAMPLES["qwen3"][lang]
        samples, sr = await asyncio.to_thread(_qwen_synth, text, req.voice, lang, "")

    sf.write(str(cached), samples, sr)
    return {"url": f"/cache/{cached.name}", "cached": False}


@app.post("/api/generate")
async def generate(req: GenerateReq):
    engine = check_engine(req.engine)
    check_voice(engine, req.voice)
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Script is empty")
    if len(text) > MAX_CHARS[engine]:
        raise HTTPException(
            400, f"Script too long for {engine} ({MAX_CHARS[engine]} characters max)"
        )

    if engine == "kokoro":
        lang_code = LANG_META[req.voice[:3]][0]
        speed = min(2.0, max(0.5, req.speed))
        samples, sr = await asyncio.to_thread(
            _kokoro_synth, text, req.voice, speed, lang_code
        )
    else:
        meta = next(v for v in QWEN_VOICES if v[0] == req.voice)
        instruct = req.instruct.strip()[:200]
        samples, sr = await asyncio.to_thread(
            _qwen_synth, text, req.voice, meta[1], instruct
        )

    fname = f"gen_{int(time.time())}_{uuid.uuid4().hex[:6]}_{engine}_{req.voice}.wav"
    sf.write(str(OUT_DIR / fname), samples, sr)
    return {
        "url": f"/audio_out/{fname}",
        "duration": round(len(samples) / sr, 1),
        "voice": req.voice,
        "engine": engine,
    }


app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/audio_out", StaticFiles(directory=OUT_DIR), name="audio_out")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
