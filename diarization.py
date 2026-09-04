"""Split a transcript into speaker turns ("who said what").

Everything runs on this PC. The models come from NVIDIA NeMo: an MSDD
diarizer that groups voices using `titanet_large` voice fingerprints and a
`marblenet` voice-activity detector. They are downloaded once from NVIDIA's
public servers (no account, no key, no licence to accept) and cached under
%USERPROFILE%\\.cache\\torch\\NeMo. No audio ever leaves the machine.

The audio is diarized as a single whole file, never in chunks: cluster
numbers are only meaningful inside one diarization run, so "speaker 0" in
minute 5 and "speaker 0" in minute 40 are the same person only if both came
out of the same pass.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000

# Upper bound for the automatic speaker count. Only used when the caller does
# not pin an exact number.
MAX_SPEAKERS = int(os.getenv("H9_MAX_SPEAKERS", "8"))
BATCH_SIZE = int(os.getenv("H9_DIAR_BATCH", "24"))

# NeuralDiarizer takes ~20s to build, so keep one instance for the whole run.
_DIARIZER = None


def _silence_nemo() -> None:
    """NeMo prints a banner and a progress bar for every internal step."""
    logging.getLogger("nemo_logging").setLevel(logging.ERROR)
    try:
        from nemo.utils import logging as nemo_logging

        nemo_logging.setLevel(logging.ERROR)
    except (ImportError, AttributeError):
        pass


def default_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_diarizer(device: str):
    global _DIARIZER
    if _DIARIZER is None:
        from nemo.collections.asr.models.msdd_models import NeuralDiarizer
        from whisper_diarization.diarization.msdd.msdd import create_config

        _silence_nemo()
        _DIARIZER = NeuralDiarizer(cfg=create_config()).to(device)
    return _DIARIZER


def _save_wav(waveform: np.ndarray, path: Path) -> None:
    import torch
    import torchaudio

    torchaudio.save(
        str(path),
        torch.from_numpy(waveform).unsqueeze(0),
        SAMPLE_RATE,
        channels_first=True,
    )


def diarize_waveform(
    waveform: np.ndarray,
    num_speakers: int | None = None,
    device: str | None = None,
) -> list[tuple[int, int, int]]:
    """Return [(start_ms, end_ms, speaker_index), ...] sorted by start time.

    `waveform` is mono 16 kHz float32, as produced by
    faster_whisper.decode_audio. Pass `num_speakers` when the count is known
    (a two-person interview): pinning it stops the clustering from splitting
    one voice into two on a noisy recording.
    """
    from nemo.collections.asr.parts.utils.speaker_utils import rttm_to_labels

    device = device or default_device()
    model = _load_diarizer(device)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        wav_path = temp_path / "mono.wav"
        _save_wav(waveform, wav_path)

        manifest_path = temp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "audio_filepath": str(wav_path),
                    "offset": 0,
                    "duration": None,
                    "label": "infer",
                    "text": "-",
                    "num_speakers": num_speakers,
                    "rttm_filepath": None,
                    "uem_filepath": None,
                }
            ),
            encoding="utf-8",
        )

        model._initialize_configs(
            manifest_path=str(manifest_path),
            max_speakers=None if num_speakers else MAX_SPEAKERS,
            num_speakers=num_speakers,
            tmpdir=str(temp_path),
            batch_size=BATCH_SIZE,
            num_workers=0,
            verbose=False,
        )
        clustering = model.clustering_embedding.clus_diar_model._diarizer_params
        clustering.out_dir = str(temp_path)
        clustering.manifest_filepath = str(manifest_path)
        model.msdd_model.cfg.test_ds.manifest_filepath = str(manifest_path)
        model.diarize()

        rttm_path = temp_path / "pred_rttms" / "mono.rttm"
        if not rttm_path.is_file():
            return []

        turns: list[tuple[int, int, int]] = []
        for line in rttm_to_labels(str(rttm_path)):
            start, end, speaker = line.split()
            turns.append(
                (
                    int(float(start) * 1000),
                    int(float(end) * 1000),
                    int(speaker.split("_")[1]),
                )
            )

    turns.sort(key=lambda item: item[0])
    return turns


def release() -> None:
    """Free the diarizer's VRAM once every file has been processed."""
    global _DIARIZER
    if _DIARIZER is None:
        return
    _DIARIZER = None
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass


def person_labels(
    speaker_ts: list[tuple[int, int, int]], me_cluster: int | None = None
) -> dict[int, str]:
    """Map cluster numbers to "Person 1", "Person 2", ...

    Numbering follows who speaks first, so the labels stay stable if you
    re-run the same file. When `me_cluster` is given (your enrolled voice was
    recognised) that cluster is always Person 1.
    """
    order: list[int] = []
    for _start, _end, speaker in speaker_ts:
        if speaker not in order:
            order.append(speaker)
    if me_cluster is not None and me_cluster in order:
        order.remove(me_cluster)
        order.insert(0, me_cluster)
    return {speaker: f"Person {i}" for i, speaker in enumerate(order, start=1)}


def build_turns(
    words: list[dict], speaker_ts: list[tuple[int, int, int]], labels: dict[int, str]
) -> list[dict]:
    """Attach each transcribed word to a speaker, then merge into turns.

    get_realigned_ws_mapping_with_punctuation fixes the common failure where
    a speaker change lands in the middle of a sentence: it moves the whole
    sentence to whichever speaker owns most of it. It works off the
    punctuation Whisper already produced.
    """
    if not words or not speaker_ts:
        return []

    from whisper_diarization.helpers import (
        get_realigned_ws_mapping_with_punctuation,
        get_words_speaker_mapping,
    )

    mapping = get_words_speaker_mapping(words, speaker_ts, "start")
    mapping = get_realigned_ws_mapping_with_punctuation(mapping)

    turns: list[dict] = []
    for item in mapping:
        word = item["word"].strip()
        if not word:
            continue
        label = labels.get(item["speaker"], f"Person {item['speaker'] + 1}")
        if turns and turns[-1]["speaker"] == label:
            turns[-1]["text"] += " " + word
            turns[-1]["end_ms"] = item["end_time"]
        else:
            turns.append(
                {
                    "speaker": label,
                    "start_ms": item["start_time"],
                    "end_ms": item["end_time"],
                    "text": word,
                }
            )
    return turns


def format_time(milliseconds: int) -> str:
    total_seconds = max(int(milliseconds) // 1000, 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def write_turns(path: Path, turns: list[dict], with_timestamps: bool = False) -> None:
    blocks = []
    for turn in turns:
        prefix = f"[{format_time(turn['start_ms'])}] " if with_timestamps else ""
        blocks.append(f"{prefix}{turn['speaker']}: {turn['text']}")
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
