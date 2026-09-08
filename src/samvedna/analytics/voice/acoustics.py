"""What the voice is doing, measured in units somebody can check.

Six features, each with an explicit reference band and a *graded* divergence in
0..1 rather than a threshold that fires. The difference matters: a threshold
table makes a marginal exceedance read exactly like a dramatic one, and hides
the fact that the thresholds were chosen to make a demo fire.

**These bands are documented, adjustable, and NOT clinically validated.** They
encode direction and rough scale from the speech literature and nothing more.
That is why the voice domain is tiered T3 in `config/weights.py` — the same tier
as an opt-in wearable trend — and why voice alone can never clear the evidence
gate. A single T3 domain scores 0.183 against a 0.65 threshold, by construction.

Implemented in numpy alone. Praat via parselmouth would be more accurate, and it
is a native dependency the recipient of this archive would have to go and
install, which the transfer requirement rules out. The trade is stated rather
than hidden: `f0_hz` here is an autocorrelation estimate and will make octave
errors on creaky voice where Praat would not.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "AcousticFrame",
    "Band",
    "BANDS",
    "analyse",
    "Evidence",
    "SAMPLE_RATE",
]

SAMPLE_RATE = 16_000
# Human speech F0 sits inside this range; anything outside is an artefact.
F0_MIN_HZ, F0_MAX_HZ = 70.0, 350.0
# A window shorter than this cannot carry a reliable F0 estimate.
MIN_WINDOW_S = 0.6
# Energy below this fraction of the window peak counts as silence.
SILENCE_FLOOR = 0.08


@dataclass(frozen=True, slots=True)
class Band:
    """A reference band for one feature, and which way is notable.

    `normal` is where unremarkable conversational speech sits; `notable` is where
    the feature is clearly outside that. Divergence ramps linearly between them
    and saturates, so a marginal exceedance stays marginal.
    """

    feature: str
    normal: float
    notable: float
    weight: float
    label: str

    @property
    def direction(self) -> str:
        return "above" if self.notable > self.normal else "below"

    def divergence(self, value: float) -> float:
        span = self.notable - self.normal
        if span == 0:
            return 0.0
        return max(0.0, min((value - self.normal) / span, 1.0))

    def describe(self, value: float) -> str:
        return f"{self.label} {value:.3g} ({self.direction} {self.normal:g})"


# Expressed in measured units, not invented 0..1 scores, so the numbers an
# officer or clinician sees are the numbers the signal actually produced.
BANDS: tuple[Band, ...] = (
    # Laryngeal tension raises cycle-to-cycle perturbation.
    Band("jitter_local", 0.010, 0.030, 0.20, "pitch perturbation"),
    Band("shimmer_local", 0.040, 0.110, 0.16, "amplitude perturbation"),
    # Breathy or tearful speech carries more noise relative to harmonics.
    Band("hnr_db", 18.0, 7.0, 0.18, "harmonic-to-noise ratio"),
    # A narrow F0 range is the classic low-mood prosody.
    Band("f0_range_semitones", 8.0, 2.5, 0.20, "intonation range"),
    # Effort and pacing.
    Band("pause_ratio", 0.30, 0.70, 0.14, "pause fraction"),
    Band("speech_rate_sps", 3.6, 1.8, 0.12, "syllable rate"),
)
BAND_BY_FEATURE = {b.feature: b for b in BANDS}


@dataclass(frozen=True, slots=True)
class Evidence:
    """One feature's contribution, named so it can be disagreed with."""

    feature: str
    value: float
    band_normal: float
    band_notable: float
    divergence: float
    label: str

    def describe(self) -> str:
        return BAND_BY_FEATURE[self.feature].describe(self.value)


@dataclass(frozen=True, slots=True)
class AcousticFrame:
    """Measurements over one window of speech. Never the audio itself.

    The audio that produced this is discarded the moment the frame exists. There
    is no field it could be kept in, and `analyse` never returns it.
    """

    at_ms: int
    duration_s: float
    voiced_fraction: float
    f0_hz: float | None = None
    f0_range_semitones: float | None = None
    jitter_local: float | None = None
    shimmer_local: float | None = None
    hnr_db: float | None = None
    pause_ratio: float | None = None
    speech_rate_sps: float | None = None

    @property
    def trustworthy(self) -> bool:
        """Too little voiced speech to say anything. Withhold rather than guess."""
        return self.voiced_fraction >= 0.25 and self.duration_s >= MIN_WINDOW_S

    def available(self) -> dict[str, float]:
        return {
            b.feature: getattr(self, b.feature)
            for b in BANDS
            if getattr(self, b.feature, None) is not None
        }


def _frames(samples: np.ndarray, size: int, hop: int) -> np.ndarray:
    if len(samples) < size:
        return np.empty((0, size))
    count = 1 + (len(samples) - size) // hop
    idx = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    return samples[idx]


