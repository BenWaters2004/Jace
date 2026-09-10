import {
  useEffect,
  useRef,
} from "react";
import type {
  OfficeWorker,
} from "../agents/useAgentOffice";
import {
  JacePixelOfficeEngine,
} from "../pixelOffice/engine";
import "./PixelAgentOfficeCanvas.css";

export function PixelAgentOffice(
  props: {
    workers:
      OfficeWorker[];
    selectedTaskId:
      string | null;
    onSelectTask:
      (
        taskId:
          string | null,
      ) => void;
  },
) {
  const canvasRef =
    useRef<
      HTMLCanvasElement |
      null
    >(null);

  const engineRef =
    useRef<
      JacePixelOfficeEngine |
      null
    >(null);

  const workersRef =
    useRef(
      props.workers,
    );

  const selectTaskRef =
    useRef(
      props.onSelectTask,
    );

  useEffect(
    () => {
      workersRef.current =
        props.workers;

      engineRef.current
        ?.syncWorkers(
          props.workers,
        );
    },
    [
      props.workers,
    ],
  );

  useEffect(
    () => {
      const engine =
        engineRef.current;

      if (!engine) {
        return;
      }

      const worker =
        workersRef.current.find(
          (candidate) =>
            candidate.task?.id ===
            props.selectedTaskId,
        );

      engine.setSelected(
        worker?.id ??
        null,
      );
    },
    [
      props.selectedTaskId,
    ],
  );

  useEffect(
    () => {
      selectTaskRef.current =
        props.onSelectTask;
    },
    [
      props.onSelectTask,
    ],
  );

  useEffect(
    () => {
      const canvas =
        canvasRef.current;

      if (!canvas) {
        return;
      }

      const engine =
        new JacePixelOfficeEngine(
          canvas,
        );

      engineRef.current =
        engine;

      engine.syncWorkers(
        workersRef.current,
      );

      engine.start();

      const resize =
        () => {
          const rect =
            canvas
              .getBoundingClientRect();

          engine.resize(
            rect.width,
            rect.height,
            window.devicePixelRatio ||
              1,
          );
        };

      resize();

      const resizeObserver =
        new ResizeObserver(
          resize,
        );

      resizeObserver.observe(
        canvas,
      );

      let dragging =
        false;

      let moved =
        false;

      let lastX = 0;
      let lastY = 0;

      const pointerDown =
        (
          event:
            PointerEvent,
        ) => {
          dragging =
            true;

          moved =
            false;

          lastX =
            event.clientX;

          lastY =
            event.clientY;

          canvas.setPointerCapture(
            event.pointerId,
          );
        };

      const pointerMove =
        (
          event:
            PointerEvent,
        ) => {
          const hit =
            engine.hitTest(
              event.clientX,
              event.clientY,
            );

          engine.hoveredCharacterId =
            hit
              ?.characterId ??
            null;

          if (
            !dragging
          ) {
            return;
          }

          const dx =
            event.clientX -
            lastX;

          const dy =
            event.clientY -
            lastY;

          if (
            Math.abs(dx) +
              Math.abs(dy) >
            2
          ) {
            moved =
              true;
          }

          engine.pan(
            dx,
            dy,
          );

          lastX =
            event.clientX;

          lastY =
            event.clientY;
        };

      const pointerUp =
        (
          event:
            PointerEvent,
        ) => {
          if (
            canvas
              .hasPointerCapture(
                event.pointerId,
              )
          ) {
            canvas
              .releasePointerCapture(
                event.pointerId,
              );
          }

          if (
            !moved
          ) {
            const hit =
              engine.hitTest(
                event.clientX,
                event.clientY,
              );

            if (
              hit
                ?.characterId
            ) {
              const character =
                engine.characters.get(
                  hit.characterId,
                );

              const nextSelected =
                engine.selectedCharacterId ===
                  hit.characterId
                  ? null
                  : hit.characterId;

              engine.setSelected(
                nextSelected,
              );

              selectTaskRef.current(
                nextSelected &&
                character
                  ?.taskId
                  ? character.taskId
                  : null,
              );
            } else {
              engine.setSelected(
                null,
              );

              selectTaskRef.current(
                null,
              );
            }
          }

          dragging =
            false;

          moved =
            false;
        };

      const pointerLeave =
        () => {
          engine.hoveredCharacterId =
            null;
        };

      const wheel =
        (
          event:
            WheelEvent,
        ) => {
          event.preventDefault();

          engine.zoomAt(
            event.clientX,
            event.clientY,
            event.deltaY,
          );
        };

      const doubleClick =
        () => {
          engine.fitToRoom();
        };

      canvas.addEventListener(
        "pointerdown",
        pointerDown,
      );

      canvas.addEventListener(
        "pointermove",
        pointerMove,
      );

      canvas.addEventListener(
        "pointerup",
        pointerUp,
      );

      canvas.addEventListener(
        "pointercancel",
        pointerUp,
      );

      canvas.addEventListener(
        "pointerleave",
        pointerLeave,
      );

      canvas.addEventListener(
        "wheel",
        wheel,
        {
          passive:
            false,
        },
      );

      canvas.addEventListener(
        "dblclick",
        doubleClick,
      );

      return () => {
        resizeObserver
          .disconnect();

        canvas.removeEventListener(
          "pointerdown",
          pointerDown,
        );

        canvas.removeEventListener(
          "pointermove",
          pointerMove,
        );

        canvas.removeEventListener(
          "pointerup",
          pointerUp,
        );

        canvas.removeEventListener(
          "pointercancel",
          pointerUp,
        );

        canvas.removeEventListener(
          "pointerleave",
          pointerLeave,
        );

        canvas.removeEventListener(
          "wheel",
          wheel,
        );

        canvas.removeEventListener(
          "dblclick",
          doubleClick,
        );

        engine.dispose();

        engineRef.current =
          null;
      };
    },
    [],
  );

  return (
    <div
      className={
        "jace-canvas-office"
      }
    >
      <div
        className={
          "jace-canvas-office-actions"
        }
      >
        <span
          className={
            "jace-pixel-assets-badge"
          }
        >
          PIXEL AGENTS
        </span>

        <button
          type="button"
          onClick={
            () =>
              engineRef.current
                ?.fitToRoom()
          }
          title={
            "Fit whole office"
          }
        >
          FIT
        </button>

        <button
          type="button"
          onClick={
            () =>
              engineRef.current
                ?.resetLayout()
          }
          title={
            "Reset office layout"
          }
        >
          RESET
        </button>
      </div>

      <canvas
        ref={
          canvasRef
        }
        className={
          "jace-canvas-office-surface"
        }
        aria-label={
          "Jace live office using Pixel Agents assets"
        }
      />
    </div>
  );
}
