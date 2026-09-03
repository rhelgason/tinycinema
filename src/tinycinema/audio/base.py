"""The audio sink interface and the playback clocks built on it.

The whole point of this module is `Clock.now()`. The player loop asks one
question every frame -- "what time is it in this movie?" -- and everything else
(waiting, dropping, the HUD) follows from the answer. Phase 1 answered it with a
wall clock. Phase 2 answers it with the audio device's actual playback position,
and nothing else in the loop had to change.

Why audio leads: people notice an audio glitch instantly and a dropped video
frame almost never. So audio plays uninterrupted and video chases it. Doing it
the other way round -- resampling audio to match video timing -- is both harder
and worse.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class AudioSink(Protocol):
    """Something that plays a media file's audio and can say where it is."""

    def start(self, position: float = 0.0) -> None: ...

    def anchor(self) -> tuple[float, float] | None:
        """(media position, perf_counter when it was observed), or None.

        Reporting *when* the observation was made, rather than just a bare
        position, is what lets the clock interpolate between reports. A sink
        that reports every 30ms would otherwise turn the timeline into a 30ms
        staircase, which is a third of a frame interval at 30fps.
        """
        ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool:
        """False once playback has finished or failed."""
        ...


class Clock:
    """A monotonic media timeline, pausable, that the video chases.

    The wall-clock implementation. `WallClock` is not a fallback so much as the
    correct answer when there is no audio: with nothing to sync against, elapsed
    real time *is* the timeline.
    """

    def __init__(self) -> None:
        self._origin = 0.0
        self._paused_at: float | None = None
        self._started = False

    def _rebase(self, position: float) -> None:
        """Move the wall-clock timeline to `position` without restarting anything.

        Deliberately *not* start(): subclasses override start() to (re)launch an
        audio process, so calling it from resume() would tear down and relaunch
        the audio device on every pause -- costing a fresh startup latency each
        time and desyncing the very thing we paused.
        """
        self._origin = time.perf_counter() - position
        self._paused_at = None
        self._started = True

    def start(self, position: float = 0.0) -> None:
        self._rebase(position)

    def now(self) -> float:
        if not self._started:
            return 0.0
        if self._paused_at is not None:
            return self._paused_at
        return time.perf_counter() - self._origin

    def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = self.now()

    def resume(self) -> None:
        if self._paused_at is not None:
            # Re-base rather than accumulating an offset, so a long pause cannot
            # leave the loop with a pile of debt to work off.
            self._rebase(self._paused_at)

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def stop(self) -> None:
        self._started = False

    @property
    def source(self) -> str:
        return "wall"


WallClock = Clock


class AudioClock(Clock):
    """A media timeline driven by an audio sink's real playback position.

    The sink reports its position intermittently -- every few frames of audio,
    not every video frame -- so between reports we extrapolate with the wall
    clock from the last known-good anchor. Each new report re-anchors, which
    corrects both the sink's startup latency and any long-run drift without the
    timeline ever jumping backwards during normal playback.
    """

    #: If the sink has not reported by now, assume it never will and fall back
    #: to the wall clock. Without this a silently-broken sink would freeze the
    #: video on frame one forever. Kept tight because every millisecond of it is
    #: a frozen first frame; real device warm-up is 100-300ms.
    FALLBACK_AFTER = 1.0

    def __init__(self, sink: AudioSink) -> None:
        super().__init__()
        self.sink = sink
        self._anchor: tuple[float, float] | None = None  # (media pos, perf_counter)
        self._start_position = 0.0
        self._started_at = 0.0
        self._fellback = False
        self._last_returned = float("-inf")
        self._anchor_floor = 0.0

    def start(self, position: float = 0.0) -> None:
        self._rebase(position)
        self._start_position = position
        self._started_at = time.perf_counter()
        self._anchor = None
        self._fellback = False
        self._last_returned = float("-inf")
        self._anchor_floor = time.perf_counter()
        self.sink.start(position)

    def now(self) -> float:
        if self._paused_at is not None:
            return self._paused_at
        if not self._started:
            return 0.0
        return self._monotonic(self._raw_now())

    def _raw_now(self) -> float:
        if self._fellback:
            # Committed to the wall clock. Re-entering the branch below would
            # re-base the origin on every single call and freeze the timeline.
            return super().now()

        now = time.perf_counter()
        fresh = self.sink.anchor()
        # Reject anything the sink observed before our last start/resume. A sink
        # that doesn't clear its own stale report on resume would otherwise hand
        # us a pre-pause observation and we'd extrapolate straight through the
        # whole pause.
        if fresh is not None and fresh[1] >= self._anchor_floor:
            self._anchor = fresh

        if self._anchor is not None:
            # Always interpolate from the anchor rather than returning the
            # reported value directly. The report describes where audio was when
            # the sink observed it, which is already in the past by the time we
            # read it -- returning it verbatim pins the timeline into a staircase
            # with steps the width of the sink's reporting interval.
            anchor_pos, anchor_at = self._anchor
            return anchor_pos + (now - anchor_at)

        # Nothing reported yet. Hold at the start position so video waits for
        # audio to actually begin -- that is what makes them start aligned.
        # But a sink that is already dead is never going to report, so don't
        # make the viewer stare at a frozen frame waiting for the timeout.
        if self.sink.active and now - self._started_at < self.FALLBACK_AFTER:
            return self._start_position

        self._fellback = True  # one-way door; see the guard at the top
        # Re-base the wall clock so the timeline continues smoothly from where
        # we were holding, instead of jumping forward by the whole timeout.
        self._rebase(self._start_position)
        return super().now()

    def _monotonic(self, value: float) -> float:
        """Never let the timeline run backwards.

        A late report can land behind where we had extrapolated to. Rewinding
        would make the player re-wait frames it already showed, so stall instead
        and let the timeline catch up naturally.
        """
        if value < self._last_returned:
            return self._last_returned
        self._last_returned = value
        return value

    def pause(self) -> None:
        super().pause()
        self.sink.pause()

    def resume(self) -> None:
        if self._paused_at is None:
            return
        resume_at = self._paused_at
        super().resume()
        self._started_at = time.perf_counter()
        self._anchor = None
        self._start_position = resume_at
        self._last_returned = float("-inf")
        self._anchor_floor = time.perf_counter()
        self.sink.resume()

    def stop(self) -> None:
        super().stop()
        self.sink.stop()

    @property
    def fell_back(self) -> bool:
        """True if the audio sink never reported and we gave up on it."""
        return self._fellback

    @property
    def source(self) -> str:
        return "wall*" if self._fellback else "audio"


class NullSink:
    """No audio. Keeps the player's code path uniform."""

    def start(self, position: float = 0.0) -> None:
        pass

    def anchor(self) -> tuple[float, float] | None:
        return None

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def stop(self) -> None:
        pass

    @property
    def active(self) -> bool:
        return False
