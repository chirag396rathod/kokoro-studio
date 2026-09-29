# Kokoro Studio

A fast, offline text-to-speech web studio with **two engines** powered by open-source models. Paste or upload a script, audition voices, and generate studio-ready WAV audio — all on your own machine.

- **Kokoro 82M** — 54 voices across 9 languages, real-time on CPU ([hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M))
- **Gemini TTS (`gemini-3.8-flash-tts`, cloud)** — **2,089 voices across 30 locales** with natural-language **style instructions** ("say it like a sports commentator"). Needs a free API key in `.env`; auto-disabled without one ([Gemini API](https://ai.google.dev/gemini-api/docs/speech-generation))

## Features

- **Script input** — drag & drop a `.txt` file or paste text, with live character/word counts
- **Engine switcher** — pick Kokoro (54 voices, fast) or Qwen3-TTS 0.6B (9 speakers, more expressive)
- **Voice previews** — filter by language tab, search by name, audition any voice with one click (samples are cached for instant replay)
- **Style instructions** — Qwen3 voices accept natural-language direction, e.g. *"speak in a very excited tone"*
- **Speed control** — 0.5x to 2x playback speed (Kokoro)
- **Instant results** — inline audio player + one-click WAV download
- **Runs 100% offline** — no API keys, no cloud, no telemetry
- **Polished UI** — light/dark theme, responsive layout, accessible (keyboard + focus rings + ARIA)

## Quick start

Requires **Python 3.10–3.12**.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download the model files (~352 MB Kokoro, one time)
python download_models.py

# 3. Start the studio
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** in your browser.

### About the Gemini TTS engine (cloud)

Uses Google's `gemini-3.8-flash-tts` via the Gemini API. Setup:

1. Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Copy `.env.example` to `.env` and paste your key
3. Restart the server

The full voice catalog (2,089 voices / 30 locales) is fetched from Google's voice library and cached locally for 7 days (`cache/gemini_voices.json`). Free tier has daily quotas; paid tier costs ~$10 per 1M audio tokens (a short clip is a fraction of a cent).

### About the Qwen3-TTS engine (local, optional)

Qwen3-TTS runs locally through PyTorch and is **only practical on an NVIDIA GPU**. On machines without one it is shown greyed out (measured ~250x real-time on CPU; DirectML is unstable with this model). Set `QWEN_ENABLED=1` to force it on.

### Sanity check (optional)

```bash
python test_kokoro.py   # generates three funny WAVs with different voices
```

## Voices (54)

Voice names follow `<language><gender>_<name>`: `a` = American English, `b` = British English, `e` = Spanish, `f` = French, `h` = Hindi, `i` = Italian, `j` = Japanese, `p` = Brazilian Portuguese, `z` = Mandarin; `f`/`m` = female/male.

| Language | Female | Male |
|---|---|---|
| English (US) | af_alloy, af_aoede, af_bella, af_heart, af_jessica, af_kore, af_nicole, af_nova, af_river, af_sarah, af_sky | am_adam, am_echo, am_eric, am_fenrir, am_liam, am_michael, am_onyx, am_puck, am_santa |
| English (UK) | bf_alice, bf_emma, bf_isabella, bf_lily | bm_daniel, bm_fable, bm_george, bm_lewis |
| Spanish | ef_dora | em_alex, em_santa |
| French | ff_siwis | — |
| Hindi | hf_alpha, hf_beta | hm_omega, hm_psi |
| Italian | if_sara | im_nicola |
| Japanese | jf_alpha, jf_gongitsune, jf_nezumi, jf_tebukuro | jm_kumo |
| Portuguese (BR) | pf_dora | pm_alex, pm_santa |
| Mandarin | zf_xiaobei, zf_xiaoni, zf_xiaoxiao, zf_xiaoyi | zm_yunjian, zm_yunxi, zm_yunxia, zm_yunyang |

## Qwen3-TTS speakers (9)

Downloaded automatically from Hugging Face on first use (~2.5 GB with the speech tokenizer).

| Speaker | Description | Native language |
|---|---|---|
| Vivian | Bright young female | Chinese |
| Serena | Warm, gentle young female | Chinese |
| Uncle_Fu | Seasoned male, mellow timbre | Chinese |
| Dylan | Youthful Beijing male | Chinese (Beijing) |
| Eric | Lively Chengdu male | Chinese (Sichuan) |
| Ryan | Dynamic male with rhythm | English |
| Aiden | Sunny American male | English |
| Ono_Anna | Playful Japanese female | Japanese |
| Sohee | Warm Korean female | Korean |

## API

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/voices` | GET | — | Engine catalog with per-engine voice metadata |
| `/api/preview` | POST | `{"engine", "voice"}` | `{url, cached}` — cached sample |
| `/api/generate` | POST | `{"engine", "text", "voice", "speed", "instruct"}` | `{url, duration, voice, engine}` |

## Project structure

```
├── app.py              # FastAPI server (model loads once, synthesis in threadpool)
├── download_models.py  # One-time model file downloader
├── test_kokoro.py      # CLI sanity check
├── static/
│   ├── index.html      # Single-page UI (no build step)
│   ├── style.css       # Design system (light/dark themes)
│   └── app.js          # Upload, voice picker, generate flow
├── cache/              # Cached voice previews (created at runtime)
└── audio_out/          # Generated WAVs (created at runtime)
```

## Tech

- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) — ONNX runtime inference for Kokoro-82M (~325 MB fp32 model)
- FastAPI + vanilla HTML/CSS/JS — zero frontend build tooling
- Model weights are excluded from git; `download_models.py` fetches them from the official release

## License

[MIT](LICENSE)
