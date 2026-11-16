"""Suggest meeting boundaries and save reviewable transcript timing data.

This module uses only the standard library so the desktop window can read the
proposal without loading the transcription models.
"""

from __future__ import annotations

import json
from pathlib import Path

MIN_GAP_MS = 5_000
MIN_MEETING_MS = 10 * 60_000
MAX_SUGGESTIONS = 8
DEFAULT_BREAKS = 2


def clock(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def proposal_path(transcript: Path) -> Path:
    return transcript.with_suffix(".meetings.json")


def suggest(units: list[dict]) -> list[dict]:
    """Use pauses, strengthened by a change in the nearby group of voices."""
    if len(units) < 2:
        return []
    candidates = []
    for index in range(1, len(units)):
        before, after = units[index - 1], units[index]
        gap = after["start_ms"] - before["end_ms"]
        if gap < MIN_GAP_MS:
            continue
        before_voices = {u["speaker"] for u in units[:index]
                         if u.get("speaker") and u["end_ms"] >= before["end_ms"] - 120_000}
        after_voices = {u["speaker"] for u in units[index:]
                        if u.get("speaker") and u["start_ms"] <= after["start_ms"] + 120_000}
        changed = bool(before_voices and after_voices and not before_voices & after_voices)
        candidates.append({"index": index, "at_ms": after["start_ms"],
                           "gap_ms": gap, "voice_change": changed})

    # Prefer the strongest breaks when several occur close together.
    candidates.sort(key=lambda c: c["gap_ms"] + (5_000 if c["voice_change"] else 0), reverse=True)
    chosen = []
    for candidate in candidates:
        at = candidate["at_ms"]
        if at - units[0]["start_ms"] < MIN_MEETING_MS:
            continue
        if units[-1]["end_ms"] - at < MIN_MEETING_MS:
            continue
        if all(abs(at - other["at_ms"]) >= MIN_MEETING_MS for other in chosen):
            chosen.append(candidate)
            if len(chosen) == MAX_SUGGESTIONS:
                break
    preferred = {candidate["index"] for candidate in chosen[:DEFAULT_BREAKS]}
    for candidate in chosen:
        candidate["default"] = candidate["index"] in preferred
    return sorted(chosen, key=lambda c: c["index"])


def save(transcript: Path, units: list[dict], timestamps: bool,
         silence_note_ms: int) -> int:
    candidates = suggest(units)
    path = proposal_path(transcript)
    if not candidates:
        path.unlink(missing_ok=True)
        return 0
    data = {"version": 1, "source": transcript.name, "timestamps": timestamps,
            "silence_note_ms": silence_note_ms, "units": units,
            "candidates": candidates}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return len(candidates)


def render(units: list[dict], timestamps: bool, silence_note_ms: int) -> str:
    blocks = []
    previous = None
    for unit in units:
        gap = unit["start_ms"] - previous["end_ms"] if previous else 0
        if previous and silence_note_ms and gap >= silence_note_ms:
            span = f"{gap / 60_000:.0f} min" if gap >= 90_000 else f"{gap // 1000} s"
            prefix = f"[{clock(previous['end_ms'])}] " if timestamps else ""
            blocks.append(f"{prefix}--- {span} without speech ---")
        # Same layout as diarization.write_turns: header line, then the text.
        header = f"[{clock(unit['start_ms'])}] " if timestamps else ""
        header += unit.get("speaker") or ""
        text = unit["text"].strip()
        blocks.append(f"{header.rstrip()}\n{text}" if header.strip() else text)
        previous = unit
    return "\n\n".join(blocks) + ("\n" if blocks else "")
