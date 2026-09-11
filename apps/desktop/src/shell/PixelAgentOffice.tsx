import {
  useEffect,
  useRef,
  useState,
} from "react";
import type { OfficeWorker } from "../agents/useAgentOffice";
import { getAgentBubbleDescriptor } from "../agents/activity";
import { JacePixelOfficeEngine } from "../pixelOffice/engine";
import type { CameraState } from "../pixelOffice/types";
import "./PixelAgentOfficeCanvas.css";

interface BubblePosition {
  workerId: string;
  left: number;
  top: number;
  text: string;
  tone: "working" | "thinking" | "permission" | "success" | "error";
}

function readCamera(engine: JacePixelOfficeEngine): CameraState {
  // The office engine already owns the live camera transform. We only read it
  // here so the DOM speech bubbles track the pixel characters while panning,
  // zooming and camera-follow are active.
  return (engine as unknown as { camera: CameraState }).camera;
}

export function PixelAgentOffice(props: {
  workers: OfficeWorker[];
  selectedWorkerId: string | null;
  onSelectWorker: (workerId: string | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<JacePixelOfficeEngine | null>(null);
  const workersRef = useRef(props.workers);
  const selectWorkerRef = useRef(props.onSelectWorker);
  const selectedWorkerIdRef = useRef(props.selectedWorkerId);
  const [bubblePositions, setBubblePositions] =
    useState<BubblePosition[]>([]);

  useEffect(() => {
    workersRef.current = props.workers;
    engineRef.current?.syncWorkers(props.workers);
  }, [props.workers]);

  useEffect(() => {
    selectWorkerRef.current = props.onSelectWorker;
  }, [props.onSelectWorker]);

  useEffect(() => {
    selectedWorkerIdRef.current = props.selectedWorkerId;
    engineRef.current?.setSelected(props.selectedWorkerId);
  }, [props.selectedWorkerId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const engine = new JacePixelOfficeEngine(canvas);
    engineRef.current = engine;
    engine.syncWorkers(workersRef.current);
    engine.setSelected(selectedWorkerIdRef.current);
    engine.start();

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      engine.resize(
        rect.width,
        rect.height,
        window.devicePixelRatio || 1,
      );
    };

    resize();

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);

    let dragging = false;
    let moved = false;
    let lastX = 0;
    let lastY = 0;

    const pointerDown = (event: PointerEvent) => {
      dragging = true;
      moved = false;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
    };

    const pointerMove = (event: PointerEvent) => {
      const hit = engine.hitTest(event.clientX, event.clientY);
      engine.hoveredCharacterId = hit?.characterId ?? null;

      if (!dragging) return;

      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;

      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;

      engine.pan(dx, dy);
      lastX = event.clientX;
      lastY = event.clientY;
    };

    const pointerUp = (event: PointerEvent) => {
      if (canvas.hasPointerCapture(event.pointerId)) {
        canvas.releasePointerCapture(event.pointerId);
      }

      if (!moved) {
        const hit = engine.hitTest(event.clientX, event.clientY);

        if (hit?.characterId) {
          const nextSelected =
            engine.selectedCharacterId === hit.characterId
              ? null
              : hit.characterId;

          engine.setSelected(nextSelected);
          selectWorkerRef.current(nextSelected);
        } else {
          engine.setSelected(null);
          selectWorkerRef.current(null);
        }
      }

      dragging = false;
      moved = false;
    };

    const pointerLeave = () => {
      engine.hoveredCharacterId = null;
    };

    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      engine.zoomAt(event.clientX, event.clientY, event.deltaY);
    };

    const doubleClick = () => {
      engine.fitToRoom();
    };

    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", pointerUp);
    canvas.addEventListener("pointerleave", pointerLeave);
    canvas.addEventListener("wheel", wheel, { passive: false });
    canvas.addEventListener("dblclick", doubleClick);

    return () => {
      resizeObserver.disconnect();
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("pointercancel", pointerUp);
      canvas.removeEventListener("pointerleave", pointerLeave);
      canvas.removeEventListener("wheel", wheel);
      canvas.removeEventListener("dblclick", doubleClick);
      engine.dispose();
      engineRef.current = null;
    };
  }, []);

  useEffect(() => {
    let frame = 0;
    let lastUpdate = 0;

    const updateBubblePositions = (time: number) => {
      const engine = engineRef.current;
      const canvas = canvasRef.current;

      if (engine && canvas && time - lastUpdate >= 80) {
        lastUpdate = time;
        const camera = readCamera(engine);
        const rect = canvas.getBoundingClientRect();
        const now = Date.now();
        const next: BubblePosition[] = [];

        for (const character of engine.characters.values()) {
          const worker = workersRef.current.find(
            (candidate) => candidate.id === character.workerId,
          );
          const bubble = getAgentBubbleDescriptor(
            character.task,
            now,
            worker?.latestEvent,
          );
          if (!bubble) continue;

          const left = (character.x + camera.x) * camera.zoom;
          const top = (character.y - 31 + camera.y) * camera.zoom;

          if (
            left < -120 ||
            left > rect.width + 120 ||
            top < -60 ||
            top > rect.height + 60
          ) {
            continue;
          }

          next.push({
            workerId: character.workerId,
            left,
            top,
            text: bubble.text,
            tone: bubble.tone,
          });
        }

        setBubblePositions(next);
      }

      frame = window.requestAnimationFrame(updateBubblePositions);
    };

    frame = window.requestAnimationFrame(updateBubblePositions);

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div className="jace-canvas-office">
      <canvas
        ref={canvasRef}
        className="jace-canvas-office-surface"
        aria-label="Jace live office using Pixel Agents assets"
      />

      <div className="agent-bubble-layer" aria-hidden="true">
        {bubblePositions.map((bubble) => (
          <div
            key={bubble.workerId}
            className={`agent-speech-bubble ${bubble.tone}`}
            style={{
              left: `${bubble.left}px`,
              top: `${bubble.top}px`,
            }}
          >
            {bubble.text}
          </div>
        ))}
      </div>

      <div className="jace-canvas-office-actions">
        <span className="jace-pixel-assets-badge">PIXEL AGENTS</span>
        <button
          type="button"
          onClick={() => engineRef.current?.fitToRoom()}
          title="Fit whole office"
        >
          FIT
        </button>
        <button
          type="button"
          onClick={() => engineRef.current?.resetLayout()}
          title="Reset office layout"
        >
          RESET
        </button>
      </div>
    </div>
  );
}
