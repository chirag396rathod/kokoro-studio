import asyncio
import base64
import io
import json
import os
import re
import threading
import time
import shutil
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import soundfile as sf
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kokoro_onnx import Kokoro
from video_studio import make_video, make_vn_pack

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
CACHE_DIR = BASE / "cache"
OUT_DIR = BASE / "audio_out"
CACHE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

MODEL_PATH = BASE / "kokoro-v1.0.onnx"
VOICES_PATH = BASE / "voices-v1.0.bin"
MAX_CHARS = {"kokoro": 8000, "qwen3": 2000, "gemini": 6000}

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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.8-flash-tts"
GEMINI_TEXT_MODEL = "gemini-3.8-flash"
GEMINI_TEXT_FALLBACKS = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"]

# Fixed emotion palette: (name, voice instruction for the TTS model)
EMOTIONS = [
    ("Neutral", "Say in a neutral, natural tone"),
    ("Happy", "Say cheerfully and happily"),
    ("Excited", "Say with excitement and high energy"),
    ("Sad", "Say in a sad, downbeat tone"),
    ("Angry", "Say in an angry, irritated tone"),
    ("Whisper", "Whisper this softly"),
    ("Serious", "Say in a serious, firm tone"),
    ("Calm", "Say in a calm, soothing tone"),
    ("Fearful", "Say in a fearful, nervous tone"),
    ("Surprised", "Say with surprise and amazement"),
    ("Romantic", "Say in a warm, romantic tone"),
    ("Dramatic", "Say dramatically, with intensity"),
]
EMOTION_MAP = dict(EMOTIONS)
GEMINI_VOICES_CACHE = CACHE_DIR / "gemini_voices.json"
GEMINI_VOICES_MAX_AGE = 7 * 24 * 3600

# speaker, style descriptor, gender — 30 prebuilt Gemini TTS voices
GEMINI_VOICES = [
    ("Zephyr", "Bright", "Female"), ("Puck", "Upbeat", "Male"),
    ("Charon", "Informative", "Male"), ("Kore", "Firm", "Female"),
    ("Fenrir", "Excitable", "Male"), ("Leda", "Youthful", "Female"),
    ("Orus", "Firm", "Male"), ("Aoede", "Breezy", "Female"),
    ("Callirrhoe", "Easy-going", "Female"), ("Autonoe", "Bright", "Female"),
    ("Enceladus", "Breathy", "Male"), ("Iapetus", "Clear", "Male"),
    ("Umbriel", "Easy-going", "Male"), ("Algieba", "Smooth", "Male"),
    ("Despina", "Smooth", "Female"), ("Erinome", "Clear", "Female"),
    ("Algenib", "Gravelly", "Male"), ("Rasalgethi", "Informative", "Male"),
    ("Laomedeia", "Upbeat", "Female"), ("Achernar", "Soft", "Female"),
    ("Alnilam", "Firm", "Male"), ("Schedar", "Even", "Male"),
    ("Gacrux", "Mature", "Female"), ("Pulcherrima", "Forward", "Female"),
    ("Achird", "Friendly", "Male"), ("Zubenelgenubi", "Casual", "Male"),
    ("Vindemiatrix", "Gentle", "Female"), ("Sadachbia", "Lively", "Male"),
    ("Sadaltager", "Knowledgeable", "Male"), ("Sulafat", "Warm", "Female"),
]

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
    "gemini": {"label": "Gemini TTS", "styles": True, "speed": False},
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


def gemini_meta(v: dict) -> dict:
    return {
        "name": v["id"],
        "display": v.get("display_name") or v["id"],
        "lang": v.get("language_code", "en-US"),
        "gender": (v.get("gender") or "?").capitalize(),
        "desc": v.get("persona") or v.get("accent") or "",
    }


