import type {
  OfficeWorker,
} from "../agents/useAgentOffice";
import type {
  AgentTask,
} from "../agents/types";
import {
  SPECIALIST_CHARACTER_INDEX,
} from "./assets";
import {
  buildBlockedTiles,
  buildWallTiles,
  collectWalkableTiles,
  findPath,
  loadOfficeLayout,
  OFFICE_CAMERA_STORAGE_KEY,
  resetOfficeLayout,
  TILE_SIZE,
  tileBottomCenter,
  WALL_TINT,
} from "./layout";
import {
  PixelSpriteLibrary,
} from "./spriteLibrary";
import type {
  CameraState,
  CarpetZone,
  CharacterMode,
  FurniturePlacement,
  OfficeCharacter,
  OfficeDirection,
  OfficeHit,
  OfficeLayoutConfig,
  OfficePet,
  OfficePoint,
  OfficeRoomZone,
  OfficeSeat,
} from "./types";

const WALK_SPEED = 42;
const PET_WALK_SPEED = 31;

const WALK_FRAME_SECONDS =
  0.14;

const WORK_FRAME_SECONDS =
  0.28;

const PET_FRAME_SECONDS =
  0.22;

const WANDER_MIN_SECONDS =
  2.8;

const WANDER_MAX_SECONDS =
  6.8;

const PET_IDLE_MIN_SECONDS =
  2.2;

const PET_IDLE_MAX_SECONDS =
  5.2;

const TERMINAL_BUBBLE_SECONDS =
  4.5;

const READING_TOOLS =
  new Set([
    "web_search",
    "read_web_page",
    "browser_read_page",
    "search_memory",
    "search_conversations",
    "list_computer_workspaces",
    "list_workspace_files",
    "read_workspace_file",
    "search_workspace_files",
    "workspace_file_info",
    "inspect_workspace_media",
  ]);

interface Renderable {
  depth: number;
  render: () => void;
}

function randomRange(
  min: number,
  max: number,
) {
  return (
    min +
    Math.random() *
      (max - min)
  );
}

function randomItem<T>(
  items: T[],
): T {
  return items[
    Math.floor(
      Math.random() *
        items.length,
    )
  ];
}

function directionBetween(
  fromCol: number,
  fromRow: number,
  toCol: number,
  toRow: number,
): OfficeDirection {
  if (toCol > fromCol) {
    return "right";
  }

  if (toCol < fromCol) {
    return "left";
  }

  if (toRow > fromRow) {
    return "down";
  }

  return "up";
}

function extractCurrentTool(
  task: AgentTask | null,
): string | null {
  if (!task) {
    return null;
  }

  const activity =
    task.progress_message
      ?.trim() ?? "";

  const match =
    /^Using\s+(.+)$/i.exec(
      activity,
    );

  if (match?.[1]) {
    return match[1].trim();
  }

  if (
    task.used_tools.length >
    0
  ) {
    return task.used_tools[
      task.used_tools.length -
        1
    ];
  }

  return null;
}

function taskMode(
  task: AgentTask | null,
): CharacterMode {
  if (!task) {
    return "idle";
  }

  switch (task.status) {
    case "queued":
      return "queued";

    case "running":
      return "type";

    case "thinking":
      return "think";

    case "waiting_permission":
      return "wait";

    case "completed":
      return "complete";

    case "failed":
      return "failed";

    case "cancelled":
      return "idle";

    case "using_tool": {
      const tool =
        extractCurrentTool(
          task,
        );

      if (
        tool &&
        (
          READING_TOOLS.has(
            tool,
          ) ||
          tool.includes("read") ||
          tool.includes("search") ||
          tool.includes("list")
        )
      ) {
        return "read";
      }

      return "type";
    }

    default:
      return "idle";
  }
}

function bubbleText(
  character:
    OfficeCharacter,
): string | null {
  if (
    character.mode === "queued"
  ) {
    return "QUEUED";
  }

  if (
    character.mode === "think"
  ) {
    return "THINKING";
  }

  if (
    character.mode === "wait"
  ) {
    return "PERMISSION";
  }

  if (
    character.mode ===
      "complete"
  ) {
    return (
      character.bubbleTimer >
      0
        ? "DONE"
        : null
    );
  }

  if (
    character.mode === "failed"
  ) {
    return (
      character.bubbleTimer >
      0
        ? "FAILED"
        : null
    );
  }

  if (
    character.mode === "read"
  ) {
    const tool =
      character.currentTool
        ?.toLowerCase() ?? "";

    if (
      tool.includes("web")
    ) {
      return "WEB";
    }

    if (
      tool.includes("memory")
    ) {
      return "MEMORY";
    }

    if (
      tool.includes(
        "conversation",
      )
    ) {
      return "HISTORY";
    }

    if (
      tool.includes(
        "workspace",
      )
    ) {
      return "FILES";
    }

    return "READING";
  }

  if (
    character.mode === "type"
  ) {
    const tool =
      character.currentTool
        ?.toLowerCase() ?? "";

    if (
      tool.includes("command")
    ) {
      return "TERMINAL";
    }

    if (
      tool.includes("write")
    ) {
      return "WRITING";
    }

    if (
      tool.includes("replace")
    ) {
      return "EDITING";
    }

    if (
      tool.includes("move")
    ) {
      return "MOVING";
    }

    if (
      tool.includes("delete")
    ) {
      return "DELETING";
    }

    return (
      character.taskId
        ? "WORKING"
        : null
    );
  }

  return null;
}

function loadCamera():
  CameraState {
  try {
    const raw =
      window.localStorage
        .getItem(
          OFFICE_CAMERA_STORAGE_KEY,
        );

    if (raw) {
      const parsed =
        JSON.parse(
          raw,
        ) as Partial<CameraState>;

      if (
        typeof parsed.x ===
          "number" &&
        typeof parsed.y ===
          "number" &&
        typeof parsed.zoom ===
          "number"
      ) {
        return {
          x: parsed.x,
          y: parsed.y,
          zoom:
            Math.max(
              0.5,
              Math.min(
                6,
                parsed.zoom,
              ),
            ),
        };
      }
    }
  } catch {
    // Best-effort persistence.
  }

  return {
    x: 0,
    y: 0,
    zoom: 1,
  };
}

function characterSpriteIndex(
  worker: OfficeWorker,
): number {
  if (
    worker.overflowIndex >
    0
  ) {
    return 5;
  }

  return (
    SPECIALIST_CHARACTER_INDEX[
      worker.definition.id
    ] ??
    5
  );
}

export class JacePixelOfficeEngine {
  readonly characters =
    new Map<
      string,
      OfficeCharacter
    >();

  readonly pet:
    OfficePet;

  selectedCharacterId:
    string | null = null;

  hoveredCharacterId:
    string | null = null;

  cameraFollowId:
    string | null = null;

  private readonly canvas:
    HTMLCanvasElement;

  private readonly ctx:
    CanvasRenderingContext2D;

  private readonly sprites =
    new PixelSpriteLibrary();

