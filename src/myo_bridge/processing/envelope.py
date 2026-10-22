"""Per-channel RMS envelope with an O(1) running-sum ring buffer."""

from __future__ import annotations

import math


class RmsEnvelope:
    def __init__(self, channels: int = 8, window_samples: int = 10) -> None:
        self.channels = channels
        self.set_window(window_samples)

    def set_window(self, window_samples: int) -> None:
        n = max(1, int(window_samples))
        self.window = n
        self._buf = [[0.0] * n for _ in range(self.channels)]
        self._sum = [0.0] * self.channels
        self._idx = 0
        self._count = 0

    def push(self, sample) -> None:
        """sample: 8 normalised values (-1..1)."""
        i = self._idx
        buf, s = self._buf, self._sum
        for ch in range(self.channels):
            v = sample[ch]
            sq = v * v
            s[ch] += sq - buf[ch][i]
            buf[ch][i] = sq
        self._idx = (i + 1) % self.window
        if self._count < self.window:
            self._count += 1

    @property
    def values(self) -> tuple[float, ...]:
        n = self._count or 1
        return tuple(math.sqrt(max(0.0, s / n)) for s in self._sum)

    @property
    def mean(self) -> float:
        v = self.values
        return sum(v) / len(v)

    def reset(self) -> None:
        self.set_window(self.window)
