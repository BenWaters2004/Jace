import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  setVoiceListening,
  setVoiceSpeaking,
  synthesizeVoice,
  transcribeVoiceRecording,
} from "../api";
import type { VoicePhase, VoiceSettings, VoiceStatus } from "../types";

interface VoiceControllerOptions {
  settings: VoiceSettings | null;
  status: VoiceStatus | null;
  onTranscript: (text: string) => void | Promise<void>;
  onError: (message: string) => void;
}

function preferredMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  for (const candidate of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(candidate)) return candidate;
  }
  return "";
}

function cleanClientSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/g, "the linked page")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/\*\*|__|~~/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function takeSentences(buffer: string): { segments: string[]; rest: string } {
  const segments: string[] = [];
  let rest = buffer;

  while (rest.length) {
    const match = rest.match(/^([\s\S]*?[.!?](?:["')\]]*)\s+)/);
    if (match && match[1].trim().length >= 18) {
      segments.push(match[1].trim());
      rest = rest.slice(match[0].length);
      continue;
    }

    const newline = rest.indexOf("\n");
    if (newline >= 0 && newline >= 80) {
      segments.push(rest.slice(0, newline).trim());
      rest = rest.slice(newline + 1);
      continue;
    }

    // Keep first audio responsive even when the model writes one very long
    // sentence. Prefer a comma/semicolon boundary before a hard split.
    if (rest.length > 260) {
      const window = rest.slice(120, 240);
      const candidates = [window.lastIndexOf("; "), window.lastIndexOf(", "), window.lastIndexOf(": ")];
      const offset = Math.max(...candidates);
      const splitAt = offset >= 0 ? 120 + offset + 1 : 220;
      segments.push(rest.slice(0, splitAt).trim());
      rest = rest.slice(splitAt).trimStart();
      continue;
    }
    break;
  }

  return { segments: segments.filter(Boolean), rest };
}

export function useVoiceController(options: VoiceControllerOptions) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [amplitude, setAmplitude] = useState(0);
  const [lastTranscript, setLastTranscript] = useState("");

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const recordingRequestedRef = useRef(false);
  const recordingChunksRef = useRef<BlobPart[]>([]);
  const micContextRef = useRef<AudioContext | null>(null);
  const micFrameRef = useRef<number | null>(null);

  const playbackContextRef = useRef<AudioContext | null>(null);
  const playbackSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const playbackFrameRef = useRef<number | null>(null);
  const speechQueueRef = useRef<string[]>([]);
  const speechBufferRef = useRef("");
  const speechWorkerRef = useRef(false);
  const speechGenerationRef = useRef(0);
  const responseSpeechEnabledRef = useRef(false);
  const speakingPublishedRef = useRef(false);

  const canRecord = Boolean(
    options.settings?.enabled
      && options.status?.enabled
      && options.status?.stt_dependency_available,
  );
  const canSpeak = Boolean(
    options.settings?.enabled
      && options.status?.enabled
      && options.status?.tts_dependency_available
      && options.status?.tts_model_files_available,
  );

  const stopAmplitudeLoop = useCallback((kind: "mic" | "playback") => {
    const ref = kind === "mic" ? micFrameRef : playbackFrameRef;
    if (ref.current !== null) window.cancelAnimationFrame(ref.current);
    ref.current = null;
    setAmplitude(0);
  }, []);

  const startAnalyserLoop = useCallback((analyser: AnalyserNode, kind: "mic" | "playback") => {
    const ref = kind === "mic" ? micFrameRef : playbackFrameRef;
    const values = new Uint8Array(analyser.fftSize);
    let lastPaint = 0;

    const tick = (time: number) => {
      analyser.getByteTimeDomainData(values);
      if (time - lastPaint > 45) {
        let sum = 0;
        for (const sample of values) {
          const centered = (sample - 128) / 128;
          sum += centered * centered;
        }
        const rms = Math.sqrt(sum / values.length);
        setAmplitude(Math.max(0, Math.min(1, rms * (kind === "mic" ? 5.5 : 4.2))));
        lastPaint = time;
      }
      ref.current = window.requestAnimationFrame(tick);
    };
    ref.current = window.requestAnimationFrame(tick);
  }, []);

  const publishSpeaking = useCallback(async (active: boolean) => {
    if (speakingPublishedRef.current === active) return;
    speakingPublishedRef.current = active;
    try { await setVoiceSpeaking(active); } catch { /* presentation state is best-effort */ }
  }, []);

  const stopSpeaking = useCallback(() => {
    speechGenerationRef.current += 1;
    speechQueueRef.current = [];
    speechBufferRef.current = "";
    responseSpeechEnabledRef.current = false;
    try { playbackSourceRef.current?.stop(); } catch { /* already ended */ }
    playbackSourceRef.current = null;
    speechWorkerRef.current = false;
    stopAmplitudeLoop("playback");
    setPhase((current) => current === "speaking" ? "idle" : current);
    void publishSpeaking(false);
  }, [publishSpeaking, stopAmplitudeLoop]);

  const ensurePlaybackContext = useCallback(async () => {
    if (!playbackContextRef.current) playbackContextRef.current = new AudioContext();
    if (playbackContextRef.current.state === "suspended") await playbackContextRef.current.resume();
    return playbackContextRef.current;
  }, []);

  // Prime Web Audio from the first real user gesture so later asynchronous
  // Kokoro responses can start immediately in WebView2 without autoplay
  // policy getting in the way.
  useEffect(() => {
    const unlock = () => {
      void ensurePlaybackContext();
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, [ensurePlaybackContext]);

  const processSpeechQueue = useCallback(async () => {
    if (speechWorkerRef.current || !canSpeak || !options.settings) return;
    speechWorkerRef.current = true;
    const generation = speechGenerationRef.current;

    try {
      while (speechQueueRef.current.length && generation === speechGenerationRef.current) {
        const raw = speechQueueRef.current.shift() ?? "";
        const text = cleanClientSpeech(raw);
        if (!text) continue;

        let audioData: ArrayBuffer;
        try {
          audioData = await synthesizeVoice({
            text,
            voice: options.settings.tts_voice,
            speed: options.settings.tts_speed,
            language: options.settings.tts_language,
          });
        } catch (error) {
          options.onError(error instanceof Error ? error.message : "Jace could not synthesize local speech.");
          speechQueueRef.current = [];
          break;
        }
        if (generation !== speechGenerationRef.current) break;

        const context = await ensurePlaybackContext();
        const decoded = await context.decodeAudioData(audioData.slice(0));
        if (generation !== speechGenerationRef.current) break;

        const source = context.createBufferSource();
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.62;
        source.buffer = decoded;
        source.connect(analyser);
        analyser.connect(context.destination);
        playbackSourceRef.current = source;

        setPhase("speaking");
        void publishSpeaking(true);
        startAnalyserLoop(analyser, "playback");

        await new Promise<void>((resolve) => {
          source.onended = () => resolve();
          source.start();
        });
        playbackSourceRef.current = null;
        stopAmplitudeLoop("playback");
      }
    } finally {
      speechWorkerRef.current = false;
      if (generation === speechGenerationRef.current && speechQueueRef.current.length === 0) {
        setPhase((current) => current === "speaking" ? "idle" : current);
        void publishSpeaking(false);
      }
    }
  }, [canSpeak, ensurePlaybackContext, options, phase, publishSpeaking, startAnalyserLoop, stopAmplitudeLoop]);

  const enqueueSpeech = useCallback((text: string) => {
    const cleaned = cleanClientSpeech(text);
    if (!cleaned || !canSpeak) return;
    speechQueueRef.current.push(cleaned);
    void processSpeechQueue();
  }, [canSpeak, processSpeechQueue]);

  const beginResponse = useCallback((speak: boolean) => {
    speechBufferRef.current = "";
    responseSpeechEnabledRef.current = speak && canSpeak;
  }, [canSpeak]);

  const ingestResponseToken = useCallback((token: string) => {
    if (!responseSpeechEnabledRef.current) return;
    speechBufferRef.current += token;
    const { segments, rest } = takeSentences(speechBufferRef.current);
    speechBufferRef.current = rest;
    for (const segment of segments) enqueueSpeech(segment);
  }, [enqueueSpeech]);

  const finishResponse = useCallback(() => {
    if (responseSpeechEnabledRef.current) {
      const tail = cleanClientSpeech(speechBufferRef.current);
      if (tail) enqueueSpeech(tail);
    }
    speechBufferRef.current = "";
    responseSpeechEnabledRef.current = false;
  }, [enqueueSpeech]);

  const speakSystem = useCallback((text: string) => {
    if (!canSpeak) return;
    stopSpeaking();
    speechGenerationRef.current += 1;
    speechQueueRef.current = [text];
    void processSpeechQueue();
  }, [canSpeak, processSpeechQueue, stopSpeaking]);

  const cleanupMic = useCallback(() => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    mediaRecorderRef.current = null;
    stopAmplitudeLoop("mic");
    if (micContextRef.current) {
      void micContextRef.current.close();
      micContextRef.current = null;
    }
  }, [stopAmplitudeLoop]);

  const startListening = useCallback(async () => {
    if (!canRecord || phase === "transcribing") return;
    recordingRequestedRef.current = true;

    // PTT doubles as an interrupt, matching the interaction model the user
    // asked for: press while Jace is speaking and he immediately stops talking.
    stopSpeaking();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      if (!recordingRequestedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      mediaStreamRef.current = stream;
      recordingChunksRef.current = [];
      const mimeType = preferredMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size) recordingChunksRef.current.push(event.data);
      };

      const context = new AudioContext();
      micContextRef.current = context;
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.55;
      source.connect(analyser);
      startAnalyserLoop(analyser, "mic");

      recorder.start(160);
      setPhase("listening");
      try { await setVoiceListening(true); } catch { /* best-effort runtime event */ }
    } catch (error) {
      recordingRequestedRef.current = false;
      cleanupMic();
      setPhase("error");
      options.onError(error instanceof Error ? error.message : "Microphone access failed.");
    }
  }, [canRecord, cleanupMic, options, phase, startAnalyserLoop, stopSpeaking]);

  const stopListening = useCallback(async () => {
    recordingRequestedRef.current = false;
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      cleanupMic();
      if (phase === "listening") setPhase("idle");
      return;
    }

    setPhase("transcribing");
    try { await setVoiceListening(false); } catch { /* best-effort runtime event */ }

    const mimeType = recorder.mimeType || "audio/webm";
    const stopped = new Promise<void>((resolve) => {
      recorder.addEventListener("stop", () => resolve(), { once: true });
    });
    recorder.stop();
    await stopped;
    const blob = new Blob(recordingChunksRef.current, { type: mimeType });
    cleanupMic();

    if (blob.size < 512) {
      setPhase("idle");
      return;
    }

    try {
      const result = await transcribeVoiceRecording(blob);
      const transcript = result.text.trim();
      setLastTranscript(transcript);
      setPhase("idle");
      if (transcript) await options.onTranscript(transcript);
    } catch (error) {
      setPhase("error");
      options.onError(error instanceof Error ? error.message : "Local speech transcription failed.");
    }
  }, [cleanupMic, options, phase]);

  useEffect(() => () => {
    recordingRequestedRef.current = false;
    cleanupMic();
    try { playbackSourceRef.current?.stop(); } catch { /* ignore */ }
    stopAmplitudeLoop("playback");
    if (playbackContextRef.current) void playbackContextRef.current.close();
  }, [cleanupMic, stopAmplitudeLoop]);

  return useMemo(() => ({
    phase,
    amplitude,
    lastTranscript,
    canRecord,
    canSpeak,
    isRecording: phase === "listening",
    isSpeaking: phase === "speaking",
    startListening,
    stopListening,
    stopSpeaking,
    beginResponse,
    ingestResponseToken,
    finishResponse,
    speakSystem,
  }), [
    amplitude,
    beginResponse,
    canRecord,
    canSpeak,
    finishResponse,
    ingestResponseToken,
    lastTranscript,
    phase,
    speakSystem,
    startListening,
    stopListening,
    stopSpeaking,
  ]);
}