  private layout:
    OfficeLayoutConfig;

  private blocked:
    Set<string>;

  private wallTiles:
    Set<string>;

  private walkableTiles:
    OfficePoint[];

  private petWalkableTiles:
    OfficePoint[];

  private camera:
    CameraState =
      loadCamera();

  private animationFrame:
    number | null = null;

  private lastTime = 0;
  private worldTime = 0;
  private disposed = false;

  private resizeObserver:
    ResizeObserver | null = null;

  private resizeFrame:
    number | null = null;

  private lastViewportWidth = 0;
  private lastViewportHeight = 0;
  private resizeListenersAttached = false;

  private readonly handleViewportChange = () => {
    this.scheduleCanvasResize();
  };

  private readonly handleFullscreenChange = () => {
    // Fullscreen transitions often update layout over more than one frame.
    // Resize immediately, then re-check after the surrounding UI settles.
    this.scheduleCanvasResize();

    window.setTimeout(
      () =>
        this.scheduleCanvasResize(),
      50,
    );

    window.setTimeout(
      () =>
        this.scheduleCanvasResize(),
      200,
    );
  };

  constructor(
    canvas:
      HTMLCanvasElement,
  ) {
    const ctx =
      canvas.getContext(
        "2d",
        {
          alpha: false,
        },
      );

    if (!ctx) {
      throw new Error(
        "Could not initialise the Jace Pixel Agents canvas.",
      );
    }

    this.canvas =
      canvas;

    // The CSS size should always follow the available panel. The bitmap size
    // is managed independently in resize() using the current DPR.
    this.canvas.style.display =
      "block";

    this.canvas.style.width =
      "100%";

    this.canvas.style.height =
      "100%";

    this.canvas.style.minWidth =
      "0";

    this.canvas.style.minHeight =
      "0";

    this.canvas.style.maxWidth =
      "none";

    this.canvas.style.maxHeight =
      "none";

    this.ctx =
      ctx;

    this.layout =
      loadOfficeLayout();

    this.wallTiles =
      buildWallTiles(
        this.layout,
      );

    this.blocked =
      buildBlockedTiles(
        this.layout,
      );

    this.walkableTiles =
      collectWalkableTiles(
        this.layout,
        this.blocked,
      );

    this.petWalkableTiles =
      collectWalkableTiles(
        this.layout,
        this.blocked,
        [
          "office",
          "break",
          "lounge",
        ],
      );

    const petSpawn =
      this.petWalkableTiles
        .find(
          (tile) =>
            tile.col >=
              17 &&
            tile.col <=
              19 &&
            tile.row >=
              16 &&
            tile.row <=
              18,
        ) ??
      this.petWalkableTiles[
        0
      ] ?? {
        col: 18,
        row: 17,
      };

    const petPoint =
      tileBottomCenter(
        petSpawn.col,
        petSpawn.row,
      );

    this.pet = {
      id:
        "jace-office-pet",
      assetId:
        "gitcat",
      name:
        "Gitcat",
      direction:
        "down",
      x:
        petPoint.x,
      y:
        petPoint.y,
      tileCol:
        petSpawn.col,
      tileRow:
        petSpawn.row,
      path:
        [],
      moveProgress:
        0,
      frame:
        0,
      frameTimer:
        0,
      idleTimer:
        randomRange(
          PET_IDLE_MIN_SECONDS,
          PET_IDLE_MAX_SECONDS,
        ),
      mode:
        "idle",
      allowedRoomIds: [
        "office",
        "break",
        "lounge",
      ],
    };

    void this.sprites.load();
  }

  start() {
    if (
      this.animationFrame !==
      null
    ) {
      return;
    }

    // Allow the same engine instance to be restarted if React temporarily
    // hides/unmounts the office during a fullscreen transition.
    this.disposed =
      false;

    this.attachResizeTracking();
    this.scheduleCanvasResize();

    this.lastTime =
      performance.now();

    const tick =
      (time: number) => {
        if (
          this.disposed
        ) {
          return;
        }

        const dt =
          Math.min(
            (
              time -
              this.lastTime
            ) /
              1000,
            0.08,
          );

        this.lastTime =
          time;

        this.worldTime +=
          dt;

        this.update(dt);
        this.render();

        this.animationFrame =
          window.requestAnimationFrame(
            tick,
          );
      };

    this.animationFrame =
      window.requestAnimationFrame(
        tick,
      );
  }

  dispose() {
    this.disposed =
      true;

    this.detachResizeTracking();

    if (
      this.resizeFrame !==
      null
    ) {
      window.cancelAnimationFrame(
        this.resizeFrame,
      );

      this.resizeFrame =
        null;
    }

    if (
      this.animationFrame !==
      null
    ) {
      window.cancelAnimationFrame(
        this.animationFrame,
      );

      this.animationFrame =
        null;
    }

    try {
      window.localStorage.setItem(
        OFFICE_CAMERA_STORAGE_KEY,
        JSON.stringify(
          this.camera,
        ),
      );
    } catch {
      // Best-effort persistence.
    }

    this.characters.clear();
  }

  private attachResizeTracking() {
    if (
      this.resizeListenersAttached
    ) {
      return;
    }

    const target =
      this.canvas.parentElement ??
      this.canvas;

    if (
      typeof ResizeObserver !==
      "undefined"
    ) {
      this.resizeObserver =
        new ResizeObserver(
          () => {
            this.scheduleCanvasResize();
          },
        );

      this.resizeObserver.observe(
        target,
      );
    }

    window.addEventListener(
      "resize",
      this.handleViewportChange,
    );

    document.addEventListener(
      "fullscreenchange",
      this.handleFullscreenChange,
    );

    this.resizeListenersAttached =
      true;
  }

  private detachResizeTracking() {
    if (
      !this.resizeListenersAttached
    ) {
      return;
    }

    this.resizeObserver?.disconnect();
    this.resizeObserver =
      null;

    window.removeEventListener(
      "resize",
      this.handleViewportChange,
    );

    document.removeEventListener(
      "fullscreenchange",
      this.handleFullscreenChange,
    );

    this.resizeListenersAttached =
      false;
  }

  private scheduleCanvasResize() {
    if (
      this.disposed
    ) {
      return;
    }

    if (
      this.resizeFrame !==
      null
    ) {
      window.cancelAnimationFrame(
        this.resizeFrame,
      );
    }

    this.resizeFrame =
      window.requestAnimationFrame(
        () => {
          this.resizeFrame =
            null;

          this.resizeFromContainer();
        },
      );
  }

  private resizeFromContainer() {
    const target =
      this.canvas.parentElement ??
      this.canvas;

    const rect =
      target.getBoundingClientRect();

    // A different Jace section can temporarily hide the office while that
    // section is fullscreen. Ignore the resulting 0x0 measurement so the
    // canvas is not destroyed and can recover when the office is visible.
    if (
      rect.width <= 1 ||
      rect.height <= 1
    ) {
      return;
    }

    this.resize(
      rect.width,
      rect.height,
      window.devicePixelRatio ||
        1,
    );
  }