def _fetch_gemini_voices() -> list:
    voices, token = [], None
    for _ in range(30):
        url = "https://generativelanguage.googleapis.com/v1beta/voices?pageSize=200"
        if token:
            url += f"&pageToken={token}"
        req = urllib.request.Request(url, headers={"x-goog-api-key": GEMINI_API_KEY})
        data = json.loads(urllib.request.urlopen(req, timeout=60).read())
        voices += data.get("voices", [])
        token = data.get("next_page_token")
        if not token:
            return voices
    return voices


def get_gemini_voices() -> list:
    if GEMINI_VOICES_CACHE.exists():
        try:
            blob = json.loads(GEMINI_VOICES_CACHE.read_text())
            if time.time() - blob["ts"] < GEMINI_VOICES_MAX_AGE:
                return blob["voices"]
        except Exception:
            pass
    try:
        voices = _fetch_gemini_voices()
        GEMINI_VOICES_CACHE.write_text(
            json.dumps({"ts": time.time(), "voices": voices})
        )
        return voices
    except Exception:
        # Offline fallback: the 30 studio voices
        return [
            {
                "id": name,
                "display_name": name,
                "language_code": "en-US",
                "gender": gender.lower(),
                "persona": style,
            }
            for name, style, gender in GEMINI_VOICES
        ]


def check_engine(engine: str) -> str:
    if engine not in ENGINES:
        raise HTTPException(400, f"Unknown engine '{engine}'")
    if engine == "qwen3" and not QWEN_ENABLED:
        raise HTTPException(
            400,
            "Qwen3-TTS is disabled on this machine (needs an NVIDIA GPU to be "
            "practical). Start the server with QWEN_ENABLED=1 to force it.",
        )
    if engine == "gemini" and not GEMINI_API_KEY:
        raise HTTPException(
            400,
            "Gemini TTS is disabled: set GEMINI_API_KEY in the .env file "
            "(free key at https://aistudio.google.com/apikey).",
        )
    return engine


def check_voice(engine: str, voice: str) -> None:
    if engine == "kokoro":
        if not re.fullmatch(r"[a-z]{2}_[a-z]+", voice) or voice not in KOKORO_NAMES:
            raise HTTPException(400, f"Unknown Kokoro voice '{voice}'")
    elif engine == "qwen3":
        if voice not in {v[0] for v in QWEN_VOICES}:
            raise HTTPException(400, f"Unknown Qwen3 speaker '{voice}'")
    else:
        if voice.lower() not in {v["id"].lower() for v in get_gemini_voices()}:
            raise HTTPException(400, f"Unknown Gemini voice '{voice}'")


# ---------------------------------------------------------------- api


class VoiceReq(BaseModel):
    engine: str = "kokoro"
    voice: str


class Segment(BaseModel):
    emotion: str = "Neutral"
    text: str


class GenerateReq(BaseModel):
    engine: str = "kokoro"
    text: str = ""
    segments: list[Segment] = []
    voice: str
    speed: float = 1.0
    instruct: str = ""


class EnrichReq(BaseModel):
    text: str


class VideoJobManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = {}

    def create(self, audio_path: Path, images: list, script: str, options: dict) -> str:
        job_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        job_dir = self.root / job_id
        job_dir.mkdir()
        names = []
        for i, p in enumerate(images):
            name = f"img_{i:02d}{p.suffix or '.jpg'}"
            shutil.copyfile(p, job_dir / name)
            names.append(name)
        self.jobs[job_id] = {
            "id": job_id, "stage": "Queued", "pct": 0, "done": False, "error": None,
            "dir": job_dir, "audio": audio_path, "images": names,
            "script": script, "options": options,
        }
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return job_id

    def _run(self, job_id: str):
        job = self.jobs[job_id]

        def progress(stage: str, pct: int):
            job["stage"], job["pct"] = stage, pct

        try:
            result = make_video(job["dir"], job["audio"], job["images"],
                                job["script"], job["options"], progress)
            job["done"], job["pct"] = True, 100
            job["stage"] = f"Done — {result['scenes']} scenes, {result['duration']:.0f}s audio"
        except Exception as e:
            job["done"], job["error"] = True, str(e)[:300]


