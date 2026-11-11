"""Generate original synthetic footage, decode/render, and save actual tool evidence."""

import hashlib
import json
import subprocess
from pathlib import Path
from sw_media.tools import generate_probe_media, decode_and_render, binary

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "artifacts/phase-one/media"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "generated-source.mp4"
    output = folder / "rendered-preview.mp4"
    report = {
        "mode": "real_media_tools",
        "model_called": False,
        "provenance": {
            "source": "Project-generated FFmpeg color and sine sources",
            "third_party_footage": False,
            "scope": "technical decode/render probe; no model or creative quality evaluation",
        },
        "source": generate_probe_media(source),
        "render": decode_and_render(source, output),
        "tools": {
            name: subprocess.run(
                [binary(name), "-version"], capture_output=True, text=True, check=True
            ).stdout.splitlines()[0]
            for name in ["ffmpeg", "ffprobe"]
        },
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [source, output]},
    }
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