  refreshViewport() {
    this.scheduleCanvasResize();
  }

  resize(
    width: number,
    height: number,
    dpr: number,
  ) {
    if (
      !Number.isFinite(width) ||
      !Number.isFinite(height) ||
      width <= 1 ||
      height <= 1
    ) {
      return;
    }

    const safeDpr =
      Number.isFinite(dpr) &&
      dpr > 0
        ? dpr
        : 1;

    const pixelWidth =
      Math.max(
        1,
        Math.floor(
          width *
            safeDpr,
        ),
      );

    const pixelHeight =
      Math.max(
        1,
        Math.floor(
          height *
            safeDpr,
        ),
      );

    const viewportChanged =
      Math.abs(
        width -
          this.lastViewportWidth,
      ) > 0.5 ||
      Math.abs(
        height -
          this.lastViewportHeight,
      ) > 0.5;

    if (
      this.canvas.width !==
        pixelWidth ||
      this.canvas.height !==
        pixelHeight
    ) {
      this.canvas.width =
        pixelWidth;

      this.canvas.height =
        pixelHeight;
    }

    if (viewportChanged) {
      this.lastViewportWidth =
        width;

      this.lastViewportHeight =
        height;

      this.fitToRoom(
        width,
        height,
      );
    }
  }

  resetLayout() {
    this.layout =
      resetOfficeLayout();

    this.wallTiles =
      buildWallTiles(
        this.layout,
      );

    this.blocked =
      buildBlockedTiles(
        this.layout,
      );

    this.walkableTiles =
      collectWalkableTiles(
        this.layout,
        this.blocked,
      );

    this.petWalkableTiles =
      collectWalkableTiles(
        this.layout,
        this.blocked,
        this.pet
          .allowedRoomIds,
      );

    for (
      const character
      of this.characters.values()
    ) {
      character.path =
        [];

      character.moveProgress =
        0;
    }

    this.pet.path =
      [];

    this.pet.moveProgress =
      0;

    const rect =
      this.canvas
        .getBoundingClientRect();

    this.fitToRoom(
      rect.width,
      rect.height,
    );
  }

  fitToRoom(
    width?: number,
    height?: number,
  ) {
    const rect =
      this.canvas
        .getBoundingClientRect();

    const viewportWidth =
      width ??
      rect.width;

    const viewportHeight =
      height ??
      rect.height;

    if (
      viewportWidth <= 1 ||
      viewportHeight <= 1
    ) {
      return;
    }

    // Pixel Agents' default layout contains intentional VOID space above the
    // visible office. Frame the occupied room bounds rather than the entire
    // 21x22 storage grid so the office actually fills the available panel.
    const minCol =
      Math.min(
        ...this.layout.rooms.map(
          (room) =>
            room.col,
        ),
      );

    const minRow =
      Math.min(
        ...this.layout.rooms.map(
          (room) =>
            room.row,
        ),
      );

    const maxCol =
      Math.max(
        ...this.layout.rooms.map(
          (room) =>
            room.col +
            room.width,
        ),
      );

    const maxRow =
      Math.max(
        ...this.layout.rooms.map(
          (room) =>
            room.row +
            room.height,
        ),
      );

    const paddingX =
      TILE_SIZE;

    // Extra top space keeps 32px wall sprites and wall-mounted decor visible.
    const paddingTop =
      TILE_SIZE *
      2;

    const paddingBottom =
      TILE_SIZE;

    const worldLeft =
      Math.max(
        0,
        minCol *
          TILE_SIZE -
          paddingX,
      );

    const worldTop =
      Math.max(
        0,
        minRow *
          TILE_SIZE -
          paddingTop,
      );

    const worldRight =
      Math.min(
        this.layout.cols *
          TILE_SIZE,
        maxCol *
          TILE_SIZE +
          paddingX,
      );

    const worldBottom =
      Math.min(
        this.layout.rows *
          TILE_SIZE,
        maxRow *
          TILE_SIZE +
          paddingBottom,
      );

    const worldWidth =
      Math.max(
        TILE_SIZE,
        worldRight -
          worldLeft,
      );

    const worldHeight =
      Math.max(
        TILE_SIZE,
        worldBottom -
          worldTop,
      );

    const zoom =
      Math.max(
        0.5,
        Math.min(
          6,
          Math.min(
            viewportWidth /
              worldWidth,
            viewportHeight /
              worldHeight,
          ) *
            0.96,
        ),
      );

    const worldCentreX =
      worldLeft +
      worldWidth /
        2;

    const worldCentreY =
      worldTop +
      worldHeight /
        2;

    this.camera.zoom =
      zoom;

    this.camera.x =
      viewportWidth /
        (
          2 *
          zoom
        ) -
      worldCentreX;

    this.camera.y =
      viewportHeight /
        (
          2 *
          zoom
        ) -
      worldCentreY;

    this.cameraFollowId =
      null;
  }

  private seatForWorker(
    worker:
      OfficeWorker,
  ): OfficeSeat {
    if (
      worker.overflowIndex >
      0
    ) {
      const overflow =
        this.layout.seats
          .find(
            (seat) =>
              seat.id ===
              `overflow-${Math.min(
                worker.overflowIndex,
                3,
              )}`,
          );

      if (overflow) {
        return overflow;
      }
    }

    return (
      this.layout.seats
        .find(
          (seat) =>
            seat.specialist ===
            worker.definition.id,
        ) ??
      this.layout.seats[0]
    );
  }

