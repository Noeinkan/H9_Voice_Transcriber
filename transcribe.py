"""Batch-transcribe M4A files from input/ to plain TXT in output/."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("BUZZ_REDUCE_GPU_MEMORY", "true")

from buzz.transcriber.file_transcriber import write_output
from buzz.transcriber.transcriber import OutputFormat, Segment

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
WORK_DIR = ROOT / "_work"
LOG_FILE = ROOT / "transcripts.log"
MODEL_DIR = ROOT / "models" / "large-v3"

SEGMENT_SECONDS = 30 * 60
HF_BASE = "https://huggingface.co/Systran/faster-whisper-large-v3/resolve/main"
SMALL_FILES = ("config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json")
MODEL_BIN = "model.bin"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB


def log(message: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def model_is_ready(model_dir: Path = MODEL_DIR) -> bool:
    model_bin = model_dir / MODEL_BIN
    return model_bin.is_file() and model_bin.stat().st_size > 500_000_000


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "H9-Voice-Transcriber/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    dest.write_bytes(data)
    log(f"  saved {dest.name} ({len(data) / 1024:.0f} KB)")


def _download_large_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    downloaded = partial.stat().st_size if partial.is_file() else 0

    headers = {"User-Agent": "H9-Voice-Transcriber/1.0"}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"
        log(f"  resuming {MODEL_BIN} from {downloaded / 1e9:.2f} GB")

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length", 0))
        if response.status == 206 and downloaded > 0:
            total += downloaded
        elif downloaded > 0 and response.status == 200:
            downloaded = 0
            partial.unlink(missing_ok=True)

        mode = "ab" if downloaded > 0 else "wb"
        last_logged = downloaded
        with partial.open(mode) as handle:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded - last_logged >= 100 * 1024 * 1024:
                    if total:
                        log(f"  {downloaded / 1e9:.2f} / {total / 1e9:.2f} GB ({downloaded * 100 / total:.0f}%)")
                    else:
                        log(f"  {downloaded / 1e9:.2f} GB downloaded")
                    last_logged = downloaded

    partial.replace(dest)
    log(f"  saved {MODEL_BIN} ({dest.stat().st_size / 1e9:.2f} GB)")


def download_model(model_dir: Path = MODEL_DIR) -> Path:
    if model_is_ready(model_dir):
        size_gb = (model_dir / MODEL_BIN).stat().st_size / (1024**3)
        log(f"Model already present ({size_gb:.1f} GB)")
        return model_dir

    log("Downloading large-v3 model files into models/large-v3/")
    log("model.bin is ~3 GB — progress updates every 100 MB.")

    for name in SMALL_FILES:
        dest = model_dir / name
        if dest.is_file() and dest.stat().st_size > 0:
            log(f"  skip {name} (already exists)")
            continue
        log(f"  downloading {name}...")
        _download_file(f"{HF_BASE}/{name}", dest)

    model_bin = model_dir / MODEL_BIN
    if not model_is_ready(model_dir):
        log(f"  downloading {MODEL_BIN}...")
        try:
            _download_large_file(f"{HF_BASE}/{MODEL_BIN}", model_bin)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Download failed (HTTP {exc.code}): {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Download failed: {exc.reason}") from exc

    if not model_is_ready(model_dir):
        raise RuntimeError("model.bin is missing or incomplete after download")

    size_gb = model_bin.stat().st_size / (1024**3)
    log(f"Model ready at {model_dir} ({size_gb:.1f} GB)")
    return model_dir


def ensure_model() -> Path:
    return download_model(MODEL_DIR)


def run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def probe_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return float(result.stdout.strip())


def split_audio(source: Path, dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    pattern = dest_dir / f"{source.stem}_part%03d.m4a"
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-f",
            "segment",
            "-segment_time",
            str(SEGMENT_SECONDS),
            "-c",
            "copy",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
    )
    parts = sorted(dest_dir.glob(f"{source.stem}_part*.m4a"))
    if not parts:
        raise RuntimeError(f"No segments created for {source.name}")
    return parts


def transcribe_file(audio_path: Path, model_dir: Path) -> list[Segment]:
    from buzz import cuda_setup  # noqa: F401
    import faster_whisper
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "int8_float16" if device == "cuda" else "int8"
    log(f"  loading model on {device}...")

    model = faster_whisper.WhisperModel(
        str(model_dir),
        device=device,
        compute_type=compute_type,
    )
    log(f"  transcribing {audio_path.name}...")
    whisper_segments, _info = model.transcribe(str(audio_path), language=None, task="transcribe")
    return [
        Segment(
            start=int(segment.start * 1000),
            end=int(segment.end * 1000),
            text=segment.text,
        )
        for segment in whisper_segments
    ]


def should_skip(source: Path, output: Path) -> bool:
    return output.exists() and output.stat().st_mtime >= source.stat().st_mtime


def transcribe_one(source: Path, model_dir: Path) -> None:
    output = OUTPUT_DIR / f"{source.stem}.txt"
    if should_skip(source, output):
        log(f"SKIP {source.name} (output is up to date)")
        return

    log(f"START {source.name}")
    duration = probe_duration_seconds(source)
    log(f"  duration: {duration / 60:.1f} min")

    if duration > SEGMENT_SECONDS:
        segment_dir = WORK_DIR / source.stem
        if segment_dir.exists():
            shutil.rmtree(segment_dir)
        parts = split_audio(source, segment_dir)
        log(f"  split into {len(parts)} segment(s)")
        all_segments: list[Segment] = []
        offset_ms = 0
        for index, part in enumerate(parts, start=1):
            log(f"  segment {index}/{len(parts)}: {part.name}")
            segments = transcribe_file(part, model_dir)
            for segment in segments:
                all_segments.append(
                    Segment(
                        start=segment.start + offset_ms,
                        end=segment.end + offset_ms,
                        text=segment.text,
                        translation=segment.translation,
                    )
                )
            offset_ms += int(probe_duration_seconds(part) * 1000)
        shutil.rmtree(segment_dir, ignore_errors=True)
    else:
        all_segments = transcribe_file(source, model_dir)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_output(str(output), all_segments, OutputFormat.TXT)
    log(f"DONE  {source.name} -> {output.name}")


def main() -> int:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sources = sorted(INPUT_DIR.glob("*.m4a"))
    if not sources:
        log("No .m4a files found in input/. Drop files there and run again.")
        return 0

    try:
        import torch

        if torch.cuda.is_available():
            log(f"GPU: {torch.cuda.get_device_name(0)}")
        else:
            log("WARNING: CUDA not available, transcription will use CPU (much slower)")
    except ImportError:
        log("WARNING: torch not installed")

    model_dir = ensure_model()

    for source in sources:
        try:
            transcribe_one(source, model_dir)
        except Exception as exc:
            log(f"ERROR {source.name}: {exc}")
            return 1

    log("All files processed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
