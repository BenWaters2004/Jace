import { getCurrentWindow } from "@tauri-apps/api/window";

type ResizeDirection =
  | "North"
  | "NorthEast"
  | "East"
  | "SouthEast"
  | "South"
  | "SouthWest"
  | "West"
  | "NorthWest";

const HANDLES: Array<{
  direction: ResizeDirection;
  className: string;
}> = [
  { direction: "North", className: "north" },
  { direction: "NorthEast", className: "north-east" },
  { direction: "East", className: "east" },
  { direction: "SouthEast", className: "south-east" },
  { direction: "South", className: "south" },
  { direction: "SouthWest", className: "south-west" },
  { direction: "West", className: "west" },
  { direction: "NorthWest", className: "north-west" },
];

export function WindowResizeHandles(props: {
  enabled: boolean;
}) {
  if (!props.enabled) return null;

  return (
    <div className="window-resize-handles" aria-hidden="true">
      {HANDLES.map((handle) => (
        <div
          key={handle.direction}
          className={`window-resize-handle ${handle.className}`}
          onMouseDown={(event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            event.stopPropagation();
            void getCurrentWindow()
              .startResizeDragging(handle.direction)
              .catch(() => undefined);
          }}
        />
      ))}
    </div>
  );
}