  syncWorkers(
    workers:
      OfficeWorker[],
  ) {
    const keep =
      new Set<string>();

    workers.forEach(
      (
        worker,
        index,
      ) => {
        keep.add(
          worker.id,
        );

        const seat =
          this.seatForWorker(
            worker,
          );

        let character =
          this.characters.get(
            worker.id,
          );

        if (!character) {
          const spawn =
            this.walkableTiles[
              Math.floor(
                Math.random() *
                  this.walkableTiles.length,
              )
            ] ?? {
              col:
                4 +
                index,
              row:
                15,
            };

          const centre =
            tileBottomCenter(
              spawn.col,
              spawn.row,
            );

          character = {
            id:
              worker.id,
            workerId:
              worker.id,
            specialistId:
              worker.definition.id,
            spriteIndex:
              characterSpriteIndex(
                worker,
              ),
            label:
              worker.definition.name,
            accent:
              worker.definition.accent,
            mode:
              "idle",
            desiredMode:
              "idle",
            direction:
              "down",
            x:
              centre.x,
            y:
              centre.y,
            tileCol:
              spawn.col,
            tileRow:
              spawn.row,
            path:
              [],
            moveProgress:
              0,
            frame:
              0,
            frameTimer:
              0,
            idleTimer:
              randomRange(
                WANDER_MIN_SECONDS,
                WANDER_MAX_SECONDS,
              ),
            bubbleTimer:
              0,
            seatId:
              seat.id,
            taskId:
              null,
            taskTitle:
              "",
            activity:
              "Standing by",
            currentTool:
              null,
            progress:
              0,
            task:
              null,
          };

          this.characters.set(
            worker.id,
            character,
          );
        }

        const previousTaskId =
          character.taskId;

        const previousDesired =
          character.desiredMode;

        character.specialistId =
          worker.definition.id;

        character.spriteIndex =
          characterSpriteIndex(
            worker,
          );

        character.label =
          worker.definition.name;

        character.accent =
          worker.definition.accent;

        character.seatId =
          seat.id;

        character.task =
          worker.task;

        character.taskId =
          worker.task?.id ??
          null;

        character.taskTitle =
          worker.task?.title ??
          "";

        character.activity =
          worker.task
            ?.progress_message ??
          (
            worker.task
              ? worker.task
                  .status
                  .replace(
                    /_/g,
                    " ",
                  )
              : "Standing by"
          );

        character.currentTool =
          extractCurrentTool(
            worker.task,
          );

        character.progress =
          worker.task
            ?.progress ??
          0;

        character.desiredMode =
          taskMode(
            worker.task,
          );

        const taskChanged =
          previousTaskId !==
          character.taskId;

        if (
          taskChanged &&
          (
            character
              .desiredMode ===
              "complete" ||
            character
              .desiredMode ===
              "failed"
          )
        ) {
          character.bubbleTimer =
            TERMINAL_BUBBLE_SECONDS;
        }

        if (!worker.task) {
          if (
            previousTaskId !==
              null ||
            previousDesired !==
              "idle"
          ) {
            character.desiredMode =
              "idle";

            character.mode =
              "idle";

            character.path =
              [];

            character.idleTimer =
              randomRange(
                WANDER_MIN_SECONDS,
                WANDER_MAX_SECONDS,
              );
          }

          return;
        }

        const atSeat =
          character.tileCol ===
            seat.col &&
          character.tileRow ===
            seat.row;

        if (!atSeat) {
          if (
            character.path
              .length ===
              0 ||
            taskChanged
          ) {
            character.path =
              findPath(
                this.layout,
                this.blocked,
                character.tileCol,
                character.tileRow,
                seat.col,
                seat.row,
              );

            character.moveProgress =
              0;
          }

          if (
            character.path
              .length >
            0
          ) {
            character.mode =
              "walk";
          }
        } else {
          character.direction =
            seat.facing;

          character.mode =
            character
              .desiredMode ===
              "walk"
              ? "type"
              : character
                  .desiredMode;
        }
      },
    );

    for (
      const id
      of this.characters.keys()
    ) {
      if (
        !keep.has(id)
      ) {
        this.characters.delete(
          id,
        );
      }
    }
  }

  setSelected(
    id: string | null,
  ) {
    this.selectedCharacterId =
      id;

    this.cameraFollowId =
      id;
  }

  pan(
    dx: number,
    dy: number,
  ) {
    this.camera.x +=
      dx /
      this.camera.zoom;

    this.camera.y +=
      dy /
      this.camera.zoom;

    this.cameraFollowId =
      null;
  }

  zoomAt(
    clientX: number,
    clientY: number,
    deltaY: number,
  ) {
    const rect =
      this.canvas
        .getBoundingClientRect();

    const previous =
      this.camera.zoom;

    const next =
      Math.max(
        0.5,
        Math.min(
          6,
          previous *
            (
              deltaY >
              0
                ? 0.9
                : 1.1
            ),
        ),
      );

    if (
      next === previous
    ) {
      return;
    }

    const localX =
      clientX -
      rect.left;

    const localY =
      clientY -
      rect.top;

    const worldX =
      localX /
        previous -
      this.camera.x;

    const worldY =
      localY /
        previous -
      this.camera.y;

    this.camera.zoom =
      next;

    this.camera.x =
      localX /
        next -
      worldX;

    this.camera.y =
      localY /
        next -
      worldY;

    this.cameraFollowId =
      null;
  }

  hitTest(
    clientX: number,
    clientY: number,
  ): OfficeHit | null {
    const rect =
      this.canvas
        .getBoundingClientRect();

    const x =
      (
        clientX -
        rect.left
      ) /
        this.camera.zoom -
      this.camera.x;

    const y =
      (
        clientY -
        rect.top
      ) /
        this.camera.zoom -
      this.camera.y;

    const characters =
      [
        ...this.characters.values(),
      ].sort(
        (a, b) =>
          b.y -
          a.y,
      );

    for (
      const character
      of characters
    ) {
      if (
        x >=
          character.x -
            11 &&
        x <=
          character.x +
            11 &&
        y >=
          character.y -
            35 &&
        y <=
          character.y +
            6
      ) {
        return {
          characterId:
            character.id,
        };
      }
    }

    if (
      x >=
        this.pet.x -
          18 &&
      x <=
        this.pet.x +
          18 &&
      y >=
        this.pet.y -
          35 &&
      y <=
        this.pet.y +
          5
    ) {
      return {
        petId:
          this.pet.id,
      };
    }

    return null;
  }

  private update(
    dt: number,
  ) {
    for (
      const character
      of this.characters.values()
    ) {
      character.frameTimer +=
        dt;

      if (
        character.bubbleTimer >
        0
      ) {
        character.bubbleTimer =
          Math.max(
            0,
            character.bubbleTimer -
              dt,
          );
      }

      if (
        character.mode ===
        "walk"
      ) {
        this.updateWalking(
          character,
          dt,
        );

        continue;
      }

      if (
        character.taskId &&
        character.path.length ===
          0
      ) {
        const seat =
          this.layout.seats.find(
            (candidate) =>
              candidate.id ===
              character.seatId,
          );

        if (
          seat &&
          (
            character.tileCol !==
              seat.col ||
            character.tileRow !==
              seat.row
          )
        ) {
          character.path =
            findPath(
              this.layout,
              this.blocked,
              character.tileCol,
              character.tileRow,
              seat.col,
              seat.row,
            );

          if (
            character.path.length >
            0
          ) {
            character.mode =
              "walk";

            continue;
          }
        }

        character.mode =
          character.desiredMode;

        if (seat) {
          character.direction =
            seat.facing;
        }
      }

      if (
        character.mode ===
          "type" ||
        character.mode ===
          "read"
      ) {
        if (
          character.frameTimer >=
          WORK_FRAME_SECONDS
        ) {
          character.frameTimer =
            0;

          character.frame =
            (
              character.frame +
              1
            ) %
            2;
        }

        continue;
      }

      if (
        character.mode ===
          "idle"
      ) {
        this.updateIdle(
          character,
          dt,
        );
      }
    }

    this.updatePet(dt);
    this.updateCamera(dt);
  }

