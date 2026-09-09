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

export type VoiceControllerState = VoicePhase;
export type VoiceState = VoicePhase;

export interface VoiceStatusResponse {
  enabled: boolean;
  platform_supported?: boolean;
  transcription_available?: boolean;
  synthesis_available?: boolean;
  stt_available?: boolean;
  tts_available?: boolean;
  stt_dependency_available?: boolean;
  tts_dependency_available?: boolean;
  tts_model_files_available?: boolean;
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

interface VoiceSettingsLike {
  enabled?: boolean;
  auto_speak?: boolean;
  verbal_approvals?: boolean;
  microphone_mode?: string;
  tts_voice?: string;
  tts_speed?: number;
  tts_language?: string;
}

interface VoiceStatusLike {
  enabled?: boolean;
  stt_dependency_available?: boolean;
  tts_dependency_available?: boolean;
  tts_model_files_available?: boolean;
  transcription_available?: boolean;
  synthesis_available?: boolean;
  stt_available?: boolean;
  tts_available?: boolean;
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

  // Current Phase 10B App.tsx passes these objects directly.
  settings?: VoiceSettingsLike | null;
  status?: VoiceStatusLike | null;

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
  canRecord: boolean;
  canSpeak: boolean;
  amplitude: number;

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
  speakSystem: (text: string) => void;

  beginResponse: (shouldSpeak: boolean) => void;
  ingestResponseToken: (token: string) => void;
  finishResponse: () => void;

  stopSpeaking: () => void;
  cancel: () => void;
  clearError: () => void;
  refreshStatus: () => Promise<VoiceStatusResponse | null>;
}

const MIN_RECORDING_MS = 350;
const MIN_AUDIO_BYTES = 1_000;
const RECORDER_TIMESLICE_MS = 250;
const FINAL_FLUSH_DELAY_MS = 75;

// Streamed TTS tuning. Jace begins speaking once a useful sentence-sized
// chunk has arrived rather than waiting for the complete model response.
const MIN_STREAM_CHUNK_CHARS = 24;
const MAX_STREAM_BUFFER_CHARS = 220;

// Updating React state at full audio-frame rate would unnecessarily re-render
// the whole desktop shell. ~22 FPS is smooth enough for the core visualisation.
const AMPLITUDE_UPDATE_INTERVAL_MS = 45;

interface SpeechQueueItem {
  text: string;
  generation: number;
}

let welcomeSpokenThisLaunch = false;

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function cleanSpeechText(text: string): string {
  return text
    .replace(/```[a-zA-Z0-9_-]*\s*/g, "")
    .replace(/```/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/[*_~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Pull complete speakable chunks from a streamed model buffer.
 *
 * Normal sentence punctuation is preferred. If the model produces a very long
 * clause without punctuation, a whitespace/comma boundary is used so the user
 * still hears a response promptly.
 */
function pullSpeechChunks(
  input: string,
  flushRemainder = false,
): { chunks: string[]; remainder: string } {
  const chunks: string[] = [];
  let remainder = input;
  let cursor = 0;
  const boundary = /[.!?]+["')\\]]?(?=\\s|$)/g;
  let match: RegExpExecArray | null;

  while ((match = boundary.exec(input)) !== null) {
    const end = match.index + match[0].length;
    const candidate = input.slice(cursor, end).trim();

    if (candidate.length >= MIN_STREAM_CHUNK_CHARS) {
      chunks.push(candidate);
      cursor = end;
    }
  }

  remainder = input.slice(cursor);

  while (remainder.trim().length > MAX_STREAM_BUFFER_CHARS) {
    const searchWindow = remainder.slice(0, MAX_STREAM_BUFFER_CHARS + 1);
    const commaBoundary = Math.max(
      searchWindow.lastIndexOf(", "),
      searchWindow.lastIndexOf("; "),
      searchWindow.lastIndexOf(": "),
    );
    const whitespaceBoundary = searchWindow.lastIndexOf(" ");

    const splitAt =
      commaBoundary >= MIN_STREAM_CHUNK_CHARS
        ? commaBoundary + 1
        : whitespaceBoundary >= MIN_STREAM_CHUNK_CHARS
          ? whitespaceBoundary
          : MAX_STREAM_BUFFER_CHARS;

    const candidate = remainder.slice(0, splitAt).trim();
    if (candidate) chunks.push(candidate);
    remainder = remainder.slice(splitAt).trimStart();
  }

  if (flushRemainder) {
    const tail = remainder.trim();
    if (tail) chunks.push(tail);
    remainder = "";
  }

  return { chunks, remainder };
}

function createAudioContext(): AudioContext | null {
  if (typeof AudioContext === "undefined") return null;

  try {
    return new AudioContext();
  } catch {
    return null;
  }
}

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

    return true;
  });
}

async function responseError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: unknown;
      message?: unknown;
    };

    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
    if (typeof body.message === "string" && body.message.trim()) return body.message;
  } catch {
    // Fall through to the status-based fallback below.
  }

  return `${fallback} (${response.status} ${response.statusText})`;
}

