"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "./api";

/**
 * Drives a live voice sitting: microphone in, six numbers back, audio gone.
 *
 * The hook owns three things the page should not have to think about — the
 * audio graph, the window queue, and making sure the microphone is actually
 * released when the sitting ends. That last one matters more than it sounds: a
 * page that stops sending audio but leaves the track live keeps the browser's
 * recording indicator on, and a person who has been told the recording stopped
 * is entitled to see it stop.
 */

const WINDOW_SECONDS = 2;
const TARGET_RATE = 16000;

export interface Reading {
  raised: boolean;
  detail: string;
  divergence?: number;
  coverage?: number;
  windows?: number;
  count?: number;
  shifted?: { feature: string; was: number; now: number; z: number }[];
}

export interface Readings {
  gap: Reading;
  strain: Reading;
  shift: Reading;
}

export interface Frame {
  at_ms: number;
  duration_s: number;
  voiced_fraction: number;
  trustworthy: boolean;
  features: Record<string, number>;
}

export interface Acute {
  routed_to: string;
  acknowledge_by: string | null;
  message: string;
  resources: { who: string; how: string }[];
  matched_phrase: string;
}

export interface Utterance {
  at_ms: number;
  text: string;
  raised: boolean;
  divergence: number;
  detail: string;
}

export interface Closed {
  windows_measured: number;
  kept: Record<string, number>;
  prior_sittings: number;
  readings: Readings;
  deviation: {
    domain: string; tier: string; weight: number; z_self: number;
    daily_breach: Record<string, number>;
  } | null;
  note: string;
}

type Status = "idle" | "asking" | "live" | "closing" | "closed" | "error";

function headers(session: Session): Record<string, string> {
  return {
    "X-Role": session.role,
    "X-Operator": session.operator,
    "X-Units": session.units,
    "Content-Type": "application/json",
  };
}

export function useVoiceSession(session: Session | null) {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const [level, setLevel] = useState(0);
  const [windows, setWindows] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [readings, setReadings] = useState<Readings | null>(null);
  const [utterances, setUtterances] = useState<Utterance[]>([]);
  const [acute, setAcute] = useState<Acute | null>(null);
  const [closed, setClosed] = useState<Closed | null>(null);
  const [priorSittings, setPriorSittings] = useState(0);
  const [hasBaseline, setHasBaseline] = useState(false);

  const sessionId = useRef<string | null>(null);
  const context = useRef<AudioContext | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const node = useRef<AudioWorkletNode | null>(null);
  const startedAt = useRef(0);
  const sending = useRef(false);

  /** Release the microphone completely. Called on stop and on unmount. */
  const teardown = useCallback(() => {
    node.current?.port.close();
    node.current?.disconnect();
    node.current = null;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    void context.current?.close();
    context.current = null;
    setLevel(0);
  }, []);

  useEffect(() => teardown, [teardown]);

  const pushWindow = useCallback(
    async (buffer: ArrayBuffer) => {
      if (!session || !sessionId.current || sending.current) return;
      sending.current = true;
      try {
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i += 1) {
          binary += String.fromCharCode(bytes[i]);
        }
        const response = await fetch(`/api/voice/${sessionId.current}/audio`, {
          method: "POST",
          headers: headers(session),
          body: JSON.stringify({
            pcm16: btoa(binary),
            at_ms: Date.now() - startedAt.current,
          }),
        });
        const body = await response.json();
        if (response.ok) {
          setFrame(body.frame);
          setWindows(body.windows);
          setReadings(body.readings);
        }
      } catch {
        /* one dropped window is not worth interrupting a sitting for */
      } finally {
        sending.current = false;
      }
    },
    [session],
  );

  const start = useCallback(async () => {
    if (!session) return;
    setError("");
    setStatus("asking");
    setClosed(null);
    setAcute(null);
    setUtterances([]);
    setWindows(0);
    setFrame(null);
    setReadings(null);

    try {
      const opened = await fetch("/api/voice/session", {
        method: "POST",
        headers: headers(session),
        body: "{}",
      });
      const body = await opened.json();
      if (!opened.ok) throw new Error(body.detail ?? "could not open a sitting");
      sessionId.current = body.session_id;
      setPriorSittings(body.prior_sittings ?? 0);
      setHasBaseline(Boolean(body.has_baseline));

      const media = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      stream.current = media;

      const ctx = new AudioContext();
      context.current = ctx;
      await ctx.audioWorklet.addModule("/voice-capture.js");

      const source = ctx.createMediaStreamSource(media);
      const worklet = new AudioWorkletNode(ctx, "voice-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        processorOptions: { targetRate: TARGET_RATE, windowSeconds: WINDOW_SECONDS },
      });
      worklet.port.onmessage = (event) => {
        if (event.data.type === "level") setLevel(event.data.peak);
        else if (event.data.type === "window") void pushWindow(event.data.pcm);
      };
      source.connect(worklet);
      node.current = worklet;
      startedAt.current = Date.now();
      setStatus("live");
    } catch (e) {
      teardown();
      const message = (e as Error).message;
      setError(
        message.includes("Permission") || message.includes("denied")
          ? "The browser blocked the microphone. Allow it in the address bar and try again — nothing is recorded until you do."
          : message,
      );
      setStatus("error");
    }
  }, [session, pushWindow, teardown]);

  const say = useCallback(
    async (text: string, source: "typed" | "on_device_stt" = "typed") => {
      if (!session || !sessionId.current || !text.trim()) return;
      const at = Date.now() - startedAt.current;
      const response = await fetch(`/api/voice/${sessionId.current}/utterance`, {
        method: "POST",
        headers: headers(session),
        body: JSON.stringify({ text, at_ms: at, source }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.detail ?? "that could not be recorded");
        return;
      }
      setReadings(body.readings);
      if (body.acute) setAcute(body.acute);
      setUtterances((prev) => [
        ...prev,
        {
          at_ms: at,
          text,
          raised: Boolean(body.raised),
          divergence: body.divergence ?? 0,
          detail: body.detail ?? "",
        },
      ]);
    },
    [session],
  );

  const stop = useCallback(async () => {
    if (!session || !sessionId.current) return;
    setStatus("closing");
    teardown();
    try {
      const response = await fetch(`/api/voice/${sessionId.current}/close`, {
        method: "POST",
        headers: headers(session),
        body: "{}",
      });
      const body = await response.json();
      if (response.ok) setClosed(body);
      else setError(body.detail ?? "the sitting could not be closed cleanly");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      sessionId.current = null;
      setStatus("closed");
    }
  }, [session, teardown]);

  return {
    status, error, level, windows, frame, readings, utterances, acute, closed,
    priorSittings, hasBaseline, start, say, stop,
    live: status === "live",
  };
}
