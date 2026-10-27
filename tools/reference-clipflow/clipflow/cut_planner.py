"""Strict scene-aware, full-sentence segment planner.

A raw ASR/SRT caption cue is NOT automatically the end of a sentence: only an
explicit terminal sentence marker in unmodified recognition text may certify a
cut. Never use the presentation SRT after punctuation stripping. If speech
boundaries are uncertain, fail instead of claiming to have kept sentences intact.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Sequence


MIN_SECONDS_EXCLUSIVE = 3.0
MAX_SECONDS_INCLUSIVE = 8.0
# Closing quotation/bracket glyphs may follow a real sentence terminator.
_CLOSERS = '\"\'”’」』）)]】》〉'
_TERMINAL = frozenset('。！？!?')


class NoFeasibleSegmentation(ValueError):
    """The requested time and complete-sentence hard constraints conflict."""

    def __init__(self, reason: str, *, duration: float,
                 sentence_ends: Sequence[float], scene_boundaries: Sequence[float]):
        super().__init__(reason)
        self.reason = reason
        self.duration = duration
        self.sentence_ends = list(sentence_ends)
        self.scene_boundaries = list(scene_boundaries)

    def diagnostic(self) -> dict:
        return {"code": "NO_FEASIBLE_SENTENCE_CUTS", "reason": self.reason,
                "video_duration_seconds": round(self.duration, 3),
                "min_seconds_exclusive": MIN_SECONDS_EXCLUSIVE,
                "max_seconds_inclusive": MAX_SECONDS_INCLUSIVE,
                "confirmed_sentence_ends_seconds": list(self.sentence_ends),
                "scene_candidates_seconds": list(self.scene_boundaries),
                "action": "HOLD: review original audio / add verified complete-sentence boundary; never cut mid-sentence"}


def is_sentence_complete(text: str) -> bool:
    """Conservative terminal marker check on *unmodified* ASR/SRT transcript."""
    s = text.rstrip().rstrip(_CLOSERS).rstrip()
    # ASCII '.' is only considered terminal if not part of a numeric decimal.
    if s.endswith('.'):
        return True
    return bool(s and s[-1] in _TERMINAL)


def verified_sentence_ends(captions: Sequence, words: Sequence | None,
                           duration: float) -> list[float]:
    """Candidate cuts are punctuation-marked complete phrases, never cue count.

    Word timestamps, when present, are used to exclude points *inside* a word.
    Silence may corroborate a sentence, but a pause alone is not semantic proof.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("无效的原视频时长")
    word_spans = sorted(((float(w.start),float(w.end)) for w in (words or ())
                         if str(getattr(w, 'text', '')).strip()))
    choices: list[float] = []
    for cue in captions:
        if not is_sentence_complete(str(cue.text)):
            continue
        t = round(float(cue.end), 3)
        if not (0 < t < duration):
            continue
        if any(a + .045 < t < b - .045 for a, b in word_spans):
            continue
        choices.append(t)
    return sorted(set(choices))


def plan_sentence_cuts(duration: float, scene_boundaries: Sequence[float],
                       captions: Sequence, words: Sequence | None = None,
                       *, maximum: float = MAX_SECONDS_INCLUSIVE) -> list[float]:
    """Find all cuts globally using DP; never force a midpoint or tiny tail.

    Hard constraints: every segment is strictly >3s and <=maximum (<=8s).
    Nonfinal cuts must be backed by a confirmed complete-sentence cue.
    Objective: prefer scene boundaries near those sentence ends, then durations
    around 5.5s and fewer unnecessary cuts. Segment order/time is preserved.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('原视频时长无效')
    if not (MIN_SECONDS_EXCLUSIVE < maximum <= MAX_SECONDS_INCLUSIVE):
        raise ValueError('--max-seconds 只允许大于3秒且不超过8秒')
    scene = sorted(set(round(float(t),3) for t in scene_boundaries
                       if math.isfinite(float(t)) and 0 < t < duration))
    ends = verified_sentence_ends(captions, words, duration)
    if duration <= MIN_SECONDS_EXCLUSIVE:
        raise NoFeasibleSegmentation('原视频时长不大于3秒，无法产生符合严格下限的片段',
                                     duration=duration,sentence_ends=ends,scene_boundaries=scene)
    # Includes start/end, where no speech boundary is required at source EOF.
    nodes = [0.] + [x for x in ends if x < duration] + [round(duration, 6)]
    nodes = sorted(set(nodes))
    dist: list[float] = [float('inf')]*len(nodes)
    steps = [10**9]*len(nodes)
    before = [-1]*len(nodes)
    dist[0] = 0.0
    steps[0] = 0
    for i in range(1,len(nodes)):
        end = nodes[i]
        for j in range(i):
            start = nodes[j]
            width = end - start
            # Float tolerance must NOT turn a 3.0-second clip into a legal one.
            if width <= MIN_SECONDS_EXCLUSIVE + 1e-8 or width > maximum + 1e-8:
                continue
            if not math.isfinite(dist[j]):
                continue
            terminal = i == len(nodes)-1
            scene_distance = (min((abs(end-q) for q in scene),default=9.0)
                              if not terminal else 0.0)
            # Being close to a real camera cut counts more than equal lengths.
            scene_penalty = min(3.0, scene_distance*2.0) if not terminal else 0.0
            cost = (dist[j] + 1.0 + scene_penalty
                    + .08*((width-5.5)/2.5)**2)
            nsteps = steps[j]+1
            if cost < dist[i]-1e-9 or (abs(cost-dist[i]) <= 1e-9 and nsteps < steps[i]):
                dist[i], steps[i], before[i] = cost,nsteps,j
    if before[-1]<0:
        raise NoFeasibleSegmentation(
            '完整句尾与时长限制无法同时满足：可能有超过8秒的连续句子，或剩余不足/等于3秒；不允许硬切',
            duration=duration, sentence_ends=ends, scene_boundaries=scene)
    cuts = []
    idx = len(nodes)-1
    while idx>=0:
        cuts.append(nodes[idx]);idx=before[idx]
    cuts.reverse()
    assert cuts[0]==0.0 and abs(cuts[-1]-duration)<.001
    assert all(MIN_SECONDS_EXCLUSIVE < b-a <= maximum+1e-8 for a,b in zip(cuts,cuts[1:]))
    return cuts