function releaseStream(stream: MediaStream | null): void {
  if (!stream) return;

  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch {
      // Best-effort cleanup.
    }
  }
}

function optionVoiceEnabled(options: UseVoiceControllerOptions): boolean {
  if (options.settings?.enabled !== undefined) return options.settings.enabled;
  if (options.enabled !== undefined) return options.enabled;
  return true;
}

function statusSttAvailable(status: VoiceStatusLike | VoiceStatusResponse | null | undefined): boolean | undefined {
  if (!status) return undefined;

  if (status.stt_dependency_available !== undefined) {
    return status.stt_dependency_available;
  }
  if (status.transcription_available !== undefined) {
    return status.transcription_available;
  }
  if (status.stt_available !== undefined) {
    return status.stt_available;
  }

  return undefined;
}

function statusTtsAvailable(status: VoiceStatusLike | VoiceStatusResponse | null | undefined): boolean | undefined {
  if (!status) return undefined;

  if (status.synthesis_available !== undefined) {
    return status.synthesis_available;
  }
  if (status.tts_available !== undefined) {
    return status.tts_available;
  }

  if (status.tts_dependency_available !== undefined) {
    if (status.tts_model_files_available !== undefined) {
      return status.tts_dependency_available && status.tts_model_files_available;
    }
    return status.tts_dependency_available;
  }

  return undefined;
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
  const [amplitude, setAmplitude] = useState(0);

  const phaseRef = useRef<VoicePhase>("idle");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingStartedAtRef = useRef<number | null>(null);
  const stoppingRef = useRef<Promise<string | null> | null>(null);
  const homeHeldRef = useRef(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const audioCompletionRef = useRef<(() => void) | null>(null);
  const speechFetchAbortRef = useRef<AbortController | null>(null);

  const meterContextRef = useRef<AudioContext | null>(null);
  const meterSourceRef = useRef<AudioNode | null>(null);
  const meterAnalyserRef = useRef<AnalyserNode | null>(null);
  const meterAnimationRef = useRef<number | null>(null);
  const lastAmplitudeEmitRef = useRef(0);

  const responseBufferRef = useRef("");
  const responseShouldSpeakRef = useRef(false);
  const responseGenerationRef = useRef(0);

  const speechGenerationRef = useRef(0);
  const speechQueueRef = useRef<SpeechQueueItem[]>([]);
  const speechWorkerRunningRef = useRef(false);

  const mountedRef = useRef(true);

  const setPhase = useCallback((next: VoicePhase) => {
    phaseRef.current = next;

    if (!mountedRef.current) return;

    setPhaseState(next);
    optionsRef.current.onStateChange?.(next);
    optionsRef.current.onListeningChange?.(next === "listening");
    optionsRef.current.onSpeakingChange?.(next === "speaking");
  }, []);

  const reportError = useCallback(
    (message: string) => {
      if (!mountedRef.current) return;

      setError(message);
      setPhase("error");
      optionsRef.current.onError?.(message);
    },
    [setPhase],
  );

  const clearError = useCallback(() => {
    if (!mountedRef.current) return;

    setError(null);
    if (phaseRef.current === "error") {
      setPhase("idle");
    }
  }, [setPhase]);

  const stopAmplitudeMeter = useCallback(() => {
    if (meterAnimationRef.current !== null) {
      cancelAnimationFrame(meterAnimationRef.current);
      meterAnimationRef.current = null;
    }

    try {
      meterSourceRef.current?.disconnect();
    } catch {
      // Best-effort graph cleanup.
    }

    try {
      meterAnalyserRef.current?.disconnect();
    } catch {
      // Best-effort graph cleanup.
    }

    meterSourceRef.current = null;
    meterAnalyserRef.current = null;

    const context = meterContextRef.current;
    meterContextRef.current = null;

    if (context && context.state !== "closed") {
      void context.close().catch(() => {
        // AudioContext cleanup is non-critical.
      });
    }

    lastAmplitudeEmitRef.current = 0;

    if (mountedRef.current) {
      setAmplitude(0);
    }
  }, []);

  const startAmplitudeMeter = useCallback(
    (
      context: AudioContext,
      source: AudioNode,
      analyser: AnalyserNode,
      connectToOutput: boolean,
      gainMultiplier: number,
    ) => {
      stopAmplitudeMeter();

      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.72;

      source.connect(analyser);

      if (connectToOutput) {
        analyser.connect(context.destination);
      }

      meterContextRef.current = context;
      meterSourceRef.current = source;
      meterAnalyserRef.current = analyser;

      const samples = new Uint8Array(analyser.fftSize);
      let smoothed = 0;
      let lastUpdateAt = 0;

      const tick = (time: number) => {
        if (
          !mountedRef.current ||
          meterAnalyserRef.current !== analyser ||
          meterContextRef.current !== context
        ) {
          return;
        }

        analyser.getByteTimeDomainData(samples);

        let sumSquares = 0;
        for (const sample of samples) {
          const centred = (sample - 128) / 128;
          sumSquares += centred * centred;
        }

        const rms = Math.sqrt(sumSquares / samples.length);
        const target = clamp01((rms - 0.006) * gainMultiplier);

        // Faster attack, slower release prevents a visually jittery core.
        smoothed =
          target > smoothed
            ? smoothed * 0.42 + target * 0.58
            : smoothed * 0.82 + target * 0.18;

        if (time - lastUpdateAt >= AMPLITUDE_UPDATE_INTERVAL_MS) {
          lastUpdateAt = time;

          const emitted = smoothed < 0.015 ? 0 : smoothed;
          if (Math.abs(emitted - lastAmplitudeEmitRef.current) >= 0.012) {
            lastAmplitudeEmitRef.current = emitted;
            setAmplitude(emitted);
          }
        }

        meterAnimationRef.current = requestAnimationFrame(tick);
      };

      meterAnimationRef.current = requestAnimationFrame(tick);
    },
    [stopAmplitudeMeter],
  );

  const stopCurrentAudio = useCallback(() => {
    speechFetchAbortRef.current?.abort();
    speechFetchAbortRef.current = null;

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

    const complete = audioCompletionRef.current;
    audioCompletionRef.current = null;
    complete?.();

    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }

    stopAmplitudeMeter();

    if (mountedRef.current && phaseRef.current === "speaking") {
      setPhase("idle");
    }
  }, [setPhase, stopAmplitudeMeter]);

  const stopSpeaking = useCallback(() => {
    // Incrementing the generation invalidates queued/in-flight speech without
    // affecting the text/model stream itself.
    speechGenerationRef.current += 1;
    responseGenerationRef.current = speechGenerationRef.current;
    responseShouldSpeakRef.current = false;
    responseBufferRef.current = "";
    speechQueueRef.current = [];

    stopCurrentAudio();
  }, [stopCurrentAudio]);

  const refreshStatus = useCallback(async (): Promise<VoiceStatusResponse | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/voice/status`);

      if (!response.ok) {
        throw new Error(
          await responseError(response, "Could not read Jace voice status"),
        );
      }

      const next = (await response.json()) as VoiceStatusResponse;

      if (mountedRef.current) {
        setStatus(next);
      }

      return next;
    } catch (statusError) {
      const message =
        statusError instanceof Error
          ? statusError.message
          : "Could not read Jace voice status.";

      // A status read failure must not take the whole app offline.
      if (mountedRef.current) {
        setError(message);
      }

      return null;
    }
  }, []);

  const synthesizeAndPlay = useCallback(
    async (text: string, generation: number): Promise<void> => {
      const value = cleanSpeechText(text);
      if (!value || generation !== speechGenerationRef.current) return;

      const fetchController = new AbortController();
      speechFetchAbortRef.current = fetchController;

      const response = await fetch(`${API_BASE_URL}/voice/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
        signal: fetchController.signal,
      });

      if (speechFetchAbortRef.current === fetchController) {
        speechFetchAbortRef.current = null;
      }

      if (generation !== speechGenerationRef.current) return;

      if (!response.ok) {
        throw new Error(
          await responseError(response, "Speech synthesis failed"),
        );
      }

      const blob = await response.blob();
      if (generation !== speechGenerationRef.current) return;

      if (!blob.size) {
        throw new Error("Speech synthesis returned an empty audio file.");
      }

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);

      audioRef.current = audio;
      audioUrlRef.current = url;

      if (mountedRef.current) {
        setError(null);
      }

      // Route TTS playback through an analyser so JaceCore receives the real
      // waveform level of Kokoro's generated speech.
      let playbackUsesAudioContext = false;
      const context = createAudioContext();

      if (context) {
        try {
          if (context.state === "suspended") {
            await context.resume();
          }

          const source = context.createMediaElementSource(audio);
          const analyser = context.createAnalyser();

          startAmplitudeMeter(context, source, analyser, true, 4.4);
          playbackUsesAudioContext = true;
        } catch (meterError) {
          console.debug("[Jace Voice] TTS analyser unavailable", meterError);

          if (context.state !== "closed") {
            void context.close().catch(() => {});
          }
        }
      }

      setPhase("speaking");

      try {
        await new Promise<void>((resolve, reject) => {
          let settled = false;

          const finish = () => {
            if (settled) return;
            settled = true;

            if (audioCompletionRef.current === finish) {
              audioCompletionRef.current = null;
            }

            resolve();
          };

          const fail = () => {
            if (settled) return;
            settled = true;

            if (audioCompletionRef.current === finish) {
              audioCompletionRef.current = null;
            }

            reject(new Error("Jace could not play the generated speech audio."));
          };

          audioCompletionRef.current = finish;
          audio.addEventListener("ended", finish, { once: true });
          audio.addEventListener("error", fail, { once: true });

          void audio.play().catch((playError: unknown) => {
            if (settled) return;
            settled = true;

            if (audioCompletionRef.current === finish) {
              audioCompletionRef.current = null;
            }

            reject(
              playError instanceof Error
                ? playError
                : new Error("Jace could not start speech playback."),
            );
          });
        });
      } finally {
        if (audioRef.current === audio) {
          audioRef.current = null;
        }

        if (audioUrlRef.current === url) {
          URL.revokeObjectURL(url);
          audioUrlRef.current = null;
        }

        // If Web Audio was unavailable the element played directly and there
        // is no meter to clean up.
        if (playbackUsesAudioContext) {
          stopAmplitudeMeter();
        }

        if (
          generation === speechGenerationRef.current &&
          phaseRef.current === "speaking"
        ) {
          setPhase("idle");
        }
      }
    },
    [setPhase, startAmplitudeMeter, stopAmplitudeMeter],
  );

  const runSpeechQueue = useCallback(async () => {
    if (speechWorkerRunningRef.current) return;

    speechWorkerRunningRef.current = true;

    try {
      while (mountedRef.current) {
        const item = speechQueueRef.current.shift();
        if (!item) break;

        if (item.generation !== speechGenerationRef.current) {
          continue;
        }

        try {
          await synthesizeAndPlay(item.text, item.generation);
        } catch (speechError) {
          if (
            item.generation !== speechGenerationRef.current ||
            isAbortError(speechError)
          ) {
            continue;
          }

          speechQueueRef.current = [];

          const message =
            speechError instanceof Error
              ? speechError.message
              : "Jace could not speak the response.";

          reportError(message);
          break;
        }
      }
    } finally {
      speechWorkerRunningRef.current = false;
    }
  }, [reportError, synthesizeAndPlay]);

  const queueSpeechChunks = useCallback(
    (chunks: string[], generation: number) => {
      for (const chunk of chunks) {
        const cleaned = cleanSpeechText(chunk);
        if (!cleaned) continue;

        speechQueueRef.current.push({
          text: cleaned,
          generation,
        });
      }

      if (speechQueueRef.current.length > 0) {
        void runSpeechQueue();
      }
    },
    [runSpeechQueue],
  );

  const speak = useCallback(
    async (text: string): Promise<void> => {
      const value = cleanSpeechText(text);
      if (!value) return;

      stopSpeaking();
      const generation = speechGenerationRef.current;

      try {
        await synthesizeAndPlay(value, generation);
      } catch (speakError) {
        if (
          generation !== speechGenerationRef.current ||
          isAbortError(speakError)
        ) {
          return;
        }

        const message =
          speakError instanceof Error
            ? speakError.message
            : "Jace could not speak the response.";

        reportError(message);
        throw speakError;
      }
    },
    [reportError, stopSpeaking, synthesizeAndPlay],
  );

  /**
   * Begin a streamed assistant response.
   *
   * Previous speech is interrupted immediately. If this turn should be spoken,
   * ingestResponseToken() will begin queueing sentence-sized TTS chunks as soon
   * as they are complete.
   */
  const beginResponse = useCallback(
    (shouldSpeak: boolean) => {
      stopSpeaking();

      const generation = speechGenerationRef.current;

      responseGenerationRef.current = generation;
      responseBufferRef.current = "";
      responseShouldSpeakRef.current = shouldSpeak;
    },
    [stopSpeaking],
  );

  const ingestResponseToken = useCallback(
    (token: string) => {
      if (!responseShouldSpeakRef.current || !token) return;

      const generation = responseGenerationRef.current;
      if (generation !== speechGenerationRef.current) return;

      responseBufferRef.current += token;

      const { chunks, remainder } = pullSpeechChunks(
        responseBufferRef.current,
        false,
      );

      responseBufferRef.current = remainder;

      if (chunks.length) {
        queueSpeechChunks(chunks, generation);
      }
    },
    [queueSpeechChunks],
  );

  const finishResponse = useCallback(() => {
    const shouldSpeak = responseShouldSpeakRef.current;
    const generation = responseGenerationRef.current;

    responseShouldSpeakRef.current = false;

    if (!shouldSpeak || generation !== speechGenerationRef.current) {
      responseBufferRef.current = "";
      return;
    }

    const { chunks } = pullSpeechChunks(responseBufferRef.current, true);
    responseBufferRef.current = "";

    if (chunks.length) {
      queueSpeechChunks(chunks, generation);
    }
  }, [queueSpeechChunks]);

  const speakSystem = useCallback(
    (text: string) => {
      const value = cleanSpeechText(text);
      if (!value) return;

      // Permission prompts and system announcements take priority over normal
      // assistant narration.
      responseShouldSpeakRef.current = false;
      responseBufferRef.current = "";

      void speak(value).catch(() => {
        // speak() already routes useful errors into Jace's UI.
      });
    },
    [speak],
  );

  const deliverTranscript = useCallback(async (text: string) => {
    const current = optionsRef.current;
    const handler =
      current.onSubmitTranscript ??
      current.onFinalTranscript ??
      current.onTranscript ??
      current.onTranscription ??
      current.onVoiceInput ??
      current.onText;

    if (handler) {
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
      throw new Error(
        await responseError(response, "Audio transcription failed"),
      );
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

    if (!optionVoiceEnabled(currentOptions)) return;
    if (currentOptions.disabled) return;
    if (currentOptions.online === false) return;
    if (currentOptions.isGenerating) return;
    if (recorderRef.current && recorderRef.current.state !== "inactive") return;

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      reportError(
        "Microphone recording is not supported by this Jace desktop runtime.",
      );
      return;
    }

    // Push-to-talk always interrupts current speech so Jace cannot transcribe
    // its own speaker output.
    stopSpeaking();

    if (mountedRef.current) {
      setError(null);
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });

      // Keep the stream reachable immediately so any later setup failure still
      // releases the microphone correctly.
      streamRef.current = stream;

      // Feed the live microphone level into JaceCore. Failure to create a Web
      // Audio analyser must never prevent recording/transcription.
      try {
        const context = createAudioContext();

        if (context) {
          if (context.state === "suspended") {
            await context.resume();
          }

          const source = context.createMediaStreamSource(stream);
          const analyser = context.createAnalyser();

          // Microphone RMS is normally lower than decoded TTS audio, so use a
          // slightly stronger normalisation multiplier.
          startAmplitudeMeter(context, source, analyser, false, 8.2);
        }
      } catch (meterError) {
        console.debug("[Jace Voice] microphone analyser unavailable", meterError);
        stopAmplitudeMeter();
      }

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
        const recorderError = (
          event as Event & { error?: DOMException }
        ).error;

        reportError(
          recorderError?.message || "The microphone recorder reported an error.",
        );
      });

      recorder.start(RECORDER_TIMESLICE_MS);

      console.debug("[Jace Voice] recorder started", {
        requestedMimeType: mimeType,
        recorderMimeType: recorder.mimeType,
      });

      setPhase("listening");
    } catch (recordError) {
      stopAmplitudeMeter();
      releaseStream(streamRef.current);
      streamRef.current = null;
      recorderRef.current = null;

      const message =
        recordError instanceof DOMException && recordError.name === "NotAllowedError"
          ? "Microphone access was denied. Allow microphone access for Jace, then try again."
          : recordError instanceof Error
            ? recordError.message
            : "Jace could not start the microphone.";

      reportError(message);
    }
  }, [
    reportError,
    setPhase,
    startAmplitudeMeter,
    stopAmplitudeMeter,
    stopSpeaking,
  ]);

  const stopRecording = useCallback(async (): Promise<string | null> => {
    if (stoppingRef.current) return stoppingRef.current;

    const recorder = recorderRef.current;
    const startedAt = recordingStartedAtRef.current;

    if (!recorder || recorder.state === "inactive") {
      stopAmplitudeMeter();
      releaseStream(streamRef.current);
      streamRef.current = null;
      recorderRef.current = null;
      recordingStartedAtRef.current = null;

      if (phaseRef.current === "listening") {
        setPhase("idle");
      }

      return null;
    }

    const task = (async (): Promise<string | null> => {
      try {
        const elapsedMs =
          startedAt == null ? 0 : performance.now() - startedAt;

        const blob = await new Promise<Blob>((resolve, reject) => {
          const handleStop = () => {
            try {
              const chunks = chunksRef.current.filter(
                (chunk) => chunk.size > 0,
              );

              const actualMimeType =
                chunks[0]?.type ||
                recorder.mimeType ||
                preferredAudioMimeType() ||
                "audio/webm";

              const finalBlob = new Blob(chunks, {
                type: actualMimeType,
              });

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
            // WebView2 can otherwise return only the WebM header on rapid stop.
            recorder.requestData();
          } catch {
            // The stop event remains authoritative.
          }

          window.setTimeout(() => {
            try {
              if (recorder.state !== "inactive") {
                recorder.stop();
              }
            } catch (stopError) {
              reject(stopError);
            }
          }, FINAL_FLUSH_DELAY_MS);
        });

        recorderRef.current = null;
        recordingStartedAtRef.current = null;
        stopAmplitudeMeter();
        releaseStream(streamRef.current);
        streamRef.current = null;

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

        // handleVoiceTranscript() may already have started generation by the
        // time it resolves. The runtime state in App.tsx will take over.
        setPhase("idle");
        return transcript;
      } catch (stopError) {
        recorderRef.current = null;
        recordingStartedAtRef.current = null;
        stopAmplitudeMeter();
        releaseStream(streamRef.current);
        streamRef.current = null;
        chunksRef.current = [];

        const message =
          stopError instanceof Error
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
  }, [
    deliverTranscript,
    reportError,
    setPhase,
    stopAmplitudeMeter,
    transcribeBlob,
  ]);

  const toggleRecording = useCallback(async () => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      await stopRecording();
    } else {
      await startRecording();
    }
  }, [startRecording, stopRecording]);

  const cancel = useCallback(() => {
    homeHeldRef.current = false;
    responseShouldSpeakRef.current = false;
    responseBufferRef.current = "";

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

    stopAmplitudeMeter();
    releaseStream(streamRef.current);
    streamRef.current = null;

    stopSpeaking();
    setPhase("idle");
  }, [setPhase, stopAmplitudeMeter, stopSpeaking]);

  // Physical Home key = push-to-talk.
  useEffect(() => {
    if (options.enableHomePushToTalk === false) return;

    function keyDown(event: KeyboardEvent) {
      if (event.code !== "Home" && event.key !== "Home") return;
      if (event.repeat || homeHeldRef.current) return;
      if (event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;

      const current = optionsRef.current;
      if (
        !optionVoiceEnabled(current) ||
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

  // Local startup greeting. It is never sent to the LLM and runs only once
  // per desktop launch.
  useEffect(() => {
    if (welcomeSpokenThisLaunch) return;
    if (options.speakWelcome === false) return;
    if (!optionVoiceEnabled(options)) return;
    if (options.disabled) return;
    if (options.online === false) return;

    let cancelled = false;

    const timer = window.setTimeout(() => {
      void (async () => {
        const currentStatus = await refreshStatus();
        if (cancelled || welcomeSpokenThisLaunch) return;

        const synthesisAvailable = statusTtsAvailable(currentStatus) ?? false;
        if (!synthesisAvailable) return;

        welcomeSpokenThisLaunch = true;

        const line =
          String(optionsRef.current.welcomeLine || "").trim() ||
          currentStatus?.welcome_line ||
          DEFAULT_VOICE_WELCOME_LINE;

        try {
          await speak(line);
        } catch {
          // speak() already reports a useful error.
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
    options.settings?.enabled,
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
      responseShouldSpeakRef.current = false;
      responseBufferRef.current = "";
      speechQueueRef.current = [];
      speechGenerationRef.current += 1;
      speechFetchAbortRef.current?.abort();
      speechFetchAbortRef.current = null;

      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          // Best effort.
        }
      }

      stopAmplitudeMeter();
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
      audioCompletionRef.current?.();
      audioCompletionRef.current = null;

      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
    };
  }, [refreshStatus, stopAmplitudeMeter]);

  const supported =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined";

  const voiceEnabled = optionVoiceEnabled(options);

  const sttAvailable =
    statusSttAvailable(options.status) ??
    statusSttAvailable(status) ??
    true;

  const ttsAvailable =
    statusTtsAvailable(options.status) ??
    statusTtsAvailable(status) ??
    false;

  const canRecord = Boolean(
    voiceEnabled &&
      !options.disabled &&
      options.online !== false &&
      supported &&
      sttAvailable,
  );

  const canSpeak = Boolean(
    voiceEnabled &&
      !options.disabled &&
      options.online !== false &&
      ttsAvailable,
  );

  const available = canRecord;

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
    canRecord,
    canSpeak,

    // Real microphone/TTS RMS level, normalised to 0..1 for JaceCore.
    amplitude,

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
    speakSystem,

    beginResponse,
    ingestResponseToken,
    finishResponse,

    stopSpeaking,
    cancel,
    clearError,
    refreshStatus,
  };
}
