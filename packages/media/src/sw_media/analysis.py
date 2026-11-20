"""Phase-two local, bounded media analysis. Coordinates are source-relative milliseconds."""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

from sw_contracts.validation import RuleError
from sw_media.tools import binary, probe, run

MAX_BYTES = 64 * 1024 * 1024
MAX_DURATION_MS = 180_000
MAX_DIMENSION = 3840
ALLOWED_SUFFIXES = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
TOOL_POLICY = "media-evidence-v1"


def sha_file(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def ffmpeg(source, *args, timeout=40, before=()):
    return run([
        binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm",
        "-threads", "2", "-filter_threads", "1", *before, "-i", str(source), *map(str, args),
    ], timeout=timeout)


def seconds(ms):
    return f"{ms / 1000:.3f}"


def tool_versions():
    return {name: run([binary(name), "-version"]).splitlines()[0] for name in ("ffmpeg", "ffprobe")}


def inspect(source):
    try:
        data = probe(source)
    except (TypeError, ValueError, OverflowError):
        raise RuleError("INVALID_MEDIA", "No measurable video duration") from None
    videos = [s for s in data["streams"] if s["codec_type"] == "video"]
    if not videos or not 0 < data["duration_ms"] <= MAX_DURATION_MS:
        raise RuleError("INVALID_MEDIA", "Video must contain footage and be at most 180 seconds")
    video = videos[0]
    w, h = video.get("width", 0), video.get("height", 0)
    if min(w, h) <= 0 or max(w, h) > MAX_DIMENSION or w * h > 3840 * 2160:
        raise RuleError("INVALID_MEDIA", "Video dimensions exceed the analysis budget")
    data.update(width=w, height=h, has_audio=any(s["codec_type"] == "audio" for s in data["streams"]))
    return data


def slice_intervals(duration, cuts):
    cuts = sorted({ms for ms in cuts if 0 < ms < duration})
    points = [0]
    scene_boundaries = 0
    fallback_boundaries = 0
    for end in [*cuts, duration]:
        if end != duration and (end - points[-1] < 1800 or duration - end < 1200):
            continue
        while end - points[-1] > 12_000:
            points.append(points[-1] + 8_000)
            fallback_boundaries += 1
        points.append(end)
        scene_boundaries += end != duration
    mode = "scene_and_fixed" if scene_boundaries and fallback_boundaries else (
        "scene" if scene_boundaries else "fixed_or_single"
    )
    return list(zip(points, points[1:])), mode


def scan_cuts(source):
    return [round(float(t) * 1000) for t in re.findall(
        r"pts_time:([\d.]+)", ffmpeg(source, "-an", "-vf",
        "fps=4,scale=320:-2,select=gt(scene\\,0.35),metadata=mode=print:file=-", "-f", "null", "-")
    )]


def prepare_media(source, work, data):
    # A browser-safe proxy preserves the source's relative time scale. No visual edits are applied.
    preview = work / "preview.mp4"
    ffmpeg(source, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1",
           "-vf", "scale='min(960,iw)':-2", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-threads", "2", "-crf", "25", "-c:a", "aac", "-movflags", "+faststart",
           preview, timeout=75)
    if preview.stat().st_size > MAX_BYTES:
        raise RuleError("FILE_TOO_LARGE", "Preview exceeds analysis budget")
    intervals, split = slice_intervals(data["duration_ms"], scan_cuts(source))
    rows = []
    for i, (start, end) in enumerate(intervals):
        # Output seeking from the bounded proxy avoids inaccurate input seeks on long GOPs.
        frame_ms = start + (end - start) // 3
        frame = work / f"frame-{i:03}.jpg"
        stats = ffmpeg(preview, "-an", "-vf",
                       "scale=320:-2,signalstats,metadata=mode=print:file=-", "-frames:v", "1",
                       "-q:v", "4", "-f", "image2", "-update", "1", frame,
                       timeout=8, before=("-ss", seconds(frame_ms)))
        if not frame.is_file() or frame.stat().st_size == 0:
            raise RuleError("INVALID_MEDIA", "Cannot locate representative frame")
        match = re.search(r"lavfi\.signalstats\.YAVG=([\d.]+)", stats)
        y = round(float(match[1]), 2) if match else None
        rows.append({"in_ms": start, "out_ms": end, "frame_ms": frame_ms, "frame": frame.name,
                     "signals": {"width": data["width"], "height": data["height"], "luma_yavg": y,
                                 "exposure_hint": "unknown" if y is None else "dark_sample" if y < 35
                                 else "bright_sample" if y > 220 else "no_extreme_at_sample"}})
    return preview, rows, split


def speech(source, work, model, language, duration):
    if not model:
        raise RuleError("TRANSCRIPTION_NOT_CONFIGURED", "Configure the local speech model for audio-bearing videos")
    path = Path(model)
    if not path.is_dir() or not all((path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")):
        raise RuleError("TRANSCRIPTION_NOT_CONFIGURED", "Local speech model snapshot is incomplete")
    model_hashes = {name: sha_file(path / name) for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")}
    wav = work / "speech.wav"
    # Retain input-relative timestamps and pad leading silence for a delayed audio stream.
    ffmpeg(source, "-map", "0:a:0", "-vn", "-af", "aresample=async=1:first_pts=0",
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-t", seconds(duration), wav,
           before=("-copyts", "-start_at_zero"))
    try:
        result = json.loads(run([sys.executable, "-m", "sw_media.local_speech", str(path), str(wav), language],
                                timeout=180))
    except RuleError as exc:
        code = "TRANSCRIPTION_TIMEOUT" if exc.code == "MEDIA_TIMEOUT" else "TRANSCRIPTION_FAILED"
        raise RuleError(code, "Local speech analysis failed") from None
    finally:
        wav.unlink(missing_ok=True)
    def normalize(row):
        a, b = float(row["start"]), float(row["end"])
        if not math.isfinite(a) or not math.isfinite(b):
            return None
        start, end = max(0, round(a * 1000)), min(duration, round(b * 1000))
        if end > start and row["text"].strip():
            return {"in_ms": start, "out_ms": end, "text": row["text"]}
        return None

    rows = []
    for row in result["segments"]:
        utterance = normalize(row)
        if utterance:
            words = [parsed for word in row["words"] if (parsed := normalize(word))]
            rows.append({**utterance, "words": words})
    return rows, {"status": "succeeded", "provider": "faster-whisper-local", "version": result["version"],
                  "language": result["language"], "snapshot": path.name, "model_files_sha256": model_hashes,
                  "utterance_count": len(rows), "audio_ms": result["audio_ms"], "remote_model_called": False}
