"""Bounded local media probes. No shell, remote URLs, playlist demuxers or model calls."""

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from sw_contracts.validation import RuleError

ROOT = Path(__file__).resolve().parents[4]


def binary(name):
    configured = os.environ.get(name.upper() + "_PATH")
    found = configured or shutil.which(name)
    if not found and name == "ffprobe":
        candidate = ROOT / ".cache/media/node_modules/@ffprobe-installer/win32-x64/ffprobe.exe"
        if candidate.is_file():
            found = str(candidate)
    if not found and name == "ffmpeg":
        try:
            import imageio_ffmpeg

            found = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            pass
    if not found:
        raise RuleError("DEPENDENCY_UNAVAILABLE", name + " executable is not configured")
    return str(found)


def run(args, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise RuleError("DEPENDENCY_UNAVAILABLE", "Media executable not found") from None
    except subprocess.TimeoutExpired:
        raise RuleError("MEDIA_TIMEOUT", "Media process exceeded the probe time limit") from None
    if result.returncode:
        # Native stderr may disclose absolute paths. Keep it out of API error responses.
        raise RuleError("INVALID_MEDIA", "Media tool rejected the input")
    if len(result.stdout) > 1024 * 1024:
        raise RuleError("INVALID_MEDIA", "Media probe response exceeds limit")
    return result.stdout.decode("utf-8", errors="replace")


def probe(path):
    path = Path(path).resolve(strict=True)
    raw = run(
        [
            binary("ffprobe"),
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov,matroska,webm,avi,wav,mp3,ogg,flac",
            "-show_entries",
            "format=duration,format_name,size:stream=codec_type,codec_name,width,height,sample_rate,duration",
            "-of",
            "json",
            str(path),
        ]
    )
    value = json.loads(raw)
    streams = value.get("streams", [])
    if not any(stream.get("codec_type") in {"video", "audio"} for stream in streams):
        raise RuleError("INVALID_MEDIA", "No audio/video streams")
    duration = float(value.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise RuleError("INVALID_MEDIA", "No positive media duration")
    return {
        "duration_ms": round(duration * 1000),
        "format": value.get("format", {}).get("format_name"),
        "streams": streams,
        "tool": "ffprobe",
        "model_called": False,
    }


def generate_probe_media(output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            binary("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x23694f:s=1280x720:r=25:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=1",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output),
        ]
    )
    return probe(output)


def decode_and_render(source, output):
    probe(source)
    run(
        [
            binary("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            "mov,matroska,webm,avi,wav,mp3,ogg,flac",
            "-i",
            str(Path(source).resolve()),
            "-t",
            "0.5",
            "-vf",
            "scale=1280:720",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(Path(output).resolve()),
        ]
    )
    return probe(output)