video_mgr = VideoJobManager(OUT_DIR / "video_jobs")


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
    engines.append(
        {
            "id": "gemini",
            "label": ENGINES["gemini"]["label"],
            "styles": True,
            "speed": False,
            "enabled": bool(GEMINI_API_KEY),
            "voices": [gemini_meta(v) for v in get_gemini_voices()],
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


def _gemini_synth(text: str, voice: str, instruct: str):
    prompt = f"{instruct}: {text}" if instruct else text
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice}
                    }
                },
            },
        }
    ).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail)["error"]["message"]
        except Exception:
            pass
        raise HTTPException(502, f"Gemini API error: {detail}")
    try:
        part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError):
        raise HTTPException(502, f"Gemini returned no audio: {str(data)[:300]}")
    mime = part.get("mimeType", "")
    raw = base64.b64decode(part["data"])
    if "rate=" in mime:  # raw PCM (2.5 models)
        rate = int(mime.split("rate=")[-1]) or 24000
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:  # container format, e.g. audio/wav (3.x models)
        samples, rate = sf.read(io.BytesIO(raw), dtype="float32")
    return samples, rate


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
    elif engine == "gemini":
        text = "Hi there! This is how I sound. Pretty nice, right?"
        samples, sr = await asyncio.to_thread(_gemini_synth, text, req.voice, "")
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

    if req.segments:
        if engine != "gemini":
            raise HTTPException(
                400, "Emotion segments work with the Gemini engine only"
            )
        parts, rates, total = [], set(), 0
        for seg in req.segments:
            seg_text = seg.text.strip()
            if not seg_text:
                continue
            total += len(seg_text)
            if total > MAX_CHARS["gemini"]:
                raise HTTPException(
                    400, f"Script too long ({MAX_CHARS['gemini']} characters max)"
                )
            instruction = EMOTION_MAP.get(seg.emotion.strip().capitalize(), "")
            samples, sr = await asyncio.to_thread(
                _gemini_synth, seg_text, req.voice, instruction
            )
            parts.append(samples)
            rates.add(sr)
        if not parts:
            raise HTTPException(400, "Script is empty")
        if len(rates) != 1:
            raise HTTPException(502, "Mixed sample rates across segments")
        samples, sr = np.concatenate(parts), rates.pop()
    else:
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
        elif engine == "gemini":
            instruct = req.instruct.strip()[:200]
            samples, sr = await asyncio.to_thread(
                _gemini_synth, text, req.voice, instruct
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


def _gemini_text_call(prompt: str, json_mode: bool = False) -> str:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last_err = ""
    for model in GEMINI_TEXT_FALLBACKS:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            try:
                detail = json.loads(detail)["error"]["message"]
            except Exception:
                pass
            last_err = f"{model}: {detail}"
            if e.code not in (503, 429, 500):
                break  # non-retryable for this model class
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            last_err = f"{model}: {e}"
        except (KeyError, IndexError):
            raise HTTPException(502, f"Gemini returned no text: {str(data)[:300]}")
    raise HTTPException(502, f"Gemini API error: {last_err}")


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


@app.get("/api/emotions")
def list_emotions():
    return {"emotions": [{"emotion": n, "instruction": i} for n, i in EMOTIONS]}


@app.post("/api/enrich")
async def enrich(req: EnrichReq):
    if not GEMINI_API_KEY:
        raise HTTPException(400, "Gemini TTS is disabled: set GEMINI_API_KEY in .env")
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Script is empty")
    if len(text) > MAX_CHARS["gemini"]:
        raise HTTPException(400, f"Script too long ({MAX_CHARS['gemini']} characters max)")

    allowed = ", ".join(n for n, _ in EMOTIONS)
    prompt = (
        "You are a voice director. Split the script below into segments and assign "
        "an emotion to each segment.\n"
        "STRICT RULES:\n"
        f"1. Use ONLY these emotions: {allowed}.\n"
        "2. NEVER add, remove, rewrite or fix any word. The concatenation of all "
        "segment texts, in order, must reproduce the script EXACTLY, character for "
        "character (including punctuation).\n"
        "3. Split at natural emotional shifts (sentence or clause level). No empty "
        "segments. First and last segments must cover the whole script.\n"
        '4. Respond with JSON only: {"segments": [{"emotion": "...", "text": "..."}]}\n\n'
        f"SCRIPT:\n{text}"
    )

    last_err = ""
    for attempt in range(2):
        raw = await asyncio.to_thread(_gemini_text_call, prompt, True)
        try:
            parsed = json.loads(raw)
            segments = parsed["segments"]
        except Exception:
            last_err = "could not parse AI response"
            continue
        try:
            out = []
            for seg in segments:
                emo = str(seg["emotion"]).strip().capitalize()
                if emo not in EMOTION_MAP:
                    raise ValueError(f"emotion '{seg['emotion']}' not allowed")
                seg_text = str(seg["text"])
                if not seg_text.strip():
                    raise ValueError("empty segment")
                out.append({"emotion": emo, "text": seg_text})
        except (KeyError, TypeError, ValueError) as e:
            last_err = str(e)
            continue
        if _norm("".join(s["text"] for s in out)) != _norm(text):
            last_err = "AI modified the script text"
            prompt += (
                "\n\nIMPORTANT: Your previous answer changed the script wording. "
                "Copy the script text EXACTLY, splitting it without any edits."
            )
            continue
        return {"segments": out, "model": GEMINI_TEXT_MODEL}
    raise HTTPException(502, f"Emotion analysis failed: {last_err}")


@app.get("/api/audio/library")
def audio_library():
    files = sorted(OUT_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "url": f"/audio_out/{p.name}"} for p in files[:30]]


