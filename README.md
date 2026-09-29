# Kokoro Studio

A fast, offline text-to-speech web studio powered by the [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model. Paste or upload a script, audition **54 voices** across 9 languages, and generate studio-ready WAV audio — all on your own CPU.

## Features

- **Script input** — drag & drop a `.txt` file or paste text, with live character/word counts
- **54 neural voices** — filter by language tab, search by name, preview any voice with one click (samples are cached for instant replay)
- **Speed control** — 0.5x to 2x playback speed
- **Instant results** — inline audio player + one-click WAV download
- **Runs 100% offline** — no API keys, no cloud, no telemetry
- **Polished UI** — light/dark theme, responsive layout, accessible (keyboard + focus rings + ARIA)

## Quick start

Requires **Python 3.10–3.12**.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download the model files (~352 MB, one time)
python download_models.py

# 3. Start the studio
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** in your browser.

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

## API

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/voices` | GET | — | Voice catalog with language/gender metadata |
| `/api/preview` | POST | `{"voice": "am_puck"}` | `{url, cached}` — cached 2s sample |
| `/api/generate` | POST | `{"text", "voice", "speed"}` | `{url, duration, voice}` — rendered WAV |

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