  private updateWalking(
    character:
      OfficeCharacter,
    dt: number,
  ) {
    if (
      character.frameTimer >=
      WALK_FRAME_SECONDS
    ) {
      character.frameTimer =
        0;

      character.frame =
        (
          character.frame +
          1
        ) %
        4;
    }

    const next =
      character.path[0];

    if (!next) {
      const seat =
        this.layout.seats.find(
          (candidate) =>
            candidate.id ===
            character.seatId,
        );

      if (
        character.taskId &&
        seat &&
        character.tileCol ===
          seat.col &&
        character.tileRow ===
          seat.row
      ) {
        character.direction =
          seat.facing;

        character.mode =
          character.desiredMode;
      } else {
        character.mode =
          "idle";

        character.idleTimer =
          randomRange(
            WANDER_MIN_SECONDS,
            WANDER_MAX_SECONDS,
          );
      }

      return;
    }

    character.direction =
      directionBetween(
        character.tileCol,
        character.tileRow,
        next.col,
        next.row,
      );

    character.moveProgress +=
      (
        WALK_SPEED /
        TILE_SIZE
      ) *
      dt;

    const from =
      tileBottomCenter(
        character.tileCol,
        character.tileRow,
      );

    const to =
      tileBottomCenter(
        next.col,
        next.row,
      );

    const amount =
      Math.min(
        character.moveProgress,
        1,
      );

    character.x =
      from.x +
      (
        to.x -
        from.x
      ) *
      amount;

    character.y =
      from.y +
      (
        to.y -
        from.y
      ) *
      amount;

    if (
      character.moveProgress >=
      1
    ) {
      character.tileCol =
        next.col;

      character.tileRow =
        next.row;

      character.x =
        to.x;

      character.y =
        to.y;

      character.path.shift();

      character.moveProgress =
        0;
    }
  }

  private updateIdle(
    character:
      OfficeCharacter,
    dt: number,
  ) {
    if (
      character.taskId
    ) {
      return;
    }

    character.idleTimer -=
      dt;

    if (
      character.idleTimer >
        0 ||
      this.walkableTiles.length ===
        0
    ) {
      return;
    }

    const target =
      randomItem(
        this.walkableTiles,
      );

    const path =
      findPath(
        this.layout,
        this.blocked,
        character.tileCol,
        character.tileRow,
        target.col,
        target.row,
      );

    if (
      path.length >
      0
    ) {
      character.path =
        path.slice(
          0,
          Math.min(
            path.length,
            2 +
              Math.floor(
                Math.random() *
                  7,
              ),
          ),
        );

      character.moveProgress =
        0;

      character.mode =
        "walk";
    }

    character.idleTimer =
      randomRange(
        WANDER_MIN_SECONDS,
        WANDER_MAX_SECONDS,
      );
  }

  private updatePet(
    dt: number,
  ) {
    this.pet.frameTimer +=
      dt;

    if (
      this.pet.mode ===
      "walk"
    ) {
      if (
        this.pet.frameTimer >=
        PET_FRAME_SECONDS
      ) {
        this.pet.frameTimer =
          0;

        this.pet.frame =
          (
            this.pet.frame +
            1
          ) %
          3;
      }

      const next =
        this.pet.path[0];

      if (!next) {
        this.pet.mode =
          Math.random() <
            0.22
            ? "nap"
            : "idle";

        this.pet.idleTimer =
          randomRange(
            PET_IDLE_MIN_SECONDS,
            PET_IDLE_MAX_SECONDS,
          );

        return;
      }

      this.pet.direction =
        directionBetween(
          this.pet.tileCol,
          this.pet.tileRow,
          next.col,
          next.row,
        );

      this.pet.moveProgress +=
        (
          PET_WALK_SPEED /
          TILE_SIZE
        ) *
        dt;

      const from =
        tileBottomCenter(
          this.pet.tileCol,
          this.pet.tileRow,
        );

      const to =
        tileBottomCenter(
          next.col,
          next.row,
        );

      const amount =
        Math.min(
          this.pet.moveProgress,
          1,
        );

      this.pet.x =
        from.x +
        (
          to.x -
          from.x
        ) *
        amount;

      this.pet.y =
        from.y +
        (
          to.y -
          from.y
        ) *
        amount;

      if (
        this.pet.moveProgress >=
        1
      ) {
        this.pet.tileCol =
          next.col;

        this.pet.tileRow =
          next.row;

        this.pet.x =
          to.x;

        this.pet.y =
          to.y;

        this.pet.path.shift();

        this.pet.moveProgress =
          0;
      }

      return;
    }

    if (
      this.pet.frameTimer >=
      PET_FRAME_SECONDS *
        1.8
    ) {
      this.pet.frameTimer =
        0;

      this.pet.frame =
        (
          this.pet.frame +
          1
        ) %
        3;
    }

    this.pet.idleTimer -=
      dt;

    if (
      this.pet.idleTimer >
        0 ||
      this.petWalkableTiles.length ===
        0
    ) {
      return;
    }

    const target =
      randomItem(
        this.petWalkableTiles,
      );

    const path =
      findPath(
        this.layout,
        this.blocked,
        this.pet.tileCol,
        this.pet.tileRow,
        target.col,
        target.row,
      );

    if (
      path.length >
      0
    ) {
      this.pet.path =
        path;

      this.pet.moveProgress =
        0;

      this.pet.mode =
        "walk";

      this.pet.frame =
        0;

      return;
    }

    this.pet.idleTimer =
      randomRange(
        PET_IDLE_MIN_SECONDS,
        PET_IDLE_MAX_SECONDS,
      );
  }

  private updateCamera(
    dt: number,
  ) {
    if (
      !this.cameraFollowId
    ) {
      return;
    }

    const character =
      this.characters.get(
        this.cameraFollowId,
      );

    if (!character) {
      this.cameraFollowId =
        null;

      return;
    }

    const rect =
      this.canvas
        .getBoundingClientRect();

    const targetX =
      rect.width /
        (
          2 *
          this.camera.zoom
        ) -
      character.x;

    const targetY =
      rect.height /
        (
          2 *
          this.camera.zoom
        ) -
      character.y;

    const factor =
      1 -
      Math.exp(
        -6 *
        dt,
      );

    this.camera.x +=
      (
        targetX -
        this.camera.x
      ) *
      factor;

    this.camera.y +=
      (
        targetY -
        this.camera.y
      ) *
      factor;
  }

  private render() {
    const ctx =
      this.ctx;

    const rect =
      this.canvas
        .getBoundingClientRect();

    const dpr =
      window.devicePixelRatio ||
      1;

    ctx.setTransform(
      dpr,
      0,
      0,
      dpr,
      0,
      0,
    );

    ctx.imageSmoothingEnabled =
      false;

    ctx.fillStyle =
      "#071112";

    ctx.fillRect(
      0,
      0,
      rect.width,
      rect.height,
    );

    ctx.save();

    ctx.scale(
      this.camera.zoom,
      this.camera.zoom,
    );

    ctx.translate(
      this.camera.x,
      this.camera.y,
    );

    this.renderFloors(
      ctx,
    );

    this.renderCarpets(
      ctx,
    );

    this.renderDepthSortedEntities(
      ctx,
    );

    // Agent labels are UI, not world geometry. Render them after every wall,
    // prop and character so furniture can never paint over a name tag.
    this.renderCharacterLabels(
      ctx,
    );

    ctx.restore();

    this.renderOverlay(
      ctx,
      rect.width,
      rect.height,
    );
  }

