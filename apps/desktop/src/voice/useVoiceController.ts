import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../constants";

export const PUSH_TO_TALK_KEY = "Home";
export const DEFAULT_VOICE_WELCOME_LINE =
  "All systems online, sir. What are we working on today?";

export type VoicePhase =
  | "idle"
  | "listening"
  | "transcribing"
  | "speaking"
  | "error";

// Backwards-friendly aliases for Phase 10B callers.
export type VoiceControllerState = VoicePhase;
export type VoiceState = VoicePhase;

export interface VoiceStatusResponse {
  enabled: boolean;
  platform_supported?: boolean;
  transcription_available: boolean;
  synthesis_available: boolean;
  stt_available?: boolean;
  tts_available?: boolean;
  whisper_model?: string | null;
  piper_model?: string | null;
  push_to_talk_key?: string;
  welcome_line?: string;
  [key: string]: unknown;
}

export interface VoiceTranscriptionResponse {
  text: string;
  language?: string | null;
  language_probability?: number | null;
  duration_seconds?: number | null;
  bytes_received?: number;
  filename?: string | null;
}

export interface UseVoiceControllerOptions {
  enabled?: boolean;
  online?: boolean;
  disabled?: boolean;
  isGenerating?: boolean;
  autoSubmit?: boolean;
  enableHomePushToTalk?: boolean;
  speakWelcome?: boolean;
  welcomeLine?: string;

  onTranscript?: (text: string) => void | Promise<void>;
  onFinalTranscript?: (text: string) => void | Promise<void>;
  onSubmitTranscript?: (text: string) => void | Promise<void>;
  onTranscription?: (text: string) => void | Promise<void>;
  onVoiceInput?: (text: string) => void | Promise<void>;
  onText?: (text: string) => void | Promise<void>;
  onError?: (message: string) => void;
  onStateChange?: (state: VoicePhase) => void;
  onListeningChange?: (listening: boolean) => void;
  onSpeakingChange?: (speaking: boolean) => void;

  // Phase 10B evolved quickly. Keep unknown options accepted so this hook can
  // replace earlier variants without forcing unrelated App.tsx edits.
  [key: string]: any;
}

export interface VoiceController {
  phase: VoicePhase;
  state: VoicePhase;
  voiceState: VoicePhase;
  status: VoiceStatusResponse | null;
  error: string | null;
  lastTranscript: string;
  isRecording: boolean;
  isListening: boolean;
  isTranscribing: boolean;
  isSpeaking: boolean;
  supported: boolean;
  available: boolean;
  pushToTalkKey: string;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<string | null>;
  startListening: () => Promise<void>;
  stopListening: () => Promise<string | null>;
  startPushToTalk: () => Promise<void>;
  stopPushToTalk: () => Promise<string | null>;
  beginPushToTalk: () => Promise<void>;
  endPushToTalk: () => Promise<string | null>;
  toggleRecording: () => Promise<void>;
  toggleListening: () => Promise<void>;
  speak: (text: string) => Promise<void>;
  speakText: (text: string) => Promise<void>;
  stopSpeaking: () => void;
  cancel: () => void;
  clearError: () => void;
  refreshStatus: () => Promise<VoiceStatusResponse | null>;
  [key: string]: any;
}

const MIN_RECORDING_MS = 350;
const MIN_AUDIO_BYTES = 1_000;
const RECORDER_TIMESLICE_MS = 250;
const FINAL_FLUSH_DELAY_MS = 75;

let welcomeSpokenThisLaunch = false;

function preferredAudioMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";

  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];

  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

function extensionForMimeType(type: string): string {
  const normalised = type.toLowerCase();
  if (normalised.includes("ogg")) return "ogg";
  if (normalised.includes("wav")) return "wav";
  if (normalised.includes("mpeg")) return "mp3";
  if (normalised.includes("mp4") || normalised.includes("m4a")) return "m4a";
  return "webm";
}

