"""Isolated speech inference subprocess; only loads a predownloaded local model."""

import json
import sys
from importlib.metadata import version
import wave


def main():
    import numpy as np
    from faster_whisper import WhisperModel

    path, wav, language = sys.argv[1:]
    model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=2, local_files_only=True)
    # FFmpeg already decoded/resampled the file. Passing PCM avoids a second decoder.
    with wave.open(wav, "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError("Expected mono 16 kHz signed PCM")
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio, language=None if language == "auto" else language,
                                      beam_size=3, word_timestamps=True)
    payload = {
        "segments": [{"start": s.start, "end": s.end, "text": s.text,
                      "words": [{"start": w.start, "end": w.end, "text": w.word} for w in s.words or []]} for s in segments],
        "version": version("faster-whisper"), "language": info.language, "audio_ms": round(info.duration * 1000),
    }
    print(json.dumps(payload, ensure_ascii=True))


if __name__ == "__main__":
    main()
