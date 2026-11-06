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

import gc
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
_DIARIZER_DEVICE = None


def _silence_nemo() -> None:
    """NeMo prints a banner and a progress bar for every internal step."""
    logging.getLogger("nemo_logging").setLevel(logging.ERROR)
    try:
        from nemo.utils import logging as nemo_logging

        nemo_logging.setLevel(logging.ERROR)
    except (ImportError, AttributeError):
        pass


def _nearest_anchor_mapping(timestamps_in_scales):
    """Drop-in for NeMo's `get_argmin_mat`, without its all-pairs grid.

    For every base-scale segment, NeMo finds the closest segment of each other
    scale by building a full (base x scale) distance matrix. On a 3-hour
    recording that is ~33,000 x 33,000 numbers per scale: 4+ GiB on the GPU
    (out of memory on 8 GiB) or ~13 GB of RAM on CPU (swapping for hours).
    A sorted lookup returns the same indices in a few MB.
    """
    import torch

    anchors = [torch.mean(ts, dim=1) for ts in timestamps_in_scales]
    base = anchors[-1]
    mappings = []
    for curr in anchors:
        order = torch.argsort(curr, stable=True)
        ordered = curr[order]
        last = ordered.shape[0] - 1
        right = torch.searchsorted(ordered, base).clamp(max=last)
        left = (right - 1).clamp(min=0)
        pick_right = (ordered[right] - base).abs() < (ordered[left] - base).abs()
        nearest = torch.where(pick_right, right, left)
        # Like argmin, a tie between equal anchors goes to the first of them.
        nearest = torch.searchsorted(ordered, ordered[nearest])
        mappings.append(order[nearest])
    return mappings


def _patch_nemo_scale_mapping() -> None:
    from nemo.collections.asr.data import audio_to_diar_label
    from nemo.collections.asr.parts.utils import offline_clustering, speaker_utils

    # The two other modules imported the function by name, so patch each copy.
    for module in (offline_clustering, speaker_utils, audio_to_diar_label):
        module.get_argmin_mat = _nearest_anchor_mapping


MSDD_WINDOWS_PER_PASS = int(os.getenv("H9_DIAR_WINDOWS", "64"))


def _chunk_msdd_inference(diarizer) -> None:
    """Feed MSDD its windows a group at a time instead of all at once.

    With split_infer on, NeMo cuts the recording into 50-step windows but then
    pushes every window through the network in one call, so memory grows with
    the recording: a 3-hour meeting asks for 13+ GiB. Windows are independent
    rows of that batch, so running them in groups gives the same predictions.
    """
    import torch

    msdd = diarizer.msdd_model
    whole = msdd.forward_infer

    def forward_infer(input_signal, input_signal_length, emb_vectors, targets):
        step = MSDD_WINDOWS_PER_PASS
        if targets is not None or input_signal.shape[0] <= step:
            return whole(input_signal, input_signal_length, emb_vectors, targets)
        preds, weights = [], []
        for start in range(0, input_signal.shape[0], step):
            part = slice(start, start + step)
            p, w = whole(input_signal[part], input_signal_length[part],
                         emb_vectors[part], None)
            preds.append(p)
            weights.append(w)
        return torch.cat(preds), torch.cat(weights)

    msdd.forward_infer = forward_infer


def default_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_diarizer(device: str):
    global _DIARIZER, _DIARIZER_DEVICE
    if _DIARIZER is not None and _DIARIZER_DEVICE != device:
        release()
    if _DIARIZER is None:
        from nemo.collections.asr.models.msdd_models import NeuralDiarizer
        from whisper_diarization.diarization.msdd.msdd import create_config

        _silence_nemo()
        _patch_nemo_scale_mapping()
        config = create_config()
        # NeMo also loads its VAD and speaker models through cfg.device.
        # Moving only the outer module leaves those models on CUDA.
        config.device = device
        _DIARIZER = NeuralDiarizer(cfg=config).to(device)
        _chunk_msdd_inference(_DIARIZER)
        _DIARIZER_DEVICE = device
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
    global _DIARIZER, _DIARIZER_DEVICE
    if _DIARIZER is None:
        return
    _DIARIZER = None
    _DIARIZER_DEVICE = None
    gc.collect()
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
    words: list[dict], speaker_ts: list[tuple[int, int, int]], labels: dict[int, str],
    gap_ms: int = 0,
) -> list[dict]:
    """Attach each transcribed word to a speaker, then merge into turns.

    Keep word-level speaker changes, including short replies inside a sentence.
    Sentence-level realignment used to move those replies to the other speaker.

    When `gap_ms` is set, a silence at least that long between two words
    always opens a new turn, and that turn records the silence in "gap_ms".
    Word times are used rather than Whisper's sentence blocks because one
    block can stretch over a whole coffee break.
    """
    if not words or not speaker_ts:
        return []

    from whisper_diarization.helpers import get_words_speaker_mapping

    mapping = get_words_speaker_mapping(words, speaker_ts, "start")

    turns: list[dict] = []
    for item in mapping:
        word = item["word"].strip()
        if not word:
            continue
        label = labels.get(item["speaker"], f"Person {item['speaker'] + 1}")
        silence = item["start_time"] - turns[-1]["end_ms"] if turns else 0
        is_break = gap_ms > 0 and silence >= gap_ms
        if turns and turns[-1]["speaker"] == label and not is_break:
            turns[-1]["text"] += " " + word
            turns[-1]["end_ms"] = item["end_time"]
        else:
            turns.append(
                {
                    "speaker": label,
                    "start_ms": item["start_time"],
                    "end_ms": item["end_time"],
                    "text": word,
                    "gap_ms": silence if is_break else 0,
                }
            )
    return turns


def silence_note(gap_start_ms: int, gap_ms: int, with_timestamps: bool) -> str:
    """The line marking a long stretch without speech, e.g. a break."""
    minutes = gap_ms / 60000
    span = f"{minutes:.0f} min" if minutes >= 1.5 else f"{gap_ms // 1000} s"
    prefix = f"[{format_time(gap_start_ms)}] " if with_timestamps else ""
    return f"{prefix}--- {span} without speech ---"


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
        if turn.get("gap_ms"):
            blocks.append(silence_note(turn["start_ms"] - turn["gap_ms"],
                                       turn["gap_ms"], with_timestamps))
        prefix = f"[{format_time(turn['start_ms'])}] " if with_timestamps else ""
        blocks.append(f"{prefix}{turn['speaker']}: {turn['text']}")
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")
