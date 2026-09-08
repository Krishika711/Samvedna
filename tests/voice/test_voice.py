"""Phase 17: voice concordance, and the case a cue-anchored engine misses.

The design question that shaped this suite: what happens to somebody who is in
real difficulty and never says they are fine? A purely cue-driven engine reports
nothing about them, which is the wrong kind of silence — so there are two paths
in, and both are tested here.
"""
from __future__ import annotations

import numpy as np
import pytest

from samvedna.analytics.voice.acoustics import BANDS, SAMPLE_RATE, AcousticFrame, analyse
from samvedna.analytics.voice.concordance import (
    MIN_CONTRIBUTORS,
    STRAIN_MIN_CONTRIBUTORS,
    STRAIN_MIN_COVERAGE,
    assess,
    sustained_strain,
)
from samvedna.analytics.voice.minimisation import detect
from samvedna.analytics.voice.session import VoiceSession, acute_in

STRAINED = {
    "f0_range_semitones": 3.0, "jitter_local": 0.026, "shimmer_local": 0.095,
    "hnr_db": 9.0, "pause_ratio": 0.60, "speech_rate_sps": 2.1,
}


def frame(at_ms: int = 0, **kw) -> AcousticFrame:
    base = {
        "at_ms": at_ms, "duration_s": 2.0, "voiced_fraction": 0.8, "f0_hz": 140.0,
        "f0_range_semitones": 7.0, "jitter_local": 0.010, "shimmer_local": 0.040,
        "hnr_db": 18.0, "pause_ratio": 0.30, "speech_rate_sps": 3.6,
    }
    base.update(kw)
    return AcousticFrame(**base)


def tone(hz: float, seconds: float = 2.0, jitter: float = 0.0) -> np.ndarray:
    """A synthetic voiced tone with a known F0, and optionally known jitter."""
    n = int(seconds * SAMPLE_RATE)
    if jitter == 0.0:
        t = np.arange(n) / SAMPLE_RATE
        return np.sin(2 * np.pi * hz * t)
    # Alternating periods of T(1±d) give a defined local jitter of 2d.
    out, phase, base = [], 0.0, 1.0 / hz
    flip = 1
    while len(out) < n:
        period = base * (1 + flip * jitter / 2)
        count = max(1, int(period * SAMPLE_RATE))
        out.extend(np.sin(2 * np.pi * np.arange(count) / count + phase))
        flip *= -1
    return np.array(out[:n])


# ----------------------------------------------------------------- acoustics --
def test_f0_is_recovered_from_a_synthetic_tone():
    for hz in (110.0, 150.0, 220.0):
        got = analyse(tone(hz)).f0_hz
        assert got == pytest.approx(hz, rel=0.05), f"{hz} Hz read as {got}"


def test_a_window_too_short_to_measure_returns_nothing_rather_than_a_guess():
    f = analyse(tone(150.0, seconds=0.2))
    assert not f.trustworthy
    assert f.f0_hz is None


def test_silence_produces_no_f0():
    f = analyse(np.zeros(SAMPLE_RATE * 2))
    assert f.f0_hz is None
    assert f.voiced_fraction == 0.0


def test_white_noise_is_not_read_as_voiced_speech():
    rng = np.random.default_rng(7)
    f = analyse(rng.normal(size=SAMPLE_RATE * 2))
    assert f.voiced_fraction < 0.5


def test_added_noise_lowers_the_harmonic_to_noise_ratio():
    rng = np.random.default_rng(3)
    clean = analyse(tone(150.0)).hnr_db
    noisy = analyse(tone(150.0) + rng.normal(scale=0.5, size=SAMPLE_RATE * 2)).hnr_db
    assert noisy < clean


def test_the_frame_cannot_carry_audio():
    """No audio is ever stored. There is no field it could be kept in."""
    fields = set(AcousticFrame.__dataclass_fields__)
    for forbidden in ("samples", "audio", "pcm", "waveform", "buffer", "recording"):
        assert forbidden not in fields


def test_every_band_is_expressed_in_measured_units_not_a_score():
    for band in BANDS:
        assert band.normal != band.notable
        assert 0.0 < band.weight <= 1.0
        assert band.label and not band.label.isupper()


def test_divergence_saturates_so_a_marginal_exceedance_stays_marginal():
    band = next(b for b in BANDS if b.feature == "jitter_local")
    assert band.divergence(band.normal) == 0.0
    assert band.divergence(band.notable) == 1.0
    assert band.divergence(band.notable * 10) == 1.0
    assert 0.4 < band.divergence((band.normal + band.notable) / 2) < 0.6


# -------------------------------------------------------------- minimisation --
def test_a_minimising_phrase_is_detected():
    assert detect("I'm fine, sir.")[0].kind == "wellbeing"


def test_negation_cancels_a_cue():
    assert detect("I'm not fine at all.") == ()


def test_negation_does_not_leak_across_a_contrast_clause():
    """'I haven't slept but I'll manage' is a textbook minimisation, and the
    'but' is precisely what makes it one. Splitting only on sentence punctuation
    let 'haven't' reach across the clause and cancel a cue it had nothing to do
    with."""
    match = detect("I haven't slept but I'll manage.")
    assert match and match[0].kind == "coping"


def test_a_hedge_raises_confidence():
    plain = detect("I'm fine.")[0].confidence
    hedged = detect("I'm fine, mostly.")[0].confidence
    assert hedged > plain


def test_plain_speech_produces_no_cue():
    for line in ("The roster has been very hard.", "We finished the patrol on time."):
        assert detect(line) == ()


def test_one_finding_per_utterance():
    """Several cues in one sentence are one claim said several ways."""
    assert len(detect("I'm fine, it's nothing, I'm managing.")) == 1


# ------------------------------------------------- concordance (cue-anchored) --
def test_a_minimising_claim_over_a_strained_voice_raises_a_gap():
    result = assess(detect("I'm fine, sir.")[0], [frame(**STRAINED)])
    assert result.raised
    assert result.divergence > 0.4
    assert len(result.evidence) >= MIN_CONTRIBUTORS


def test_a_minimising_claim_over_a_calm_voice_raises_nothing():
    assert not assess(detect("I'm fine, sir.")[0], [frame()]).raised


def test_one_diverging_feature_is_never_enough():
    """The corroboration floor, one layer below the evidence gate's breadth."""
    result = assess(detect("I'm fine.")[0], [frame(jitter_local=0.028)])
    assert not result.raised
    assert "at least" in result.reason


def test_a_barely_moved_feature_does_not_count_as_corroboration():
    """Any non-zero divergence used to count, so a feature a fifth of the way
    out of band corroborated as loudly as one at the far end."""
    result = assess(detect("I'm fine.")[0], [frame(jitter_local=0.028,
                                                   f0_range_semitones=7.0)])
    assert not result.raised


def test_no_claim_means_nothing_to_measure_on_the_anchored_path():
    assert not assess(None, [frame(**STRAINED)]).raised


def test_untrustworthy_frames_are_not_measured():
    thin = frame(voiced_fraction=0.05, **STRAINED)
    assert not assess(detect("I'm fine.")[0], [thin]).raised


def test_the_description_names_the_sentence_and_the_measurements():
    result = assess(detect("I'm fine, sir.")[0], [frame(**STRAINED)])
    text = result.describe()
    assert "I'm fine, sir." in text
    assert any(b.label in text for b in BANDS)
    assert "%" not in text, "no confidence percentage — PART 14 forbids it"
    assert "diagnos" not in text.lower()


# ------------------------- sustained strain (the case a cue bank would miss) --
def test_a_person_in_difficulty_who_never_claims_to_be_fine_is_still_seen():
    """The hole in a purely cue-anchored design, and the reason this path exists.

    Somebody says 'the roster has been manageable' — a claim no cue bank
    contains — in a voice that is audibly strained throughout. The anchored path
    reports nothing. This one does not.
    """
    session = [frame(i * 2000, **STRAINED) for i in range(8)]
    assert not assess(None, session).raised, "the anchored path is blind here"

    strain = sustained_strain(session)
    assert strain.raised
    assert strain.divergence > 0.5
    assert strain.coverage >= STRAIN_MIN_COVERAGE
    assert "No minimising claim was made" in strain.describe()


def test_a_calm_voice_across_a_whole_sitting_raises_nothing():
    assert not sustained_strain([frame(i * 2000) for i in range(10)]).raised


def test_strain_in_only_part_of_a_sitting_is_not_a_finding_about_a_person():
    """A hard stretch inside a conversation is not the same as a strained voice."""
    mixed = (
        [frame(i * 2000) for i in range(5)]
        + [frame(i * 2000, **STRAINED) for i in range(5, 8)]
        + [frame(i * 2000) for i in range(8, 13)]
    )
    assert not sustained_strain(mixed).raised


def test_the_unanchored_path_needs_more_features_than_the_anchored_one():
    """Without a claim to anchor to, two correlated measurements are much easier
    to hit by chance."""
    assert STRAIN_MIN_CONTRIBUTORS > MIN_CONTRIBUTORS

    two_features = [
        frame(i * 2000, jitter_local=0.028, hnr_db=9.0) for i in range(8)
    ]
    assert assess(detect("I'm fine.")[0], two_features).raised
    assert not sustained_strain(two_features).raised


def test_a_short_sitting_cannot_establish_that_anything_held():
    assert not sustained_strain([frame(i * 2000, **STRAINED) for i in range(3)]).raised


# ------------------------------------------------------------------- session --
def test_a_session_holds_measurements_and_never_audio():
    fields = set(VoiceSession.__dataclass_fields__)
    for forbidden in ("audio", "samples", "pcm", "recording", "waveform"):
        assert forbidden not in fields


def test_closing_a_session_destroys_the_transcript():
    session = VoiceSession(pid="p", unit_id="U")
    session.feed_utterance(0, "I'm fine, sir.")
    assert session.transcript_for_clinician()
    session.close()
    assert session.transcript_for_clinician() == ()


def test_a_closed_session_refuses_more_input():
    session = VoiceSession(pid="p", unit_id="U")
    session.close()
    with pytest.raises(RuntimeError):
        session.feed_utterance(0, "anything")
    with pytest.raises(RuntimeError):
        session.feed_audio(frame())


def test_the_deviation_that_leaves_a_session_carries_no_words():
    session = VoiceSession(pid="p", unit_id="U")
    for i in range(8):
        session.feed_audio(frame(i * 2000, **STRAINED))
    for i, line in enumerate(["I'm fine.", "It's nothing.", "I'm managing."]):
        session.feed_utterance(i * 2500, line)

    deviation = session.as_deviation()
    assert deviation is not None
    blob = str(deviation)
    for word in ("fine", "nothing", "managing", "quote"):
        assert word not in blob


def test_voice_is_tiered_t3_and_can_never_escalate_anybody_alone():
    """The bands are not clinically validated, so voice corroborates a case and
    can never make one. A single T3 domain scores 0.183 against 0.65."""
    from tests.conftest import case

    from samvedna.core.gates import evidence

    session = VoiceSession(pid="p", unit_id="U")
    for i in range(8):
        session.feed_audio(frame(i * 2000, **STRAINED))
    for i, line in enumerate(["I'm fine.", "It's nothing.", "I'm managing."]):
        session.feed_utterance(i * 2500, line)

    deviation = session.as_deviation()
    assert deviation.tier == "T3"
    assert evidence(case(deviation)).value < 0.65


def test_one_sitting_cannot_clear_the_persistence_gate():
    """A session is a point in time, not a sustained pattern."""
    from tests.conftest import case

    from samvedna.core.gates import persistence

    session = VoiceSession(pid="p", unit_id="U")
    for i in range(8):
        session.feed_audio(frame(i * 2000, **STRAINED))
    for i, line in enumerate(["I'm fine.", "It's nothing.", "I'm managing."]):
        session.feed_utterance(i * 2500, line)

    assert not persistence(case(session.as_deviation())).passed


def test_a_session_with_nothing_in_it_produces_no_deviation():
    session = VoiceSession(pid="p", unit_id="U")
    for i in range(8):
        session.feed_audio(frame(i * 2000))
    session.feed_utterance(0, "The patrol went fine.")
    assert session.as_deviation() is None


# ------------------------------------------------------- the duty of care --
def test_acute_disclosure_in_speech_is_heard():
    """Capturing speech invites unstructured psychological disclosure, which
    creates a clinical duty of care. This is where it is discharged."""
    session = VoiceSession(pid="p", unit_id="U")
    session.feed_utterance(1000, "Honestly sir, I can't go on like this.")
    assert session.has_acute_disclosure
    assert len(session.acute_heard) == 1


def test_acute_detection_is_literal_and_never_sentiment():
    """A broad net would route ordinary frustration to a mental-health
    authority and teach the force that speaking plainly gets you referred."""
    assert acute_in("This roster is killing me.") == ()
    assert acute_in("I am exhausted and fed up.") == ()
    assert acute_in("I want to die.")


def test_a_calm_session_raises_no_acute_flag():
    session = VoiceSession(pid="p", unit_id="U")
    session.feed_utterance(0, "I'm fine, sir. Just tired.")
    assert not session.has_acute_disclosure


def test_the_acute_phrase_list_is_narrow_on_purpose():
    from samvedna.analytics.voice.session import ACUTE_PHRASES

    assert len(ACUTE_PHRASES) <= 12, "a broad list is a referral machine"


# ------------------- the mask: what voice can and cannot do about it --------
def baseline_from(**overrides):
    from samvedna.analytics.voice.concordance import VoiceBaseline

    warm = {
        "f0_range_semitones": 9.5, "jitter_local": 0.007, "shimmer_local": 0.030,
        "hnr_db": 21.0, "pause_ratio": 0.22, "speech_rate_sps": 4.1,
    }
    warm.update(overrides)
    history = []
    for i in range(5):
        session = dict(warm)
        session["f0_range_semitones"] += i * 0.2
        session["hnr_db"] -= i * 0.3
        history.append(session)
    return VoiceBaseline.from_sessions("p", history)


# Sounds entirely normal for the force — every value inside its band — but is
# flatter, tighter and noisier than this particular person has ever sounded.
MASKED = {
    "f0_range_semitones": 6.9, "jitter_local": 0.0098, "shimmer_local": 0.038,
    "hnr_db": 18.6, "pause_ratio": 0.29, "speech_rate_sps": 3.7,
}


def test_a_voice_inside_the_normal_band_raises_nothing_on_population_bands():
    """The starting point: by the force's standards this person sounds fine."""
    today = [frame(i * 2000, **MASKED) for i in range(8)]
    assert not sustained_strain(today).raised
    assert not assess(detect("I'm fine, sir.")[0], today).raised


def test_but_a_shift_from_their_own_voice_is_still_seen():
    """The one thing with purchase on a practised mask: a mask is usually a
    change from how somebody used to sound, even when it lands inside normal."""
    from samvedna.analytics.voice.concordance import baseline_shift

    today = [frame(i * 2000, **MASKED) for i in range(8)]
    shift = baseline_shift(today, baseline_from())
    assert shift.raised
    assert len(shift.shifted) >= 3
    assert "inside the normal band" in shift.describe()


def test_with_no_history_the_baseline_path_is_silent_rather_than_guessing():
    from samvedna.analytics.voice.concordance import baseline_shift

    today = [frame(i * 2000, **MASKED) for i in range(8)]
    assert not baseline_shift(today, None).raised
    assert baseline_shift(today, baseline_from()).__class__ is not None


def test_a_voice_becoming_warmer_than_usual_is_not_a_welfare_signal():
    """Counting any change would make recovery look like deterioration."""
    from statistics import median  # noqa: F401

    from samvedna.analytics.voice.concordance import baseline_shift

    better = {
        "f0_range_semitones": 12.0, "jitter_local": 0.004, "shimmer_local": 0.020,
        "hnr_db": 25.0, "pause_ratio": 0.15, "speech_rate_sps": 4.6,
    }
    today = [frame(i * 2000, **better) for i in range(8)]
    assert not baseline_shift(today, baseline_from()).raised


def test_a_mask_held_perfectly_from_the_start_is_NOT_detectable_by_voice():
    """The honest limit, written down as a test so nobody claims otherwise.

    A person who says "I'm fine" and genuinely sounds fine — and who sounded
    that way in every prior sitting too — leaves no acoustic trace. All three
    readings return nothing, and they are correct to. Any system claiming to
    detect this is claiming to measure something that left no measurement.

    The system does not depend on catching it, which is the actual answer: four
    denied leave applications and twenty-three consecutive duty days are not
    something a person can mask in a ten-minute sitting.
    """
    from samvedna.analytics.voice.concordance import baseline_shift

    steady = {
        "f0_range_semitones": 7.2, "jitter_local": 0.0095, "shimmer_local": 0.038,
        "hnr_db": 18.4, "pause_ratio": 0.28, "speech_rate_sps": 3.65,
    }
    consistent_baseline = baseline_from(**steady)
    today = [frame(i * 2000, **steady) for i in range(8)]

    assert not sustained_strain(today).raised
    assert not assess(detect("I'm fine, sir.")[0], today).raised
    assert not baseline_shift(today, consistent_baseline).raised

    session = VoiceSession(pid="p", unit_id="U", baseline=consistent_baseline)
    for f in today:
        session.feed_audio(f)
    session.feed_utterance(1000, "I'm fine, sir.")
    assert session.as_deviation() is None, "voice correctly reports nothing"


def test_the_domains_a_person_cannot_mask_still_carry_the_case():
    """Which is why voice is one of nine. Service records are laid down over
    months by other people and are not performable in a sitting."""
    from tests.conftest import case
    from tests.conftest import deviation as make_dev

    from samvedna.config.weights import CONNECTOR_DOMAINS
    from samvedna.core.gates import evidence

    assert "voice" not in CONNECTOR_DOMAINS
    unmaskable = case(
        make_dev("leave"), make_dev("duty_roster"), make_dev("workload")
    )
    assert evidence(unmaskable).passed


def test_a_session_summary_is_six_numbers_and_nothing_reconstructible():
    session = VoiceSession(pid="p", unit_id="U")
    for i in range(6):
        session.feed_audio(frame(i * 2000, **STRAINED))
    session.feed_utterance(0, "I'm fine, sir.")

    summary = session.summarise_features()
    assert set(summary) <= {b.feature for b in BANDS}
    assert all(isinstance(v, float) for v in summary.values())
    assert "fine" not in str(summary)
