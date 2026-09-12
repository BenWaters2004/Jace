import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import type { JaceRuntimeState } from "./runtime";
import {
  JaceBoardEngine,
  type BoardVisualState,
  type JaceBoardSnapshot,
} from "./JaceBoardEngine";
import "./JaceCore.css";

const THINKING_SOUND_URL = new URL("../assets/assets_thinking.wav", import.meta.url).href;
const THINKING_SOUND_VOLUME = 0.3;

// Other Windows audio sessions are reduced to 18% of their existing app
// volume while Jace is talking. The native command remembers and restores
// each session's exact previous volume afterwards.
const SPEAKING_DUCK_FACTOR = 0.18;

// A short release delay prevents music/video volume pumping if streamed TTS
// has a tiny gap between two spoken chunks.
const SPEAKING_UNDUCK_DELAY_MS = 450;

// Refresh the ducking set while Jace is speaking so an audio session that
// appears mid-response (for example a browser video starting or a new track
// creating a fresh session) is also attenuated.
const SPEAKING_DUCK_REFRESH_MS = 900;

const STATE_LABELS: Record<JaceRuntimeState, string> = {
  offline: "OFFLINE",
  idle: "IDLE",
  listening: "LISTENING",
  transcribing: "THINKING",
  thinking: "THINKING",
  speaking: "SPEAKING",
  working: "THINKING",
  waiting_permission: "THINKING",
  warning: "ATTENTION",
};

function toBoardState(state: JaceRuntimeState): BoardVisualState {
  if (state === "listening") return "listening";
  if (state === "speaking") return "speaking";
  if (
    state === "thinking" ||
    state === "transcribing" ||
    state === "working" ||
    state === "waiting_permission"
  ) {
    return "thinking";
  }
  return "idle";
}

function dottedName(name: string) {
  const cleaned = (name || "JACE").replace(/[^a-z0-9]/gi, "").toUpperCase();
  if (/^[A-Z0-9]{2,10}$/.test(cleaned)) {
    return `${cleaned.split("").join(".")}.`;
  }
  return "J.A.C.E.";
}

