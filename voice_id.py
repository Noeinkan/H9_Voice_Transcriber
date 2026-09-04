"""Recognise your own voice, so you are always Person 1.

Diarization can tell two voices apart but has no idea whose they are. This
module stores one voice fingerprint of you (a 192-number `titanet_large`
embedding, taken from a 30-second sample you record once) and compares it
against each speaker cluster found in a recording.

Nothing here needs an account or a network call after the model is cached,
and the stored fingerprint is a vector, not audio: it cannot be played back.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
VOICE_DIR = ROOT / "voice"
EMBEDDING_FILE = VOICE_DIR / "me.npy"
SAMPLE_FILE = VOICE_DIR / "me.wav"

SAMPLE_RATE = 16000

# Per-cluster audio budget when matching: the longest segments, up to a
# minute. More than that costs time without changing the answer.
MATCH_SECONDS = 60
MIN_SEGMENT_MS = 1500

# Cosine similarity of two titanet_large embeddings: same speaker usually
# lands well above 0.5, different speakers below 0.3. We also require the
# winner to beat the runner-up by a margin, otherwise the recording is too
# ambiguous to label and we fall back to speaking order.
MATCH_MIN = float(os.getenv("H9_VOICE_MATCH_MIN", "0.35"))
MATCH_MARGIN = float(os.getenv("H9_VOICE_MATCH_MARGIN", "0.06"))

_MODEL = None


def _load_model(device: str):
    global _MODEL
    if _MODEL is None:
        from nemo.collections.asr.models import EncDecSpeakerLabelModel

        _MODEL = EncDecSpeakerLabelModel.from_pretrained("titanet_large").to(device)
        _MODEL.eval()
    return _MODEL


def default_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def embed_waveform(waveform: np.ndarray, device: str | None = None) -> np.ndarray:
    """Return the L2-normalised voice fingerprint of a mono 16 kHz waveform."""
    import torch
    import torchaudio

    device = device or default_device()
    model = _load_model(device)

    with tempfile.TemporaryDirectory() as temp_dir:
        wav_path = Path(temp_dir) / "sample.wav"
        torchaudio.save(
            str(wav_path),
            torch.from_numpy(np.ascontiguousarray(waveform)).unsqueeze(0),
            SAMPLE_RATE,
            channels_first=True,
        )
        embedding = model.get_embedding(str(wav_path)).squeeze()

    vector = embedding.detach().cpu().numpy().astype(np.float32)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def save_enrollment(vector: np.ndarray) -> Path:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(EMBEDDING_FILE, vector)
    return EMBEDDING_FILE


def load_enrollment() -> np.ndarray | None:
    if not EMBEDDING_FILE.is_file():
        return None
    return np.load(EMBEDDING_FILE)


def _cluster_waveform(
    waveform: np.ndarray, speaker_ts: list[tuple[int, int, int]], speaker: int
) -> np.ndarray:
    """Concatenate up to MATCH_SECONDS of this speaker's longest segments."""
    segments = [
        (start, end)
        for start, end, spk in speaker_ts
        if spk == speaker and (end - start) >= MIN_SEGMENT_MS
    ]
    if not segments:
        segments = [(start, end) for start, end, spk in speaker_ts if spk == speaker]
    segments.sort(key=lambda item: item[1] - item[0], reverse=True)

    pieces: list[np.ndarray] = []
    collected_ms = 0
    for start, end in segments:
        pieces.append(waveform[int(start * SAMPLE_RATE / 1000) : int(end * SAMPLE_RATE / 1000)])
        collected_ms += end - start
        if collected_ms >= MATCH_SECONDS * 1000:
            break
    return np.concatenate(pieces) if pieces else np.array([], dtype=np.float32)


def identify_me(
    waveform: np.ndarray,
    speaker_ts: list[tuple[int, int, int]],
    device: str | None = None,
) -> tuple[int | None, dict[int, float]]:
    """Return (cluster that is you, similarity score per cluster).

    The cluster is None when no voice was enrolled, when nothing resembles
    you closely enough, or when two clusters are too close to call.
    """
    enrolled = load_enrollment()
    if enrolled is None or not speaker_ts:
        return None, {}

    device = device or default_device()
    scores: dict[int, float] = {}
    for speaker in sorted({spk for _s, _e, spk in speaker_ts}):
        audio = _cluster_waveform(waveform, speaker_ts, speaker)
        if audio.size < SAMPLE_RATE:  # under a second of speech, not judgeable
            continue
        scores[speaker] = float(np.dot(embed_waveform(audio, device), enrolled))

    if not scores:
        return None, {}

    best = max(scores, key=lambda spk: scores[spk])
    runner_up = max(
        (score for spk, score in scores.items() if spk != best), default=None
    )
    if scores[best] < MATCH_MIN:
        return None, scores
    if runner_up is not None and (scores[best] - runner_up) < MATCH_MARGIN:
        return None, scores
    return best, scores


def release() -> None:
    """Free the fingerprint model's VRAM."""
    global _MODEL
    if _MODEL is None:
        return
    _MODEL = None
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass
