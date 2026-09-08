"use client";

import { useState } from "react";
import { Guard } from "@/components/Shell";
import { useSession } from "@/lib/session";
import { useVoiceSession } from "@/lib/useVoiceSession";

/**
 * A voice sitting you can actually have.
 *
 * This was a scripted demonstration until somebody pointed out the obvious:
 * an add-on nobody can use is a slide, not a feature. So the microphone is
 * real, the measurement is real, and it runs on this machine.
 *
 * The one thing that is *not* automatic is the words. Detecting a minimising
 * phrase needs a transcript, and the easy way to get one is the browser's
 * built-in recogniser — which uploads the audio to the vendor. For dictating an
 * email that is a fair trade. For a soldier describing his mental state it is
 * exactly what this system forbids, so the words are typed. The field says so,
 * because a person is entitled to know why they are typing rather than talking.
 *
 * Voice remains an add-on, tiered so it can corroborate a case and never make
 * one, and honest about the person it cannot see.
 */

const FEATURE_LABEL: Record<string, string> = {
  f0_hz: "pitch",
  f0_range_semitones: "intonation range",
  jitter_local: "pitch perturbation",
  shimmer_local: "amplitude perturbation",
  hnr_db: "harmonic-to-noise",
  pause_ratio: "pause fraction",
  speech_rate_sps: "syllable rate",
};

const FEATURE_UNIT: Record<string, string> = {
  f0_hz: "Hz",
  f0_range_semitones: "st",
  hnr_db: "dB",
  speech_rate_sps: "/s",
};

const PROMPTS = [
  "How has the roster been this month?",
  "How are you sleeping?",
  "How are things at home?",
  "Is there anything you'd want changed?",
];

export default function VoicePage() {
  return (
    <Guard need="personnel">
      <VoiceSitting />
    </Guard>
  );
}

function VoiceSitting() {
  const { session } = useSession();
  const v = useVoiceSession(session);
  const [text, setText] = useState("");
  const [showReference, setShowReference] = useState(false);

  const send = () => {
    if (!text.trim()) return;
    void v.say(text);
    setText("");
  };

  return (
    <>
      <div className="page-head">
        <p className="eyebrow">Add-on capability · beyond the submitted scope</p>
        <h1>Voice sitting</h1>
        <p className="lede">
          Personnel minimise. <em>&ldquo;I&rsquo;m managing, sir.&rdquo;</em>{" "}
          Usually that is simply true. This measures the voice underneath the
          claim, on this machine, and keeps none of the audio.
        </p>
      </div>

      <div className="banner warn">
        <strong>This is an add-on.</strong>
        <span>
          The submitted system reads three sources: service records, voluntary
          self-assessment and an opt-in wearable. Voice is a fourth, explored
          afterwards. It is tiered so it can corroborate a case and never make
          one — the core system does not depend on it.
        </span>
      </div>

      {/* ------------------------------------------------ the live sitting -- */}
      <div className="card lifted" style={{ marginTop: 18 }}>
        <div className="row">
          <h2 style={{ fontSize: "1.3rem" }}>
            {v.live ? "Sitting in progress" : "Start a sitting"}
          </h2>
          <span className="spacer" />
          {v.live && (
            <>
              <span className="pill stop">● recording</span>
              <span className="faint mono">{v.windows} window(s) measured</span>
            </>
          )}
          {v.hasBaseline && (
            <span className="pill mid">{v.priorSittings} prior sitting(s)</span>
          )}
        </div>

        {!v.live && !v.closed && (
          <>
            <p className="muted" style={{ marginTop: 12 }}>
              Speak for a minute or two — read the prompts below aloud, or just
              talk. Every two seconds your voice is measured and the recording
              is thrown away. Type what you said in the box so the measurement
              has something to be compared against.
            </p>
            <div className="banner info" style={{ marginTop: 12 }}>
              <strong>Before you start.</strong>
              <span>
                Your browser will ask for the microphone. The audio never leaves
                this machine and is discarded the moment it is measured — there
                is nowhere in this system it could be stored. You can stop at any
                point, and stopping destroys the words too.
              </span>
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <button className="primary" onClick={() => void v.start()}
                      disabled={v.status === "asking"}>
                {v.status === "asking" ? "Asking for the microphone…" : "Start the sitting"}
              </button>
            </div>
          </>
        )}

        {v.error && (
          <div className="banner stop" style={{ marginTop: 14 }}>
            <strong>Could not start.</strong>
            <span>{v.error}</span>
          </div>
        )}

        {v.live && (
          <div style={{ marginTop: 16 }}>
            {/* microphone level — proof it is hearing you, measured from nothing */}
            <div className="row" style={{ gap: 12 }}>
              <span className="faint" style={{ minWidth: 74 }}>Microphone</span>
              <span className="meter">
                <span
                  className="meter-fill"
                  style={{ width: `${Math.min(100, v.level * 220)}%` }}
                />
              </span>
              <span className="faint mono">
                {v.frame?.trustworthy ? "measuring" : "too quiet to measure"}
              </span>
            </div>

            {/* the six numbers, live */}
            {v.frame && Object.keys(v.frame.features).length > 0 && (
              <div className="card flat tight" style={{ marginTop: 14 }}>
                <div className="row" style={{ marginBottom: 8 }}>
                  <h3 style={{ fontSize: "0.95rem" }}>What your voice is doing</h3>
                  <span className="spacer" />
                  <span className="faint mono">
                    voiced {(v.frame.voiced_fraction * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="feat-grid">
                  {Object.entries(v.frame.features).map(([k, value]) => (
                    <div className="feat" key={k}>
                      <span className="feat-k">{FEATURE_LABEL[k] ?? k}</span>
                      <span className="feat-v mono">
                        {value.toFixed(k === "f0_hz" || k === "hnr_db" ? 1 : 3)}
                        <span className="faint"> {FEATURE_UNIT[k] ?? ""}</span>
                      </span>
                    </div>
                  ))}
                </div>
                <p className="faint" style={{ marginTop: 10 }}>
                  These are measurements, not scores. The reference bands they
                  are compared against are documented and{" "}
                  <strong>not clinically validated</strong> — which is why voice
                  is tiered the same as an opt-in fitness band.
                </p>
              </div>
            )}

            {/* say something */}
            <div style={{ marginTop: 16 }}>
              <h3 style={{ fontSize: "0.95rem" }}>What did you just say?</h3>
              <p className="faint" style={{ marginTop: 4 }}>
                Typed, not transcribed. Automatic transcription would upload your
                voice to a company outside this data centre, and this system does
                not do that with anything you say about your own mind.
              </p>
              <div className="row" style={{ marginTop: 10 }}>
                <input
                  className="input"
                  placeholder="e.g. I'm managing, mostly."
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && send()}
                />
                <button onClick={send} disabled={!text.trim()}>Record it</button>
              </div>
              <div className="row" style={{ marginTop: 10, gap: 7 }}>
                <span className="faint">Prompts to read aloud:</span>
                {PROMPTS.map((p) => (
                  <span className="pill plain" key={p}>{p}</span>
                ))}
              </div>
            </div>

            <div className="row" style={{ marginTop: 18 }}>
              <button className="danger" onClick={() => void v.stop()}>
                Stop and end the sitting
              </button>
              <span className="faint">
                Stopping releases the microphone and destroys what you typed.
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------- the acute path -- */}
      {v.acute && (
        <div className="card lifted" style={{ marginTop: 18, borderTop: "4px solid var(--stop)" }}>
          <div className="row">
            <h2 style={{ fontSize: "1.2rem", color: "var(--stop)" }}>
              Someone will contact you today
            </h2>
            <span className="spacer" />
            <span className="pill stop">routed · {v.acute.routed_to.replace(/_/g, " ")}</span>
          </div>
          <p className="muted" style={{ marginTop: 10, whiteSpace: "pre-line" }}>
            {v.acute.message}
          </p>
          {v.acute.resources.length > 0 && (
            <ul className="muted" style={{ paddingInlineStart: 18, marginTop: 12 }}>
              {v.acute.resources.map((r) => (
                <li key={r.who}><strong>{r.who}</strong> — {r.how}</li>
              ))}
            </ul>
          )}
          <p className="faint" style={{ marginTop: 12 }}>
            This did not wait for tonight&rsquo;s run and did not go through the
            four gates. It was triggered by a specific phrase, never by a score,
            and it goes to a mental-health authority — not to your commanding
            officer.
          </p>
        </div>
      )}

      {/* ---------------------------------------------------- the three readings -- */}
      {v.readings && !v.closed && (
        <div className="grid grid-3" style={{ marginTop: 18 }}>
          {[
            { key: "gap", title: "Words vs voice", r: v.readings.gap },
            { key: "strain", title: "Sustained strain", r: v.readings.strain },
            { key: "shift", title: "Change from your own voice", r: v.readings.shift },
          ].map(({ key, title, r }) => (
            <div className="card" key={key}
                 style={{ borderTop: `4px solid ${r.raised ? "var(--hold)" : "var(--rule)"}` }}>
              <div className="row" style={{ marginBottom: 8 }}>
                <h3 style={{ fontSize: "0.98rem" }}>{title}</h3>
                <span className="spacer" />
                <span className={`pill ${r.raised ? "hold" : "plain"}`}>
                  {r.raised ? "raised" : "nothing yet"}
                </span>
              </div>
              <p className="faint">{r.detail}</p>
              {typeof r.divergence === "number" && r.divergence > 0 && (
                <p className="mono faint" style={{ marginTop: 8 }}>
                  divergence {r.divergence.toFixed(3)}
                  {typeof r.coverage === "number" && r.coverage > 0 && (
                    <> · held across {(r.coverage * 100).toFixed(0)}%</>
                  )}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ------------------------------------------------------- what you said -- */}
      {v.utterances.length > 0 && !v.closed && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3>This sitting</h3>
          <p className="faint" style={{ marginTop: 4 }}>
            Held only while the sitting is open. Closing it destroys this list.
          </p>
          <div className="stack" style={{ gap: 8, marginTop: 12 }}>
            {v.utterances.map((u, i) => (
              <div className="card flat tight" key={`${u.at_ms}-${i}`}>
                <div className="row">
                  <span className="faint mono">
                    {Math.floor(u.at_ms / 60000)}:
                    {String(Math.floor((u.at_ms % 60000) / 1000)).padStart(2, "0")}
                  </span>
                  <strong>&ldquo;{u.text}&rdquo;</strong>
                  <span className="spacer" />
                  {u.raised && (
                    <span className="pill hold">gap · {u.divergence.toFixed(2)}</span>
                  )}
                </div>
                <p className="faint" style={{ marginTop: 6 }}>{u.detail}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- closed -- */}
      {v.closed && (
        <div className="card lifted" style={{ marginTop: 18, borderTop: "4px solid var(--pass)" }}>
          <div className="row">
            <h2 style={{ fontSize: "1.25rem" }}>Sitting closed</h2>
            <span className="spacer" />
            <span className="pill pass">audio never stored</span>
            <span className="pill pass">transcript destroyed</span>
          </div>

          <p className="muted" style={{ marginTop: 12 }}>{v.closed.note}</p>

          <h3 style={{ marginTop: 18, fontSize: "0.95rem" }}>
            What was kept — {Object.keys(v.closed.kept).length} numbers
          </h3>
          <div className="feat-grid" style={{ marginTop: 8 }}>
            {Object.entries(v.closed.kept).map(([k, value]) => (
              <div className="feat" key={k}>
                <span className="feat-k">{FEATURE_LABEL[k] ?? k}</span>
                <span className="feat-v mono">{value.toFixed(3)}</span>
              </div>
            ))}
          </div>
          <p className="faint" style={{ marginTop: 10 }}>
            These let a later sitting ask whether you still sound like yourself —
            the one question a population comparison cannot answer, and the only
            reading with any purchase on somebody who is good at sounding fine.
            You now have {v.closed.prior_sittings} sitting(s) on record.
          </p>

          {v.closed.deviation ? (
            <div className="card flat" style={{ marginTop: 16 }}>
              <h3 style={{ fontSize: "0.95rem" }}>What reaches the nightly run</h3>
              <div className="feat-grid" style={{ marginTop: 8 }}>
                <div className="feat">
                  <span className="feat-k">domain</span>
                  <span className="feat-v mono">{v.closed.deviation.domain}</span>
                </div>
                <div className="feat">
                  <span className="feat-k">tier</span>
                  <span className="feat-v mono">
                    {v.closed.deviation.tier} · weight {v.closed.deviation.weight}
                  </span>
                </div>
                <div className="feat">
                  <span className="feat-k">z from baseline</span>
                  <span className="feat-v mono">{v.closed.deviation.z_self}</span>
                </div>
              </div>
              <p className="faint" style={{ marginTop: 10 }}>
                No words, no sound, no quote. On its own this scores 0.183 against
                a 0.65 evidence threshold, so it can corroborate a case built from
                service records and can never make one.
              </p>
            </div>
          ) : (
            <div className="banner good" style={{ marginTop: 16 }}>
              <strong>Nothing was raised.</strong>
              <span>
                Nothing about this sitting reaches the nightly run at all. That is
                the ordinary result.
              </span>
            </div>
          )}

          <div className="row" style={{ marginTop: 16 }}>
            <button className="primary" onClick={() => void v.start()}>
              Have another sitting
            </button>
          </div>
        </div>
      )}

      {/* --------------------------------------------------- the honest limit -- */}
      <div className="card rail" style={{ marginTop: 22 }}>
        <h2 style={{ fontSize: "1.2rem" }}>What this cannot see</h2>
        <p className="muted measure" style={{ marginTop: 10 }}>
          Someone who says &ldquo;I&rsquo;m fine&rdquo; and genuinely{" "}
          <em>sounds</em> fine leaves no acoustic trace. Not a small one — none.
          All three readings above return nothing, and they are right to: there is
          no signal there to find. Any system claiming to detect successfully
          masked distress from a voice is claiming to measure something that left
          no measurement.
        </p>
        <p className="muted measure" style={{ marginTop: 10 }}>
          What a person cannot perform in a ten-minute sitting is four denied
          leave applications, twenty-three consecutive duty days and three
          postings in eighteen months — traces laid down over months by other
          people. Those eight signals are the system. This is one more way of
          listening to it.
        </p>
      </div>

      {/* --------------------------------------------- worked examples, folded -- */}
      <div style={{ marginTop: 22 }}>
        <button className="ghost" onClick={() => setShowReference((s) => !s)}>
          {showReference ? "Hide" : "Show"} the five cases this engine is tested against
        </button>
        {showReference && <Reference />}
      </div>
    </>
  );
}

/**
 * The five sittings the test suite pins. Kept because they include the two
 * cases somebody has to go looking for — the person who never claims to be
 * fine, and the person who masks completely — and neither is easy to produce on
 * demand with a live microphone.
 */
function Reference() {
  const CASES = [
    {
      who: "Says they are fine · voice disagrees",
      what: "The classic gap. Divergence 0.633 across six features: intonation range 3.2 semitones against a normal of 8, perturbation 0.026 against 0.010, harmonic-to-noise 9.5 dB against 18.",
      result: "Raised. Reaches the gates as a Tier 3 signal.",
      kind: "warn",
    },
    {
      who: "Never claims to be fine · voice strained anyway",
      what: "No minimising phrase is ever said, so the cue-anchored path is blind. The unanchored path catches it: divergence 0.820, held across 100% of the sitting, four features past the floor.",
      result: "Raised by the second path. This is why a phrase bank alone is not enough.",
      kind: "warn",
    },
    {
      who: "Sounds fine · but not like themselves",
      what: "Every measurement inside the normal band for the force. Against their own five prior sittings: perturbation 0.007 → 0.0098, harmonic-to-noise 20.4 → 18.6.",
      result: "Only the personal-baseline path sees this.",
      kind: "info",
    },
    {
      who: "Masking completely · from the first sitting",
      what: "Says they are fine, sounds fine, and sounded exactly this way every prior time. There is no trace, because none was left.",
      result: "Nothing raised — and that is the correct answer, not a failure.",
      kind: "stop",
    },
    {
      who: "Acute disclosure, heard in speech",
      what: "A specific phrase, matched literally. 'This roster is killing me' does not fire; 'I can't go on like this' does.",
      result: "Same working day, to a mental-health authority, bypassing the gates.",
      kind: "stop",
    },
  ];

  return (
    <div className="stack" style={{ marginTop: 14 }}>
      {CASES.map((c) => (
        <div className="card" key={c.who}>
          <h3 style={{ fontSize: "0.98rem" }}>{c.who}</h3>
          <p className="muted" style={{ marginTop: 7 }}>{c.what}</p>
          <div className={`banner ${c.kind}`} style={{ marginTop: 10 }}>
            <span>{c.result}</span>
          </div>
        </div>
      ))}
      <p className="faint">
        All five are asserted in the test suite, including the fourth — the limit
        is written down as a test so nobody can claim otherwise.
      </p>
    </div>
  );
}
