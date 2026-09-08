/**
 * Microphone capture for a voice sitting.
 *
 * Runs on the audio thread, downsamples to 16 kHz, and hands whole windows to
 * the page. The page sends a window to the backend, gets six numbers back, and
 * the samples are gone — this worklet keeps nothing beyond the window it is
 * currently filling.
 *
 * Downsampling is a box average rather than plain decimation. Dropping every
 * third sample folds everything above 8 kHz back into the band as noise, and
 * that noise lands squarely on the harmonic-to-noise ratio — one of the six
 * features a finding can rest on. Averaging first is a crude anti-alias filter,
 * but it is the difference between measuring the voice and measuring the
 * resampler.
 */
class VoiceCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { targetRate = 16000, windowSeconds = 2 } = options.processorOptions || {};
    this.targetRate = targetRate;
    this.ratio = sampleRate / targetRate;
    this.windowLength = Math.round(targetRate * windowSeconds);
    this.window = new Float32Array(this.windowLength);
    this.filled = 0;
    this.carry = 0;
    this.carryCount = 0;
    this.peak = 0;
    this.framesSincePeak = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const channel = input[0];

    for (let i = 0; i < channel.length; i += 1) {
      const sample = channel[i];
      const magnitude = sample < 0 ? -sample : sample;
      if (magnitude > this.peak) this.peak = magnitude;

      // Box-average into the target rate.
      this.carry += sample;
      this.carryCount += 1;
      if (this.carryCount >= this.ratio) {
        this.window[this.filled] = this.carry / this.carryCount;
        this.filled += 1;
        this.carry = 0;
        this.carryCount = 0;

        if (this.filled >= this.windowLength) {
          // Convert here rather than on the main thread: 16-bit is half the
          // bytes of a Float32 and the measurement does not need the precision.
          const pcm = new Int16Array(this.windowLength);
          for (let n = 0; n < this.windowLength; n += 1) {
            const clamped = Math.max(-1, Math.min(1, this.window[n]));
            pcm[n] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
          }
          this.port.postMessage({ type: "window", pcm: pcm.buffer }, [pcm.buffer]);
          this.filled = 0;
        }
      }
    }

    // A level reading a few times a second, so the person can see the
    // microphone is actually hearing them. Nothing is measured from this.
    this.framesSincePeak += 1;
    if (this.framesSincePeak >= 6) {
      this.port.postMessage({ type: "level", peak: this.peak });
      this.peak = 0;
      this.framesSincePeak = 0;
    }
    return true;
  }
}

registerProcessor("voice-capture", VoiceCapture);