def _f0_track(samples: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """Autocorrelation F0 per 40 ms frame, plus per-frame voicing strength."""
    size, hop = int(0.040 * rate), int(0.010 * rate)
    frames = _frames(samples, size, hop)
    if frames.size == 0:
        return np.array([]), np.array([])

    window = np.hanning(size)
    lo = int(rate / F0_MAX_HZ)
    hi = min(int(rate / F0_MIN_HZ), size - 1)

    f0 = np.zeros(len(frames))
    strength = np.zeros(len(frames))
    for i, frame in enumerate(frames):
        centred = (frame - frame.mean()) * window
        energy = float(np.dot(centred, centred))
        if energy <= 1e-9:
            continue
        corr = np.correlate(centred, centred, mode="full")[size - 1:]
        if hi <= lo or hi >= len(corr):
            continue
        segment = corr[lo:hi]
        peak = int(np.argmax(segment))
        lag = lo + peak
        value = corr[lag] / corr[0] if corr[0] else 0.0
        # 0.30 keeps creaky and breathy voicing rather than only clean tones;
        # the cost is the occasional octave error, which is stated in the module
        # docstring rather than papered over.
        if value > 0.30 and lag > 0:
            f0[i] = rate / lag
            strength[i] = value
    return f0, strength


def _perturbation(f0: np.ndarray, samples: np.ndarray, rate: int) -> tuple[float, float]:
    """Jitter and shimmer from consecutive voiced periods.

    Local jitter is the mean absolute difference between consecutive periods
    divided by the mean period — the standard definition, so a synthetic pulse
    train built with a known perturbation recovers that figure.
    """
    voiced = f0[f0 > 0]
    if len(voiced) < 3:
        return 0.0, 0.0
    periods = 1.0 / voiced
    jitter = float(np.mean(np.abs(np.diff(periods))) / np.mean(periods))

    size, hop = int(0.040 * rate), int(0.010 * rate)
    frames = _frames(samples, size, hop)
    amps = np.array([float(np.abs(f).max()) for f in frames if np.abs(f).max() > 0])
    if len(amps) < 3:
        return jitter, 0.0
    shimmer = float(np.mean(np.abs(np.diff(amps))) / np.mean(amps))
    return jitter, shimmer


def _hnr(samples: np.ndarray, rate: int, strength: np.ndarray) -> float:
    """Harmonics-to-noise ratio in dB, from mean autocorrelation strength.

    Computed from voicing strength rather than gated behind a voiced-frame
    count. Gating it that way withholds HNR from exactly the noisy, breathy
    signals whose low HNR is the point.
    """
    voiced = strength[strength > 0]
    if len(voiced) == 0:
        return 0.0
    r = float(np.clip(np.mean(voiced), 1e-4, 0.9999))
    return float(10.0 * np.log10(r / (1.0 - r)))


def _pace(samples: np.ndarray, rate: int) -> tuple[float, float]:
    """Pause fraction and syllable rate from the energy envelope."""
    size, hop = int(0.025 * rate), int(0.010 * rate)
    frames = _frames(samples, size, hop)
    if frames.size == 0:
        return 0.0, 0.0
    energy = np.sqrt(np.mean(frames**2, axis=1))
    peak = float(energy.max())
    if peak <= 0:
        return 1.0, 0.0
    voiced = energy > peak * SILENCE_FLOOR
    pause_ratio = float(1.0 - voiced.mean())

    # Count energy peaks with a refractory gap, so one syllable is not counted
    # several times as the envelope wobbles across its top.
    smooth = np.convolve(energy, np.ones(5) / 5, mode="same")
    threshold = peak * 0.25
    refractory = int(0.09 / 0.010)
    peaks, last = 0, -refractory
    for i in range(1, len(smooth) - 1):
        if (
            smooth[i] > threshold
            and smooth[i] >= smooth[i - 1]
            and smooth[i] > smooth[i + 1]
            and i - last >= refractory
        ):
            peaks += 1
            last = i
    seconds = len(samples) / rate
    return pause_ratio, (peaks / seconds if seconds > 0 else 0.0)


def analyse(samples: np.ndarray, at_ms: int = 0, rate: int = SAMPLE_RATE) -> AcousticFrame:
    """One window of audio in, one frame of measurements out.

    The audio is not retained, not returned, and not referenced by the result.
    """
    samples = np.asarray(samples, dtype=np.float64).ravel()
    duration = len(samples) / rate
    if duration < MIN_WINDOW_S:
        return AcousticFrame(at_ms=at_ms, duration_s=duration, voiced_fraction=0.0)

    peak = float(np.abs(samples).max())
    if peak > 0:
        samples = samples / peak

    f0, strength = _f0_track(samples, rate)
    voiced_fraction = float((f0 > 0).mean()) if len(f0) else 0.0
    if voiced_fraction < 0.05:
        return AcousticFrame(
            at_ms=at_ms, duration_s=duration, voiced_fraction=voiced_fraction
        )

    voiced = f0[f0 > 0]
    median_f0 = float(np.median(voiced))
    # Interquartile range in semitones: robust to the octave errors an
    # autocorrelation tracker makes, where a min/max range would not be.
    q1, q3 = np.percentile(voiced, [25, 75])
    f0_range = float(12.0 * np.log2(q3 / q1)) if q1 > 0 else 0.0

    jitter, shimmer = _perturbation(f0, samples, rate)
    hnr = _hnr(samples, rate, strength)
    pause_ratio, rate_sps = _pace(samples, rate)

    return AcousticFrame(
        at_ms=at_ms,
        duration_s=duration,
        voiced_fraction=voiced_fraction,
        f0_hz=round(median_f0, 2),
        f0_range_semitones=round(f0_range, 3),
        jitter_local=round(jitter, 5),
        shimmer_local=round(shimmer, 5),
        hnr_db=round(hnr, 2),
        pause_ratio=round(pause_ratio, 3),
        speech_rate_sps=round(rate_sps, 3),
    )