  private renderFloors(
    ctx:
      CanvasRenderingContext2D,
  ) {
    for (
      const room
      of this.layout.rooms
    ) {
      this.renderRoomFloor(
        ctx,
        room,
      );
    }
  }

  private renderRoomFloor(
    ctx:
      CanvasRenderingContext2D,
    room:
      OfficeRoomZone,
  ) {
    if (
      room.id ===
      "office"
    ) {
      this.drawOfficeWoodFloor(
        ctx,
        room,
      );
    } else if (
      room.id ===
      "lounge"
    ) {
      this.drawLoungeFloor(
        ctx,
        room,
      );
    } else if (
      room.id ===
      "break"
    ) {
      this.drawBreakCheckerFloor(
        ctx,
        room,
      );
    } else {
      for (
        let row =
          room.row;
        row <
          room.row +
            room.height;
        row += 1
      ) {
        for (
          let col =
            room.col;
          col <
            room.col +
              room.width;
          col += 1
        ) {
          const drawn =
            this.sprites
              .drawFloorTile(
                ctx,
                room.floorPattern,
                room.floorTint,
                col *
                  TILE_SIZE,
                row *
                  TILE_SIZE,
              );

          if (!drawn) {
            ctx.fillStyle =
              room.floorTint;

            ctx.fillRect(
              col *
                TILE_SIZE,
              row *
                TILE_SIZE,
              TILE_SIZE,
              TILE_SIZE,
            );
          }
        }
      }
    }
  }

  private drawOfficeWoodFloor(
    ctx:
      CanvasRenderingContext2D,
    room:
      OfficeRoomZone,
  ) {
    const startX =
      room.col *
      TILE_SIZE;

    const startY =
      room.row *
      TILE_SIZE;

    const width =
      room.width *
      TILE_SIZE;

    const height =
      room.height *
      TILE_SIZE;

    ctx.fillStyle =
      "#784B27";

    ctx.fillRect(
      startX,
      startY,
      width,
      height,
    );

    // Fine horizontal plank seams.
    for (
      let y = startY;
      y <= startY + height;
      y += 8
    ) {
      ctx.strokeStyle =
        y % 16 === 0
          ? "rgba(89,55,31,0.60)"
          : "rgba(147,94,57,0.20)";

      ctx.beginPath();
      ctx.moveTo(
        startX,
        y + 0.5,
      );
      ctx.lineTo(
        startX + width,
        y + 0.5,
      );
      ctx.stroke();
    }

    // Staggered short joins between planks.
    for (
      let rowBand = 0;
      rowBand < height / 8;
      rowBand += 1
    ) {
      const y =
        startY +
        rowBand * 8;

      const offset =
        rowBand % 2 === 0
          ? 22
          : 40;

      for (
        let x = startX + offset;
        x < startX + width - 8;
        x += 36
      ) {
        ctx.strokeStyle =
          "rgba(94,58,34,0.38)";

        ctx.beginPath();
        ctx.moveTo(
          x + 0.5,
          y + 1,
        );
        ctx.lineTo(
          x + 0.5,
          y + 7,
        );
        ctx.stroke();
      }
    }
  }

  private drawLoungeFloor(
    ctx:
      CanvasRenderingContext2D,
    room:
      OfficeRoomZone,
  ) {
    ctx.fillStyle =
      "#5A7FA8";

    ctx.fillRect(
      room.col *
        TILE_SIZE,
      room.row *
        TILE_SIZE,
      room.width *
        TILE_SIZE,
      room.height *
        TILE_SIZE,
    );
  }

  private drawBreakCheckerFloor(
    ctx:
      CanvasRenderingContext2D,
    room:
      OfficeRoomZone,
  ) {
    const colors = [
      "#F0F2F4",
      "#4A4F57",
    ];

    for (
      let rowOffset = 0;
      rowOffset < room.height;
      rowOffset += 1
    ) {
      for (
        let colOffset = 0;
        colOffset < room.width;
        colOffset += 1
      ) {
        const x =
          (
            room.col +
            colOffset
          ) * TILE_SIZE;

        const y =
          (
            room.row +
            rowOffset
          ) * TILE_SIZE;

        ctx.fillStyle =
          colors[
            (
              rowOffset +
              colOffset
            ) % 2
          ];

        ctx.fillRect(
          x,
          y,
          TILE_SIZE,
          TILE_SIZE,
        );
      }
    }
  }

  private renderCarpets(
    ctx:
      CanvasRenderingContext2D,
  ) {
    for (
      const carpet
      of this.layout.carpets
    ) {
      this.renderCarpet(
        ctx,
        carpet,
      );
    }
  }

  private renderCarpet(
    ctx:
      CanvasRenderingContext2D,
    carpet:
      CarpetZone,
  ) {
    for (
      let rowOffset = 0;
      rowOffset <
        carpet.height;
      rowOffset += 1
    ) {
      for (
        let colOffset = 0;
        colOffset <
          carpet.width;
        colOffset += 1
      ) {
        const top =
          rowOffset >
          0;

        const right =
          colOffset <
          carpet.width -
            1;

        const bottom =
          rowOffset <
          carpet.height -
            1;

        const left =
          colOffset >
          0;

        const marchingCase =
          (
            top ? 1 : 0
          ) |
          (
            right ? 2 : 0
          ) |
          (
            bottom ? 4 : 0
          ) |
          (
            left ? 8 : 0
          );

        this.sprites
          .drawCarpetTile(
            ctx,
            carpet.carpetIndex,
            marchingCase,
            (
              carpet.col +
              colOffset
            ) *
              TILE_SIZE,
            (
              carpet.row +
              rowOffset
            ) *
              TILE_SIZE,
          );
      }
    }
  }

  private furnitureDepth(
    furniture:
      FurniturePlacement,
  ): number {
    let depth =
      (
        furniture.row +
        furniture.footprintH
      ) *
      TILE_SIZE;

    if (
      !furniture.surface
    ) {
      return depth;
    }

    const furnitureLeft =
      furniture.col;

    const furnitureRight =
      furniture.col +
      furniture.footprintW;

    const furnitureTop =
      furniture.row;

    const furnitureBottom =
      furniture.row +
      furniture.footprintH;

    for (
      const support
      of this.layout.furniture
    ) {
      if (
        support.id ===
          furniture.id ||
        !support.blocks ||
        support.wallMounted
      ) {
        continue;
      }

      const overlaps =
        furnitureLeft <
          support.col +
            support.footprintW &&
        furnitureRight >
          support.col &&
        furnitureTop <
          support.row +
            support.footprintH &&
        furnitureBottom >
          support.row;

      if (!overlaps) {
        continue;
      }

      depth =
        Math.max(
          depth,
          (
            support.row +
            support.footprintH
          ) *
            TILE_SIZE +
            0.5,
        );
    }

    return depth;
  }