function looksLikeExpectedContainer(blob: Blob): Promise<boolean> {
  return blob.slice(0, 16).arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    const type = blob.type.toLowerCase();

    if (type.includes("webm")) {
      return (
        bytes.length >= 4 &&
        bytes[0] === 0x1a &&
        bytes[1] === 0x45 &&
        bytes[2] === 0xdf &&
        bytes[3] === 0xa3
      );
    }

    if (type.includes("ogg")) {
      return (
        bytes.length >= 4 &&
        bytes[0] === 0x4f &&
        bytes[1] === 0x67 &&
        bytes[2] === 0x67 &&
        bytes[3] === 0x53
      );
    }

    if (type.includes("wav")) {
      return (
        bytes.length >= 4 &&
        bytes[0] === 0x52 &&
        bytes[1] === 0x49 &&
        bytes[2] === 0x46 &&
        bytes[3] === 0x46
      );
    }

    // Unknown/other audio containers are validated again by the backend.
    return true;
  });
}

async function responseError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string" && body.detail.trim()) return body.detail;
    if (typeof body?.message === "string" && body.message.trim()) return body.message;
  } catch {
    // Fall through to a useful local message.
  }

  return `${fallback} (${response.status} ${response.statusText})`;
}

function releaseStream(stream: MediaStream | null) {
  if (!stream) return;
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch {
      // Best effort cleanup.
    }
  }
}

