"""Proof of concept: run Qwen3-TTS on AMD GPU via DirectML, fallback to CPU."""

import time

import soundfile as sf
import torch


def try_directml():
    import os

    if os.environ.get("QWEN_FORCE_CPU"):
        print("DirectML skipped (QWEN_FORCE_CPU)")
        return None, None
    try:
        import torch_directml

        dml = torch_directml.device()
        name = torch_directml.device_name(0)
        x = torch.rand(1024, 1024, device=dml)
        _ = x @ x  # sanity check
        return dml, name
    except Exception as e:
        print(f"DirectML unavailable: {e}")
        return None, None


dml, device_name = try_directml()
print(f"Device: {device_name or 'CPU'}")

t0 = time.time()
from qwen_tts import Qwen3TTSModel

model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
    dtype=torch.bfloat16,
)
if dml is not None:
    model.model = model.model.to(dml)
    model.device = dml
print(f"Model loaded in {time.time() - t0:.1f}s on {model.device}")

t0 = time.time()
wavs, sr = model.generate_custom_voice(
    text="Hi there! I am running on your graphics card.",
    language="English",
    speaker="Aiden",
)
elapsed = time.time() - t0
audio_dur = len(wavs[0]) / sr
print(f"Generated {audio_dur:.1f}s audio in {elapsed:.1f}s (RTF {elapsed / audio_dur:.2f}x)")

sf.write("qwen_device_test.wav", wavs[0], sr)
print("Saved qwen_device_test.wav")