function formatClock(date: Date) {
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

async function setNativeAudioDucking(enabled: boolean): Promise<void> {
  try {
    await invoke("set_system_audio_ducking", {
      enabled,
      factor: SPEAKING_DUCK_FACTOR,
    });
  } catch (error) {
    // Keep voice/visualisation functional even if native audio ducking is not
    // available (for example when this UI is opened in a normal web browser).
    console.debug("[Jace Audio] system ducking unavailable", error);
  }
}

export function JaceCore(props: {
  name: string;
  state: JaceRuntimeState;
  model: string;
  runtimeConnected: boolean;
  amplitude?: number;
  onExpand: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<JaceBoardEngine | null>(null);

  const thinkingAudioRef = useRef<HTMLAudioElement | null>(null);
  const thinkingShouldPlayRef = useRef(false);
  const latestStateRef = useRef<JaceRuntimeState>(props.state);
  const duckRequestRef = useRef(0);
  const unduckTimerRef = useRef<number | null>(null);
  const duckRefreshTimerRef = useRef<number | null>(null);

  const snapshotRef = useRef<JaceBoardSnapshot>({
    state: "idle",
    displayState: "IDLE",
    level: 0,
    alert: false,
    connected: props.runtimeConnected,
    label: dottedName(props.name),
  });

  const [clock, setClock] = useState(() => formatClock(new Date()));

  const snapshot = useMemo<JaceBoardSnapshot>(
    () => ({
      state: toBoardState(props.state),
      displayState: STATE_LABELS[props.state],
      level: Math.max(0, Math.min(1, props.amplitude ?? 0)),
      alert: props.state === "warning" || props.state === "offline",
      connected: props.runtimeConnected,
      label: dottedName(props.name),
    }),
    [props.state, props.amplitude, props.runtimeConnected, props.name],
  );

  snapshotRef.current = snapshot;
  latestStateRef.current = props.state;

  // Start the procedural ai-visualizer circuit board renderer.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const engine = new JaceBoardEngine({
      canvas,
      getSnapshot: () => snapshotRef.current,
      seed: 7,
    });

    engineRef.current = engine;
    engine.start();

    return () => {
      engine.destroy();
      engineRef.current = null;
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(
      () => setClock(formatClock(new Date())),
      1_000,
    );

    return () => window.clearInterval(timer);
  }, []);

  // Thinking audio is prepared once and kept for the lifetime of the visual
  // core. WebView2/browser autoplay policies can reject an audio.play() call
  // that occurs several seconds after the original Send/voice gesture, so we
  // proactively "unlock" the element on the first local user interaction.
  useEffect(() => {
    const audio = new Audio(THINKING_SOUND_URL);
    audio.loop = true;
    audio.preload = "auto";
    audio.volume = THINKING_SOUND_VOLUME;

    let unlocked = false;
    let priming = false;

    const stopAudio = (reset = true) => {
      audio.pause();

      if (reset) {
        try {
          audio.currentTime = 0;
        } catch {
          // Best-effort reset.
        }
      }
    };

    const tryPlay = async (reason: string) => {
      if (!thinkingShouldPlayRef.current) {
        return;
      }

      audio.loop = true;
      audio.muted = false;
      audio.volume = THINKING_SOUND_VOLUME;

      if (!audio.paused) {
        return;
      }

      try {
        await audio.play();
        unlocked = true;
        console.debug("[Jace Audio] thinking sound playing", {
          reason,
          url: THINKING_SOUND_URL,
        });
      } catch (error) {
        console.warn("[Jace Audio] thinking sound play was blocked", {
          reason,
          url: THINKING_SOUND_URL,
          error,
        });
      }
    };

    const primeFromGesture = () => {
      if (unlocked || priming) {
        if (thinkingShouldPlayRef.current) {
          void tryPlay("user-gesture");
        }
        return;
      }

      priming = true;

      const previousMuted = audio.muted;
      const previousVolume = audio.volume;

      // Muted playback is allowed by WebView/browser autoplay policy. Starting
      // and immediately pausing it inside the user's gesture unlocks later
      // audible playback when the model enters thinking asynchronously.
      audio.muted = true;
      audio.volume = 0;

      void audio
        .play()
        .then(() => {
          audio.pause();

          try {
            audio.currentTime = 0;
          } catch {
            // Best effort.
          }

          audio.muted = previousMuted;
          audio.volume = previousVolume;
          unlocked = true;
          priming = false;

          console.debug("[Jace Audio] thinking sound unlocked");

          if (thinkingShouldPlayRef.current) {
            void tryPlay("post-unlock");
          }
        })
        .catch((error) => {
          audio.muted = previousMuted;
          audio.volume = previousVolume;
          priming = false;

          console.debug("[Jace Audio] thinking sound unlock deferred", error);
        });
    };

    const handleCanPlay = () => {
      console.debug("[Jace Audio] thinking sound ready", THINKING_SOUND_URL);

      if (thinkingShouldPlayRef.current) {
        void tryPlay("canplay");
      }
    };

    const handlePlaying = () => {
      unlocked = true;
    };

    const handleError = () => {
      console.error(
        "[Jace Audio] thinking sound failed to load",
        THINKING_SOUND_URL,
        audio.error,
      );
    };

    audio.addEventListener("canplay", handleCanPlay);
    audio.addEventListener("playing", handlePlaying);
    audio.addEventListener("error", handleError);

    window.addEventListener("pointerdown", primeFromGesture, true);
    window.addEventListener("keydown", primeFromGesture, true);

    audio.load();
    thinkingAudioRef.current = audio;

    return () => {
      thinkingShouldPlayRef.current = false;
      stopAudio();

      window.removeEventListener("pointerdown", primeFromGesture, true);
      window.removeEventListener("keydown", primeFromGesture, true);

      audio.removeEventListener("canplay", handleCanPlay);
      audio.removeEventListener("playing", handlePlaying);
      audio.removeEventListener("error", handleError);

      audio.removeAttribute("src");
      audio.load();

      if (thinkingAudioRef.current === audio) {
        thinkingAudioRef.current = null;
      }
    };
  }, []);

  // Follow the same mapped state used by the ai-visualizer text scramble.
  // Transcribing, thinking, working and waiting_permission form one continuous
  // processing period; the WAV should not restart while Jace moves between
  // those internal states. Speaking always stops it immediately.
  const thinkingVisualActive = toBoardState(props.state) === "thinking";

  useEffect(() => {
    const audio = thinkingAudioRef.current;

    thinkingShouldPlayRef.current =
      thinkingVisualActive && props.state !== "speaking";

    if (!audio) {
      return;
    }

    if (!thinkingShouldPlayRef.current) {
      audio.pause();

      try {
        audio.currentTime = 0;
      } catch {
        // Best effort.
      }

      return;
    }

    audio.loop = true;
    audio.muted = false;
    audio.volume = THINKING_SOUND_VOLUME;

    if (!audio.paused) {
      return;
    }

    void audio.play().catch((error) => {
      // If WebView2 rejected this asynchronous play call, the gesture-unlock
      // listener above will retry the sound on the next user interaction.
      console.warn("[Jace Audio] thinking sound waiting for audio unlock", {
        state: props.state,
        url: THINKING_SOUND_URL,
        error,
      });
    });
  }, [props.state, thinkingVisualActive]);

  // Native Windows audio ducking. The Tauri backend lowers every non-Jace
  // audio session while speaking, then restores the exact session volumes.
  // The delayed release avoids volume bouncing between streamed TTS chunks.
  useEffect(() => {
    if (unduckTimerRef.current !== null) {
      window.clearTimeout(unduckTimerRef.current);
      unduckTimerRef.current = null;
    }

    if (duckRefreshTimerRef.current !== null) {
      window.clearInterval(duckRefreshTimerRef.current);
      duckRefreshTimerRef.current = null;
    }

    const requestId = ++duckRequestRef.current;

    if (props.state === "speaking") {
      const applyDucking = () => {
        void setNativeAudioDucking(true).then(() => {
          // Guard against an enable call finishing after speech already ended.
          if (
            requestId !== duckRequestRef.current ||
            latestStateRef.current !== "speaking"
          ) {
            void setNativeAudioDucking(false);
          }
        });
      };

      applyDucking();

      // A browser, Spotify, or media player can create a new audio-session
      // instance while a long Jace response is already playing. Re-scan at a
      // low frequency so those new sessions are ducked too. Existing sessions
      // are never multiplied down because Rust remembers their original level.
      duckRefreshTimerRef.current = window.setInterval(
        applyDucking,
        SPEAKING_DUCK_REFRESH_MS,
      );

      return () => {
        if (duckRefreshTimerRef.current !== null) {
          window.clearInterval(duckRefreshTimerRef.current);
          duckRefreshTimerRef.current = null;
        }
      };
    }

    unduckTimerRef.current = window.setTimeout(() => {
      if (
        requestId === duckRequestRef.current &&
        latestStateRef.current !== "speaking"
      ) {
        void setNativeAudioDucking(false);
      }
      unduckTimerRef.current = null;
    }, SPEAKING_UNDUCK_DELAY_MS);

    return () => {
      if (unduckTimerRef.current !== null) {
        window.clearTimeout(unduckTimerRef.current);
        unduckTimerRef.current = null;
      }
    };
  }, [props.state]);

  // Always restore other applications' audio if the visual core is unmounted
  // while Jace is speaking (for example during a hot reload or app shutdown).
  useEffect(() => {
    return () => {
      duckRequestRef.current += 1;

      if (unduckTimerRef.current !== null) {
        window.clearTimeout(unduckTimerRef.current);
        unduckTimerRef.current = null;
      }

      if (duckRefreshTimerRef.current !== null) {
        window.clearInterval(duckRefreshTimerRef.current);
        duckRefreshTimerRef.current = null;
      }

      void setNativeAudioDucking(false);
    };
  }, []);

  return (
    <section
      className={`cc-panel jace-core-panel jace-ai-visualizer state-${props.state}`}
      aria-label={`${props.name} neural link ${STATE_LABELS[props.state]}`}
      onDoubleClick={props.onExpand}
      onKeyDown={(event: ReactKeyboardEvent<HTMLElement>) => {
        if (event.key === " " || event.key === "c" || event.key === "C") {
          event.preventDefault();
          engineRef.current?.toggleCinematic();
        }

        if (event.key === "f" || event.key === "F") {
          event.preventDefault();
          props.onExpand();
        }
      }}
      tabIndex={0}
    >
      <canvas ref={canvasRef} className="jace-av-stage" />
      <div className="jace-av-vignette" />

      <div className="jace-av-hud" aria-hidden="true">
        <span className="jace-av-corner tl" />
        <span className="jace-av-corner tr" />
        <span className="jace-av-corner bl" />
        <span className="jace-av-corner br" />
        <span className="jace-av-square tl" />
        <span className="jace-av-square tr" />

        <div className="jace-av-brand">
          <div className="jace-av-brand-title">{dottedName(props.name)}</div>
          <div className="jace-av-brand-sub">
            NEURAL LINK - <b>{props.runtimeConnected ? "CONNECTED" : "FALLBACK"}</b>
          </div>
        </div>

        <div className="jace-av-status">
          <div className="jace-av-state">
            {STATE_LABELS[props.state]}
            {(props.state === "thinking" ||
              props.state === "working" ||
              props.state === "transcribing" ||
              props.state === "waiting_permission") && (
              <span className="jace-av-spinner" />
            )}
          </div>
          <div className="jace-av-clock">{clock}</div>
          <div
            className={`jace-av-orb ${
              props.state === "warning" || props.state === "offline"
                ? "alert"
                : ""
            }`}
          />
        </div>

        <div className="jace-av-bus">
          SIGNAL BUS - <span>{props.runtimeConnected ? "ONLINE" : "LOCAL"}</span>
        </div>

        <div className="jace-av-hint">
          {props.state === "thinking" ||
          props.state === "working" ||
          props.state === "transcribing" ||
          props.state === "waiting_permission"
            ? "PROCESSING..."
            : "SPACE - CINEMATIC FLYTHROUGH"}
        </div>
      </div>

      <button
        className="jace-av-focus-button"
        onClick={props.onExpand}
        title="Focus Jace visualizer"
        aria-label="Focus Jace visualizer"
      >
        □
      </button>
    </section>
  );
}