export function useVoiceController(
  options: UseVoiceControllerOptions = {},
): VoiceController {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [phase, setPhaseState] = useState<VoicePhase>("idle");
  const [status, setStatus] = useState<VoiceStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastTranscript, setLastTranscript] = useState("");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingStartedAtRef = useRef<number | null>(null);
  const stoppingRef = useRef<Promise<string | null> | null>(null);
  const homeHeldRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  const setPhase = useCallback((next: VoicePhase) => {
    if (!mountedRef.current) return;
    setPhaseState(next);
    optionsRef.current.onStateChange?.(next);
    optionsRef.current.onListeningChange?.(next === "listening");
    optionsRef.current.onSpeakingChange?.(next === "speaking");
  }, []);

  const reportError = useCallback((message: string) => {
    if (!mountedRef.current) return;
    setError(message);
    setPhase("error");
    optionsRef.current.onError?.(message);
  }, [setPhase]);

  const clearError = useCallback(() => {
    if (!mountedRef.current) return;
    setError(null);
    if (phase === "error") setPhase("idle");
  }, [phase, setPhase]);

  const stopSpeaking = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      try {
        audio.pause();
        audio.currentTime = 0;
      } catch {
        // Best effort.
      }
    }
    audioRef.current = null;

    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }

    if (mountedRef.current && phase === "speaking") {
      setPhase("idle");
    }
  }, [phase, setPhase]);

  const refreshStatus = useCallback(async (): Promise<VoiceStatusResponse | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/voice/status`);
      if (!response.ok) {
        throw new Error(await responseError(response, "Could not read Jace voice status"));
      }

      const next = (await response.json()) as VoiceStatusResponse;
      if (mountedRef.current) setStatus(next);
      return next;
    } catch (statusError) {
      const message = statusError instanceof Error
        ? statusError.message
        : "Could not read Jace voice status.";
      // Status failure is non-fatal to the rest of Jace. Do not force the
      // whole UI into an error state here.
      if (mountedRef.current) setError(message);
      return null;
    }
  }, []);

  const speak = useCallback(async (text: string): Promise<void> => {
    const value = text.trim();
    if (!value) return;

    stopSpeaking();

    try {
      const response = await fetch(`${API_BASE_URL}/voice/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      });

      if (!response.ok) {
        throw new Error(await responseError(response, "Speech synthesis failed"));
      }

      const blob = await response.blob();
      if (!blob.size) throw new Error("Speech synthesis returned an empty audio file.");

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      audioUrlRef.current = url;

      setError(null);
      setPhase("speaking");

      await new Promise<void>((resolve, reject) => {
        audio.addEventListener("ended", () => resolve(), { once: true });
        audio.addEventListener(
          "error",
          () => reject(new Error("Jace could not play the generated speech audio.")),
          { once: true },
        );
        void audio.play().catch(reject);
      });

      if (audioRef.current === audio) {
        audioRef.current = null;
        if (audioUrlRef.current === url) {
          URL.revokeObjectURL(url);
          audioUrlRef.current = null;
        }
        setPhase("idle");
      }
    } catch (speakError) {
      stopSpeaking();
      const message = speakError instanceof Error
        ? speakError.message
        : "Jace could not speak the response.";
      reportError(message);
      throw speakError;
    }
  }, [reportError, setPhase, stopSpeaking]);

  const deliverTranscript = useCallback(async (text: string) => {
    const current = optionsRef.current;
    const handler =
      current.onSubmitTranscript ??
      current.onFinalTranscript ??
      current.onTranscript ??
      current.onTranscription ??
      current.onVoiceInput ??
      current.onText;

    if (typeof handler === "function") {
      await handler(text);
    }
  }, []);

  const transcribeBlob = useCallback(async (blob: Blob): Promise<string> => {
    if (blob.size < MIN_AUDIO_BYTES) {
      throw new Error(
        "The microphone recording did not contain enough audio. Hold Home, speak, then release Home to send.",
      );
    }

    const containerLooksValid = await looksLikeExpectedContainer(blob);
    if (!containerLooksValid) {
      throw new Error(
        "The microphone produced an incomplete audio recording. Please hold Home for a moment before speaking and try again.",
      );
    }

    const mimeType = blob.type || "audio/webm";
    const extension = extensionForMimeType(mimeType);
    const file = new File([blob], `jace-voice.${extension}`, {
      type: mimeType,
      lastModified: Date.now(),
    });

    const form = new FormData();
    form.append("file", file, file.name);

    console.debug("[Jace Voice] uploading recording", {
      bytes: blob.size,
      mimeType,
      filename: file.name,
    });

    const response = await fetch(`${API_BASE_URL}/voice/transcribe`, {
      method: "POST",
      body: form,
    });

    if (!response.ok) {
      throw new Error(await responseError(response, "Audio transcription failed"));
    }

    const result = (await response.json()) as VoiceTranscriptionResponse;
    const text = String(result.text ?? "").trim();

    if (!text) {
      throw new Error("Jace could not detect any speech in that recording.");
    }

    return text;
  }, []);

  const startRecording = useCallback(async (): Promise<void> => {
    const currentOptions = optionsRef.current;

    if (currentOptions.enabled === false) return;
    if (currentOptions.disabled) return;
    if (currentOptions.online === false) return;
    if (currentOptions.isGenerating) return;
    if (recorderRef.current && recorderRef.current.state !== "inactive") return;

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      reportError("Microphone recording is not supported by this Jace desktop runtime.");
      return;
    }

    // Holding Home while Jace is speaking should immediately hand control back
    // to the user instead of recording Jace's own voice output.
    stopSpeaking();
    setError(null);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });

      const mimeType = preferredAudioMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      chunksRef.current = [];
      streamRef.current = stream;
      recorderRef.current = recorder;
      recordingStartedAtRef.current = performance.now();

      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
          console.debug("[Jace Voice] audio chunk", {
            bytes: event.data.size,
            type: event.data.type,
          });
        }
      });

      recorder.addEventListener("error", (event) => {
        const recorderError = (event as Event & { error?: DOMException }).error;
        reportError(recorderError?.message || "The microphone recorder reported an error.");
      });

      recorder.start(RECORDER_TIMESLICE_MS);
      console.debug("[Jace Voice] recorder started", {
        requestedMimeType: mimeType,
        recorderMimeType: recorder.mimeType,
      });
      setPhase("listening");
    } catch (recordError) {
      releaseStream(streamRef.current);
      streamRef.current = null;
      recorderRef.current = null;

      const message = recordError instanceof DOMException && recordError.name === "NotAllowedError"
        ? "Microphone access was denied. Allow microphone access for Jace, then try again."
        : recordError instanceof Error
          ? recordError.message
          : "Jace could not start the microphone.";
      reportError(message);
    }
  }, [reportError, setPhase, stopSpeaking]);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    if (stoppingRef.current) return stoppingRef.current;

    const recorder = recorderRef.current;
    const startedAt = recordingStartedAtRef.current;

    if (!recorder || recorder.state === "inactive") {
      releaseStream(streamRef.current);
      streamRef.current = null;
      recorderRef.current = null;
      recordingStartedAtRef.current = null;
      if (phase === "listening") setPhase("idle");
      return null;
    }

    const task = (async () => {
      try {
        const elapsedMs = startedAt == null ? 0 : performance.now() - startedAt;

        const blob = await new Promise<Blob>((resolve, reject) => {
          const handleStop = () => {
            try {
              const chunks = chunksRef.current.filter((chunk) => chunk.size > 0);
              const actualMimeType =
                chunks[0]?.type ||
                recorder.mimeType ||
                preferredAudioMimeType() ||
                "audio/webm";

              const finalBlob = new Blob(chunks, { type: actualMimeType });
              console.debug("[Jace Voice] final recording", {
                chunks: chunks.length,
                bytes: finalBlob.size,
                mimeType: finalBlob.type,
                elapsedMs: Math.round(elapsedMs),
              });
              resolve(finalBlob);
            } catch (blobError) {
              reject(blobError);
            }
          };

          recorder.addEventListener("stop", handleStop, { once: true });

          try {
            // Explicitly flush the encoder's current packet before stop. This is
            // important on Windows/WebView2 where a rapid stop can otherwise
            // produce a header-only WebM file.
            recorder.requestData();
          } catch {
            // Some MediaRecorder implementations reject requestData while they
            // are already transitioning to inactive. The stop event is still
            // authoritative.
          }

          window.setTimeout(() => {
            try {
              if (recorder.state !== "inactive") recorder.stop();
            } catch (stopError) {
              reject(stopError);
            }
          }, FINAL_FLUSH_DELAY_MS);
        });

        recorderRef.current = null;
        recordingStartedAtRef.current = null;
        releaseStream(streamRef.current);
        streamRef.current = null;

        // A very brief tap is treated as a cancelled push-to-talk gesture rather
        // than an audio error.
        if (elapsedMs < MIN_RECORDING_MS) {
          chunksRef.current = [];
          setPhase("idle");
          return null;
        }

        setPhase("transcribing");
        const transcript = await transcribeBlob(blob);
        chunksRef.current = [];

        if (mountedRef.current) {
          setLastTranscript(transcript);
          setError(null);
        }

        await deliverTranscript(transcript);
        setPhase("idle");
        return transcript;
      } catch (stopError) {
        recorderRef.current = null;
        recordingStartedAtRef.current = null;
        releaseStream(streamRef.current);
        streamRef.current = null;
        chunksRef.current = [];

        const message = stopError instanceof Error
          ? stopError.message
          : "Jace could not process the microphone recording.";
        reportError(message);
        return null;
      } finally {
        stoppingRef.current = null;
      }
    })();

    stoppingRef.current = task;
    return task;
  }, [deliverTranscript, phase, reportError, setPhase, transcribeBlob]);

  const toggleRecording = useCallback(async () => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      await stopRecording();
    } else {
      await startRecording();
    }
  }, [startRecording, stopRecording]);

  const cancel = useCallback(() => {
    homeHeldRef.current = false;

    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        // Best effort.
      }
    }

    recorderRef.current = null;
    recordingStartedAtRef.current = null;
    chunksRef.current = [];
    releaseStream(streamRef.current);
    streamRef.current = null;
    stopSpeaking();
    setPhase("idle");
  }, [setPhase, stopSpeaking]);

  // Physical Home key = push-to-talk. Keydown starts recording; keyup flushes,
  // finalises and submits the transcription through the hook's existing callback.
  useEffect(() => {
    if (options.enableHomePushToTalk === false) return;

    function keyDown(event: KeyboardEvent) {
      if (event.code !== "Home" && event.key !== "Home") return;
      if (event.repeat || homeHeldRef.current) return;
      if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;

      const current = optionsRef.current;
      if (
        current.enabled === false ||
        current.disabled ||
        current.online === false ||
        current.isGenerating
      ) {
        return;
      }

      event.preventDefault();
      homeHeldRef.current = true;
      void startRecording();
    }

    function keyUp(event: KeyboardEvent) {
      if (event.code !== "Home" && event.key !== "Home") return;
      if (!homeHeldRef.current) return;

      event.preventDefault();
      homeHeldRef.current = false;
      void stopRecording();
    }

    function windowBlur() {
      if (!homeHeldRef.current) return;
      homeHeldRef.current = false;
      void stopRecording();
    }

    window.addEventListener("keydown", keyDown, { capture: true });
    window.addEventListener("keyup", keyUp, { capture: true });
    window.addEventListener("blur", windowBlur);

    return () => {
      window.removeEventListener("keydown", keyDown, { capture: true });
      window.removeEventListener("keyup", keyUp, { capture: true });
      window.removeEventListener("blur", windowBlur);
    };
  }, [options.enableHomePushToTalk, startRecording, stopRecording]);

  // Startup greeting. It is local TTS only: it is not sent to the model and it
  // does not create a conversation message. It runs once per desktop launch.
  useEffect(() => {
    if (welcomeSpokenThisLaunch) return;
    if (options.speakWelcome === false) return;
    if (options.enabled === false || options.disabled) return;
    if (options.online === false) return;

    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        const currentStatus = await refreshStatus();
        if (cancelled || welcomeSpokenThisLaunch) return;

        const synthesisAvailable =
          currentStatus?.synthesis_available ??
          currentStatus?.tts_available ??
          false;

        if (!synthesisAvailable) return;

        welcomeSpokenThisLaunch = true;
        const line =
          String(optionsRef.current.welcomeLine || "").trim() ||
          currentStatus?.welcome_line ||
          DEFAULT_VOICE_WELCOME_LINE;

        try {
          await speak(line);
        } catch {
          // speak() already reports a useful error. The startup greeting must
          // never prevent the rest of Jace from loading.
        }
      })();
    }, 650);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    options.disabled,
    options.enabled,
    options.online,
    options.speakWelcome,
    refreshStatus,
    speak,
  ]);

  useEffect(() => {
    mountedRef.current = true;
    void refreshStatus();

    return () => {
      mountedRef.current = false;
      homeHeldRef.current = false;

      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          // Best effort.
        }
      }

      releaseStream(streamRef.current);
      streamRef.current = null;
      recorderRef.current = null;

      const audio = audioRef.current;
      if (audio) {
        try {
          audio.pause();
        } catch {
          // Best effort.
        }
      }
      audioRef.current = null;

      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
    };
  }, [refreshStatus]);

  const supported =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined";

  const available = Boolean(
    supported &&
    (status?.transcription_available ?? status?.stt_available ?? true),
  );

  return {
    phase,
    state: phase,
    voiceState: phase,
    status,
    error,
    lastTranscript,
    isRecording: phase === "listening",
    isListening: phase === "listening",
    isTranscribing: phase === "transcribing",
    isSpeaking: phase === "speaking",
    supported,
    available,
    pushToTalkKey: PUSH_TO_TALK_KEY,
    startRecording,
    stopRecording,
    startListening: startRecording,
    stopListening: stopRecording,
    startPushToTalk: startRecording,
    stopPushToTalk: stopRecording,
    beginPushToTalk: startRecording,
    endPushToTalk: stopRecording,
    toggleRecording,
    toggleListening: toggleRecording,
    speak,
    speakText: speak,
    stopSpeaking,
    cancel,
    clearError,
    refreshStatus,
  };
}