  private renderDepthSortedEntities(
    ctx:
      CanvasRenderingContext2D,
  ) {
    const renderables:
      Renderable[] = [];

    const animationFrame =
      Math.floor(
        this.worldTime /
          0.34,
      );

    for (
      const key
      of this.wallTiles
    ) {
      const [
        col,
        row,
      ] =
        key
          .split(",")
          .map(Number);

      renderables.push({
        depth:
          (
            row +
            1
          ) *
            TILE_SIZE -
          2,

        render:
          () =>
            this.drawWall(
              ctx,
              col,
              row,
            ),
      });
    }

    for (
      const furniture
      of this.layout.furniture
    ) {
      const depth =
        this.furnitureDepth(
          furniture,
        );

      renderables.push({
        // Wall-mounted furniture is bottom-aligned to a wall tile. The wall
        // itself renders at bottom - 2, so using the normal furniture depth
        // draws the decoration immediately after the wall instead of behind it.
        depth,

        render:
          () =>
            this.drawFurniture(
              ctx,
              furniture,
              animationFrame,
            ),
      });
    }

    renderables.push({
      depth:
        this.pet.y +
        1,

      render:
        () =>
          this.drawPet(
            ctx,
          ),
    });

    for (
      const character
      of this.characters.values()
    ) {
      renderables.push({
        depth:
          character.y +
          2,

        render:
          () =>
            this.drawCharacter(
              ctx,
              character,
            ),
      });
    }

    renderables
      .sort(
        (a, b) =>
          a.depth -
          b.depth,
      )
      .forEach(
        (item) =>
          item.render(),
      );
  }

  private renderCharacterLabels(
    ctx:
      CanvasRenderingContext2D,
  ) {
    for (
      const character
      of this.characters.values()
    ) {
      this.drawCharacterLabel(
        ctx,
        character,
        character.id ===
          this.selectedCharacterId,
      );
    }
  }

  private wallBitmask(
    col: number,
    row: number,
  ): number {
    let mask =
      0;

    if (
      this.wallTiles.has(
        `${col},${row - 1}`,
      )
    ) {
      mask |=
        1;
    }

    if (
      this.wallTiles.has(
        `${col + 1},${row}`,
      )
    ) {
      mask |=
        2;
    }

    if (
      this.wallTiles.has(
        `${col},${row + 1}`,
      )
    ) {
      mask |=
        4;
    }

    if (
      this.wallTiles.has(
        `${col - 1},${row}`,
      )
    ) {
      mask |=
        8;
    }

    return mask;
  }

  private drawWall(
    ctx:
      CanvasRenderingContext2D,
    col: number,
    row: number,
  ) {
    const bitmask =
      this.wallBitmask(
        col,
        row,
      );

    const drawn =
      this.sprites
        .drawWallTile(
          ctx,
          0,
          bitmask,
          col *
            TILE_SIZE,
          (
            row +
            1
          ) *
            TILE_SIZE,
          WALL_TINT,
        );

    if (!drawn) {
      ctx.fillStyle =
        "#203246";

      ctx.fillRect(
        col *
          TILE_SIZE,
        row *
          TILE_SIZE,
        TILE_SIZE,
        TILE_SIZE,
      );
    }
  }

  private isSeatActive(
    seatId:
      string |
      undefined,
  ): boolean {
    if (!seatId) {
      return false;
    }

    for (
      const character
      of this.characters.values()
    ) {
      if (
        character.seatId ===
          seatId &&
        character.taskId
      ) {
        return true;
      }
    }

    return false;
  }

  private drawFurniture(
    ctx:
      CanvasRenderingContext2D,
    furniture:
      FurniturePlacement,
    animationFrame:
      number,
  ) {
    const active =
      furniture.assetGroup ===
        "PC"
        ? (
            furniture.linkedSeatId
              ? this.isSeatActive(
                  furniture.linkedSeatId,
                )
              : furniture.state ===
                  "on"
          )
        : false;

    const result =
      this.sprites
        .drawFurniture(
          ctx,
          furniture,
          active,
          animationFrame,
        );

    if (
      !result.drawn
    ) {
      ctx.fillStyle =
        "rgba(66,94,91,0.72)";

      ctx.fillRect(
        furniture.col *
          TILE_SIZE,
        furniture.row *
          TILE_SIZE,
        furniture.footprintW *
          TILE_SIZE,
        furniture.footprintH *
          TILE_SIZE,
      );

      ctx.strokeStyle =
        "rgba(161,218,210,0.18)";

      ctx.strokeRect(
        furniture.col *
          TILE_SIZE,
        furniture.row *
          TILE_SIZE,
        furniture.footprintW *
          TILE_SIZE,
        furniture.footprintH *
          TILE_SIZE,
      );
    }
  }

  private drawPet(
    ctx:
      CanvasRenderingContext2D,
  ) {
    ctx.fillStyle =
      "rgba(0,0,0,0.18)";

    ctx.beginPath();

    ctx.ellipse(
      this.pet.x,
      this.pet.y -
        1,
      8,
      3,
      0,
      0,
      Math.PI *
        2,
    );

    ctx.fill();

    const drawn =
      this.sprites
        .drawPet(
          ctx,
          this.pet.assetId,
          this.pet.mode,
          this.pet.direction,
          this.pet.frame,
          this.pet.x,
          this.pet.y,
        );

    if (!drawn) {
      ctx.fillStyle =
        "#bf885e";

      ctx.fillRect(
        this.pet.x -
          6,
        this.pet.y -
          10,
        12,
        8,
      );
    }

    if (
      this.pet.mode ===
      "nap"
    ) {
      ctx.fillStyle =
        "rgba(220,238,233,0.72)";

      ctx.font =
        "6px monospace";

      ctx.textAlign =
        "center";

      ctx.fillText(
        "z",
        this.pet.x +
          9,
        this.pet.y -
          24,
      );
    }

    ctx.fillStyle =
      "rgba(221,238,234,0.82)";

    ctx.font =
      "5px 'Courier New', monospace";

    ctx.textAlign =
      "center";

    ctx.fillText(
      this.pet.name,
      this.pet.x,
      this.pet.y +
        7,
    );
  }

  private drawCharacter(
    ctx:
      CanvasRenderingContext2D,
    character:
      OfficeCharacter,
  ) {
    const selected =
      character.id ===
      this.selectedCharacterId;

    const hovered =
      character.id ===
      this.hoveredCharacterId;

    ctx.fillStyle =
      selected
        ? "rgba(100,232,208,0.24)"
        : hovered
          ? "rgba(255,255,255,0.10)"
          : "rgba(0,0,0,0.15)";

    ctx.beginPath();

    ctx.ellipse(
      character.x,
      character.y -
        1,
      selected
        ? 9
        : 7,
      selected
        ? 4
        : 3,
      0,
      0,
      Math.PI *
        2,
    );

    ctx.fill();

    const drawn =
      this.sprites
        .drawCharacter(
          ctx,
          character.spriteIndex,
          character.mode,
          character.direction,
          character.frame,
          character.x,
          character.y,
        );

    if (!drawn) {
      ctx.fillStyle =
        character.accent;

      ctx.fillRect(
        character.x -
          5,
        character.y -
          20,
        10,
        18,
      );
    }

    const bubble =
      bubbleText(
        character,
      );

    if (bubble) {
      this.drawSpeechBubble(
        ctx,
        character,
        bubble,
      );
    }

  }

