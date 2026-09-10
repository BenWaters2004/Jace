import {
  useEffect,
  useRef,
} from "react";
import type { OfficeWorker } from "../agents/useAgentOffice";
import { JacePixelOfficeEngine } from "../pixelOffice/engine";
import "./PixelAgentOfficeCanvas.css";

export function PixelAgentOffice(props: {
  workers: OfficeWorker[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const engineRef = useRef<JacePixelOfficeEngine | null>(null);
  const workersRef = useRef(props.workers);

  useEffect(() => {
    workersRef.current = props.workers;
    engineRef.current?.syncWorkers(props.workers);
  }, [props.workers]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const engine = new JacePixelOfficeEngine(canvas);
    engineRef.current = engine;

    engine.syncWorkers(workersRef.current);
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

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let moved = false;

    const pointerDown = (event: PointerEvent) => {
      dragging = true;
      moved = false;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
    };

    const pointerMove = (event: PointerEvent) => {
      const hit = engine.hitTest(event.clientX, event.clientY);
      engine.hoveredCharacterId =
        hit?.type === "character" ? hit.id : null;

      if (!dragging) return;

      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;

      if (Math.abs(dx) + Math.abs(dy) > 2) {
        moved = true;
      }

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

        if (hit?.type === "character") {
          const character = engine.characters.get(hit.id);

          engine.setSelected(
            engine.selectedCharacterId === hit.id
              ? null
              : hit.id,
          );

          props.onSelectTask(
            character?.taskId
              ? character.taskId === props.selectedTaskId
                ? null
                : character.taskId
              : null,
          );
        } else {
          engine.setSelected(null);
          props.onSelectTask(null);
        }
      }

      dragging = false;
      moved = false;
    };

    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      engine.zoomAt(
        event.clientX,
        event.clientY,
        event.deltaY,
      );
    };

    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", pointerUp);
    canvas.addEventListener("wheel", wheel, { passive: false });

    return () => {
      observer.disconnect();
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("pointercancel", pointerUp);
      canvas.removeEventListener("wheel", wheel);
      engine.dispose();
      engineRef.current = null;
    };
  }, [props.onSelectTask, props.selectedTaskId]);

  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;

    const worker = props.workers.find(
      (candidate) =>
        candidate.task?.id === props.selectedTaskId,
    );

    if (!worker) {
      engine.setSelected(null);
      return;
    }

    engine.setSelected(worker.id);
  }, [props.selectedTaskId, props.workers]);

  return (
    <div className="jace-canvas-office">
      <canvas
        ref={canvasRef}
        className="jace-canvas-office-surface"
        aria-label="Jace live agent office"
      />
    </div>
  );
}
