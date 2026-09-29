"""Download Kokoro model files (~352 MB total, one time)."""

import sys
import urllib.request
from pathlib import Path

FILES = {
    "kokoro-v1.0.onnx": (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
        "model-files-v1.0/kokoro-v1.0.onnx"
    ),
    "voices-v1.0.bin": (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
        "model-files-v1.0/voices-v1.0.bin"
    ),
}


def progress(count: int, block: int, total: int) -> None:
    done = min(count * block, total)
    pct = done * 100 // total
    sys.stdout.write(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB ({pct}%)")
    sys.stdout.flush()


def main() -> None:
    for name, url in FILES.items():
        dest = Path(__file__).parent / name
        if dest.exists():
            print(f"[skip] {name} already exists")
            continue
        print(f"[get ] {name}")
        urllib.request.urlretrieve(url, dest, reporthook=progress)
        print()
    print("Done. Start the studio with:\n  python -m uvicorn app:app --host 127.0.0.1 --port 8000")


if __name__ == "__main__":
    main()