  private drawSpeechBubble(
    ctx:
      CanvasRenderingContext2D,
    character:
      OfficeCharacter,
    text: string,
  ) {
    ctx.font =
      "bold 5px 'Courier New', monospace";

    const width =
      Math.max(
        22,
        ctx.measureText(
          text,
        ).width +
          8,
      );

    const x =
      character.x -
      width /
        2;

    const y =
      character.y -
      44;

    let background =
      "#dbece6";

    if (
      character.mode ===
      "wait"
    ) {
      background =
        "#e3ae43";
    } else if (
      character.mode ===
      "complete"
    ) {
      background =
        "#6edca7";
    } else if (
      character.mode ===
      "failed"
    ) {
      background =
        "#df747c";
    }

    ctx.fillStyle =
      "#071111";

    ctx.fillRect(
      x -
        2,
      y -
        2,
      width +
        4,
      12,
    );

    ctx.fillStyle =
      background;

    ctx.fillRect(
      x,
      y,
      width,
      8,
    );

    ctx.fillRect(
      character.x -
        2,
      y +
        8,
      4,
      3,
    );

    ctx.fillStyle =
      "#101818";

    ctx.textAlign =
      "center";

    ctx.fillText(
      text,
      character.x,
      y +
        6,
    );
  }

  private drawCharacterLabel(
    ctx:
      CanvasRenderingContext2D,
    character:
      OfficeCharacter,
    selected:
      boolean,
  ) {
    ctx.font =
      "6px 'Courier New', monospace";

    const labelWidth =
      Math.max(
        52,
        ctx.measureText(
          character.label,
        ).width +
          8,
      );

    const labelX =
      character.x -
      labelWidth /
        2;

    const labelY =
      character.y +
      3;

    const height =
      character.taskId
        ? 20
        : 11;

    ctx.fillStyle =
      "rgba(4,14,15,0.90)";

    ctx.fillRect(
      labelX,
      labelY,
      labelWidth,
      height,
    );

    ctx.strokeStyle =
      selected
        ? character.accent
        : "rgba(112,211,203,0.14)";

    ctx.strokeRect(
      labelX,
      labelY,
      labelWidth,
      height,
    );

    ctx.fillStyle =
      "#d4ece9";

    ctx.textAlign =
      "center";

    ctx.fillText(
      character.label,
      character.x,
      labelY +
        7,
    );

    if (
      character.taskId
    ) {
      const activity =
        character.activity
          .length >
        20
          ? (
              character.activity
                .slice(
                  0,
                  19,
                ) +
              "…"
            )
          : character.activity;

      ctx.fillStyle =
        "#7ca09c";

      ctx.font =
        "5px 'Courier New', monospace";

      ctx.fillText(
        activity,
        character.x,
        labelY +
          13,
      );

      ctx.fillStyle =
        "rgba(255,255,255,0.08)";

      ctx.fillRect(
        labelX +
          3,
        labelY +
          16,
        labelWidth -
          6,
        2,
      );

      ctx.fillStyle =
        character.accent;

      ctx.fillRect(
        labelX +
          3,
        labelY +
          16,
        (
          labelWidth -
          6
        ) *
          Math.max(
            0,
            Math.min(
              1,
              character.progress,
            ),
          ),
        2,
      );
    }
  }

  private renderOverlay(
    ctx:
      CanvasRenderingContext2D,
    width: number,
    height: number,
  ) {
    ctx.setTransform(
      1,
      0,
      0,
      1,
      0,
      0,
    );

    const selected =
      this.selectedCharacterId
        ? this.characters.get(
            this.selectedCharacterId,
          )
        : null;

    if (selected) {
      const panelWidth =
        Math.min(
          width -
            24,
          360,
        );

      ctx.fillStyle =
        "rgba(4,13,14,0.90)";

      ctx.fillRect(
        12,
        height -
          45,
        panelWidth,
        31,
      );

      ctx.strokeStyle =
        "rgba(104,224,211,0.18)";

      ctx.strokeRect(
        12,
        height -
          45,
        panelWidth,
        31,
      );

      ctx.textAlign =
        "left";

      ctx.fillStyle =
        "#d9efec";

      ctx.font =
        "bold 9px 'Courier New', monospace";

      ctx.fillText(
        selected.label,
        20,
        height -
          31,
      );

      ctx.fillStyle =
        "#739c98";

      ctx.font =
        "7px 'Courier New', monospace";

      ctx.fillText(
        selected.taskTitle
          ? selected.taskTitle.slice(
              0,
              56,
            )
          : "Standing by",
        20,
        height -
          19,
      );
    }

    ctx.textAlign =
      "right";

    ctx.fillStyle =
      "rgba(177,215,211,0.36)";

    ctx.font =
      "6px 'Courier New', monospace";

    ctx.fillText(
      "PIXEL AGENTS ASSETS  •  DRAG PAN  •  WHEEL ZOOM  •  CLICK FOLLOW",
      width -
        12,
      height -
        8,
    );

    if (
      !this.sprites.ready
    ) {
      ctx.textAlign =
        "left";

      ctx.fillStyle =
        this.sprites.error
          ? "#dc7a80"
          : "rgba(125,221,211,0.58)";

      const status =
        this.sprites.error
          ? this.sprites.error
          : "LOADING PIXEL AGENTS ASSETS…";

      ctx.fillText(
        status.slice(
          0,
          120,
        ),
        12,
        14,
      );
    } else if (
      this.sprites.sourceRef
    ) {
      const diagnostics =
        this.sprites.getDiagnostics();

      ctx.textAlign =
        "left";

      ctx.fillStyle =
        diagnostics.warnings.length > 0
          ? "rgba(232,184,105,0.82)"
          : "rgba(125,221,211,0.52)";

      ctx.fillText(
        `UPSTREAM ${this.sprites.sourceRef}  •  ` +
        `CHAR ${diagnostics.charactersLoaded}/${diagnostics.charactersExpected}  •  ` +
        `FLOOR ${diagnostics.floorsLoaded}/${diagnostics.floorsExpected}  •  ` +
        `FURN ${diagnostics.furnitureGroupsLoaded}/${diagnostics.furnitureGroupsExpected}`,
        12,
        14,
      );

      if (
        diagnostics.warnings.length > 0
      ) {
        ctx.fillStyle =
          "rgba(232,184,105,0.72)";

        ctx.fillText(
          `ASSET WARNINGS ${diagnostics.warnings.length} — ` +
          diagnostics.warnings[0].slice(0, 100),
          12,
          24,
        );
      }
    }
  }
}
