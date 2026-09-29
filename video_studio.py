"""Local story-video renderer: images + audio + script -> captioned MP4."""

import io
import json
import math
import re
import subprocess
import zipfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import soundfile as sf

FPS = 30
CANVAS = {
    ("16:9", 720): (1280, 720),
    ("16:9", 1080): (1920, 1080),
    ("9:16", 720): (720, 1280),
    ("9:16", 1080): (1080, 1920),
    ("1:1", 720): (720, 720),
    ("1:1", 1080): (1080, 1080),
}
FADE_DUR = 0.25
XFADE_DUR = 0.5


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list, cwd: Path) -> None:
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error"] + args
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")


def to_wav(src: Path, dst: Path) -> float:
    """Convert any uploaded audio to wav; returns duration in seconds."""
    run_ffmpeg(
        ["-i", str(src.resolve()), "-vn", "-ac", "2", "-ar", "44100", str(dst.resolve())],
        src.parent,
    )
    info = sf.info(str(dst))
    return info.duration


def split_sentences(text: str) -> list:
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text.strip()) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def build_timeline(duration: float, sentences: list, n_images: int) -> list:
    """Scenes = image slots; sentences distributed by length, images cycled."""
    if not sentences:
        return [
            {
                "img": i % n_images,
                "start": i * duration / n_images,
                "dur": duration / n_images,
                "lines": [],
            }
            for i in range(n_images)
        ]
    weights = [len(s) for s in sentences]
    total_w = sum(weights)
    cues, t = [], 0.0
    for s, w in zip(sentences, weights):
        d = duration * w / total_w
        cues.append({"start": t, "dur": d, "text": s})
        t += d

    # group cues into n_images scenes at the largest gaps in cue boundaries
    bounds = sorted({round(c["start"], 4) for c in cues[1:]})
    cuts = set()
    if n_images > 1:
        for k in range(1, n_images):
            target = duration * k / n_images
            if bounds:
                cuts.add(min(bounds, key=lambda b: abs(b - target)))
    scenes, scene_cues, raw_start = [], [], 0.0
    for c in cues:
        if round(c["start"], 4) in cuts and scene_cues:
            scenes.append((raw_start, c["start"] - raw_start, scene_cues))
            scene_cues = []
            raw_start = c["start"]
        scene_cues.append(c)
    scenes.append((raw_start, duration - raw_start, scene_cues))
    return [
        {"img": i % n_images, "start": st, "dur": du, "cues": cs}
        for i, (st, du, cs) in enumerate(scenes)
    ]


def _zoom_expr(variant: int, total_frames: int) -> str:
    tf = max(total_frames - 1, 1)
    if variant % 4 == 0:
        return f"z='min(1+0.10*on/{tf},1.10)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
    if variant % 4 == 1:
        return f"z='max(1.10-0.10*on/{tf},1.0)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
    if variant % 4 == 2:
        return f"z='1.10':x='(iw-iw/zoom)*on/{tf}':y='(ih-ih/zoom)/2'"
    return f"z='1.10':x='(iw-iw/zoom)*(1-on/{tf})':y='(ih-ih/zoom)/2'"


def render_scene(ffmpeg: str, job_dir: Path, idx: int, img: str, dur: float,
                 w: int, h: int, variant: int, style: str) -> float:
    """Render one scene mp4 (video only). Returns adjusted duration."""
    dur = max(round(dur, 3), 0.6)
    tf = int(dur * FPS)
    zp = _zoom_expr(variant, tf)
    chain = [
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase",
        f"crop={w*2}:{h*2}",
        f"zoompan={zp}:d=1:s={w}x{h}:fps={FPS}",
        "format=yuv420p",
    ]
    if style == "fade":
        chain += [f"fade=t=in:st=0:d={FADE_DUR}", f"fade=t=out:st={max(dur - FADE_DUR, 0):.3f}:d={FADE_DUR}"]
    vf = ",".join(chain)
    run_ffmpeg(
        ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", img,
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         f"scene_{idx:04d}.mp4"],
        job_dir,
    )
    return dur


def concat_scenes(ffmpeg: str, job_dir: Path, n: int, style: str,
                  durations: list, w: int, h: int, cues_flat: list) -> None:
    """Join scene videos (crossfade chains with xfade; fade mode copies)."""
    if style == "fade" or n == 1:
        with open(job_dir / "list.txt", "w") as f:
            for i in range(n):
                f.write(f"file 'scene_{i:04d}.mp4'\n")
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", "list.txt",
                    "-c", "copy", "joined.mp4"], job_dir)
        return

    inputs = []
    for i in range(n):
        inputs += ["-i", f"scene_{i:04d}.mp4"]
    chain = []
    prev = "[0:v]"
    offset = 0.0
    for i in range(1, n):
        offset += durations[i - 1] - XFADE_DUR
        out = f"[v{i}]" if i < n - 1 else "[vout]"
        chain.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={XFADE_DUR}:offset={offset:.3f}{out}"
        )
        prev = out
    run_ffmpeg(inputs + ["-filter_complex", ";".join(chain), "-map", "[vout]",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                         "joined.mp4"], job_dir)
    _shift_cues_for_xfade(cues_flat, durations, XFADE_DUR)


