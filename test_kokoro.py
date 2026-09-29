import asyncio
import soundfile as sf
from kokoro_onnx import Kokoro

TEXT = (
    "I told my computer I needed a break, and now it won't stop sending me KitKat ads. "
    "Yesterday my WiFi and I finally had the talk. It said it needed some space. "
    "So now I'm dating a cloud. It's called OneDrive. "
    "Honestly, my smart fridge is the only one who listens to me anymore... "
    "and it just keeps judging my cheese intake."
)

VOICES = [
    ("am_puck", "en-us"),
    ("af_bella", "en-us"),
    ("bm_george", "en-gb"),
]

async def main():
    kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
    print(f"Model loaded. {len(kokoro.get_voices())} voices available.")

    for voice, lang in VOICES:
        print(f"Generating with '{voice}'...")
        samples, sample_rate = kokoro.create(
            TEXT, voice=voice, speed=1.0, lang=lang
        )
        out = f"funny_{voice}.wav"
        sf.write(out, samples, sample_rate)
        print(f"  Saved {out} ({len(samples) / sample_rate:.1f}s)")

asyncio.run(main())