@app.post("/api/video/build")
async def video_build(
    images: list[UploadFile] = File(...),
    script: str = Form(""),
    options: str = Form("{}"),
    audio: UploadFile | None = File(None),
    audio_id: str = Form(""),
):
    if not images or not images[0].filename:
        raise HTTPException(400, "Upload at least one image")
    try:
        opts = json.loads(options or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid options")

    if audio and audio.filename:
        suffix = Path(audio.filename).suffix or ".mp3"
        audio_path = OUT_DIR / f"upload_{int(time.time())}{suffix}"
        audio_path.write_bytes(await audio.read())
    elif audio_id:
        audio_path = OUT_DIR / Path(audio_id).name
        if not audio_path.exists():
            raise HTTPException(400, "Selected library audio no longer exists")
    else:
        raise HTTPException(400, "Provide an audio file or pick one from the library")

    tmp_images = []
    for img in images:
        suffix = Path(img.filename).suffix or ".jpg"
        p = OUT_DIR / f"upimg_{uuid.uuid4().hex[:8]}{suffix}"
        p.write_bytes(await img.read())
        tmp_images.append(p)
    if not tmp_images:
        raise HTTPException(400, "No readable images")

    job_id = video_mgr.create(audio_path, tmp_images, script, opts)
    return {"job_id": job_id}


@app.get("/api/video/status/{job_id}")
def video_status(job_id: str):
    job = video_mgr.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return {
        "stage": job["stage"], "pct": job["pct"],
        "done": job["done"], "error": job["error"],
    }


@app.get("/api/video/download/{job_id}")
def video_download(job_id: str):
    job = video_mgr.jobs.get(job_id)
    if not job or not job["done"] or job["error"]:
        raise HTTPException(404, "Video not ready")
    return FileResponse(job["dir"] / "story.mp4", media_type="video/mp4", filename="story.mp4")


@app.get("/api/video/vnpack/{job_id}")
def video_vnpack(job_id: str):
    job = video_mgr.jobs.get(job_id)
    if not job or not job["done"] or job["error"]:
        raise HTTPException(404, "Video not ready")
    zpath = make_vn_pack(job["dir"])
    return FileResponse(zpath, media_type="application/zip", filename="vn_pack.zip")


app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")
app.mount("/audio_out", StaticFiles(directory=OUT_DIR), name="audio_out")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/", StaticFiles(directory=BASE / "static", html=True), name="static")