def _shift_cues_for_xfade(cues: list, durations: list, t: float) -> None:
    """Adjust cue times: video timeline shrinks by t at each scene boundary."""
    starts, acc = [], 0.0
    for d in durations:
        starts.append(acc)
        acc += d
    new_starts, shift = [], 0.0
    for i, st in enumerate(starts):
        new_starts.append(st - shift)
        shift += t
    for c in cues:
        idx = max([i for i, st in enumerate(starts) if c["start"] >= st - 1e-6], default=0)
        c["start"] = max(new_starts[idx] + (c["start"] - starts[idx]), 0)


def _ass_time(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(cues: list, w: int, h: int) -> str:
    font = max(round(h * 0.055), 24)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Segoe UI,{font},&H00FFFFFF,&H00F16663,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,1,3,1,2,{int(w*0.06)},{int(w*0.06)},{int(h*0.09)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in cues:
        words = c["text"].split()
        if not words:
            continue
        total_chars = sum(len(wd) + 1 for wd in words)
        kar = []
        acc = 0.0
        for wd in words:
            share = c["dur"] * (len(wd) + 1) / total_chars
            cs = max(int(round((acc + share - acc) * 100)), 8)
            kar.append(f"{{\\k{int(round(share * 100)) or 8}}}{wd}")
            acc += share
        text = " ".join(kar)
        end = c["start"] + c["dur"]
        lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(end)},Cap,,0,0,0,,{{\\fad(80,80)}}{text}")
    return header + "\n".join(lines) + "\n"


def build_srt(cues: list) -> str:
    def fmt(t):
        h, rem = divmod(max(t, 0), 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},000"

    out = []
    for i, c in enumerate([c for c in cues if c.get("text")], 1):
        out.append(f"{i}\n{fmt(c['start'])} --> {fmt(c['start'] + c['dur'])}\n{c['text']}\n")
    return "\n".join(out)


def make_video(job_dir: Path, audio_src: Path, images: list, script: str,
               options: dict, progress) -> dict:
    ffmpeg = ffmpeg_exe()
    ratio, res = options.get("ratio", "16:9"), int(options.get("resolution", 720))
    w, h = CANVAS[(ratio, res)]
    style = options.get("transition", "fade")
    motion = options.get("motion", True)
    captions = options.get("captions", True) and bool(script.strip())

    progress(stage="Preparing audio", pct=5)
    wav = job_dir / "audio.wav"
    duration = to_wav(audio_src, wav)

    sentences = split_sentences(script) if captions else []
    scenes = build_timeline(duration, sentences, len(images))
    progress(stage="Rendering scenes", pct=10)

    durations = []
    for i, sc in enumerate(scenes):
        dur = render_scene(ffmpeg, job_dir, i, images[sc["img"]], sc["dur"],
                           w, h, i if motion else -1, style)
        durations.append(dur)
        pct = 10 + int(70 * (i + 1) / len(scenes))
        progress(stage=f"Rendering scene {i + 1}/{len(scenes)}", pct=pct)

    # flat caption cues keep absolute (audio) timeline; xfade shift applied after concat
    cues_flat = []
    for sc in scenes:
        for c in sc["cues"]:
            cues_flat.append({"start": c["start"], "dur": c["dur"], "text": c["text"]})

    progress(stage="Stitching scenes", pct=85)
    concat_scenes(ffmpeg, job_dir, len(scenes), style, durations, w, h, cues_flat)

    if captions:
        progress(stage="Burning captions", pct=92)
        (job_dir / "subs.ass").write_text(build_ass(cues_flat, w, h), encoding="utf-8")
        vf = "ass=subs.ass"
    else:
        vf = "null"

    progress(stage="Finalizing", pct=96)
    args = ["-i", "joined.mp4", "-i", "audio.wav",
            "-vf", vf,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-shortest", "story.mp4"]
    run_ffmpeg(args, job_dir)

    srt = build_srt(cues_flat)
    (job_dir / "captions.srt").write_text(srt, encoding="utf-8")
    lines = ["Scene timing (for VN / manual editing)", "=" * 40]
    t = 0.0
    for i, d in enumerate(durations):
        lines.append(f"scene {i + 1:02d}  {t:7.2f}s -> {t + d:7.2f}s   image: {Path(images[scenes[i]['img']]).name}")
        t += d
    (job_dir / "timing_sheet.txt").write_text("\n".join(lines), encoding="utf-8")

    out = job_dir / "story.mp4"
    return {"video": str(out), "duration": duration, "scenes": len(scenes), "captions": len(cues_flat)}


def make_vn_pack(job_dir: Path) -> Path:
    zpath = job_dir / "vn_pack.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ["captions.srt", "timing_sheet.txt", "story.mp4"]:
            p = job_dir / name
            if p.exists():
                z.write(p, name)
    return zpath
