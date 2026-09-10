import type { OfficeWorker } from "../agents/useAgentOffice";
import type { AgentTask } from "../agents/types";
import {
  createJaceOfficeLayout,
  findPath,
  getWalkableTiles,
  TILE_SIZE,
  tileCenter,
} from "./layout";
import type {
  OfficeCharacter,
  OfficeCharacterMode,
  OfficeDirection,
  OfficeHit,
  OfficeLayout,
  OfficeViewport,
} from "./types";

const WALK_SPEED = 52;
const WALK_FRAME_TIME = 0.13;
const TYPE_FRAME_TIME = 0.18;
const WANDER_MIN = 2.4;
const WANDER_MAX = 6.0;
const COMPLETE_HOLD = 3.5;
const FAILED_HOLD = 5.0;

function randomRange(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function directionBetween(
  fromCol: number,
  fromRow: number,
  toCol: number,
  toRow: number,
): OfficeDirection {
  if (toCol > fromCol) return "right";
  if (toCol < fromCol) return "left";
  if (toRow > fromRow) return "down";
  return "up";
}

function toolMode(task: AgentTask | null): OfficeCharacterMode {
  if (!task) return "idle";

  switch (task.status) {
    case "queued":
      return "idle";
    case "running":
      return "walk";
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
      const active = task.progress_message?.toLowerCase() ?? "";
      const tool = [...task.used_tools].at(-1)?.toLowerCase() ?? "";

      if (
        active.includes("read") ||
        active.includes("search") ||
        tool.includes("read") ||
        tool.includes("search")
      ) {
        return "read";
      }

      return "type";
    }
  }
}

function isWorkingMode(mode: OfficeCharacterMode): boolean {
  return [
    "type",
    "read",
    "think",
    "wait",
    "complete",
    "failed",
  ].includes(mode);
}

function characterColor(index: number): string {
  const colors = [
    "#50d3e0",
    "#8f7cff",
    "#62dda5",
    "#efb85b",
    "#72b8ff",
    "#da78a7",
    "#76d8ca",
  ];

  return colors[index % colors.length];
}

export class JacePixelOfficeEngine {
  readonly layout: OfficeLayout;
  readonly walkableTiles;
  readonly characters = new Map<string, OfficeCharacter>();

  selectedCharacterId: string | null = null;
  hoveredCharacterId: string | null = null;
  cameraFollowId: string | null = null;

  viewport: OfficeViewport = {
    x: 0,
    y: 0,
    zoom: 2,
  };

  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private animationFrame: number | null = null;
  private lastTime = 0;
  private disposed = false;

  constructor(canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) throw new Error("Could not create Jace office canvas.");

    this.canvas = canvas;
    this.ctx = ctx;
    this.layout = createJaceOfficeLayout();
    this.walkableTiles = getWalkableTiles(this.layout);
  }

  start() {
    if (this.animationFrame != null) return;

    this.lastTime = performance.now();

    const tick = (time: number) => {
      if (this.disposed) return;

      const dt = Math.min((time - this.lastTime) / 1000, 0.1);
      this.lastTime = time;

      this.update(dt);
      this.render();

      this.animationFrame = requestAnimationFrame(tick);
    };

    this.animationFrame = requestAnimationFrame(tick);
  }

  dispose() {
    this.disposed = true;

    if (this.animationFrame != null) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }

    this.characters.clear();
  }

  resize(width: number, height: number, dpr: number) {
    const safeWidth = Math.max(1, Math.floor(width * dpr));
    const safeHeight = Math.max(1, Math.floor(height * dpr));

    if (
      this.canvas.width !== safeWidth ||
      this.canvas.height !== safeHeight
    ) {
      this.canvas.width = safeWidth;
      this.canvas.height = safeHeight;
      this.canvas.style.width = `${width}px`;
      this.canvas.style.height = `${height}px`;
    }

    const worldWidth = this.layout.cols * TILE_SIZE;
    const worldHeight = this.layout.rows * TILE_SIZE;

    const fitX = width / worldWidth;
    const fitY = height / worldHeight;
    const fitted = Math.max(1, Math.floor(Math.min(fitX, fitY) * 2));

    if (this.viewport.zoom < 1 || !Number.isFinite(this.viewport.zoom)) {
      this.viewport.zoom = fitted;
    }
  }

  syncWorkers(workers: OfficeWorker[]) {
    const activeIds = new Set<string>();

    workers.forEach((worker, index) => {
      activeIds.add(worker.id);

      let character = this.characters.get(worker.id);
      const seat =
        this.layout.seats.find(
          (candidate) => candidate.id === worker.definition.id,
        ) ??
        this.layout.seats[index % this.layout.seats.length];

      if (!character) {
        const spawn = this.walkableTiles[
          Math.floor(Math.random() * this.walkableTiles.length)
        ] ?? { col: 2, row: 9 };

        const center = tileCenter(spawn.col, spawn.row);

        character = {
          id: worker.id,
          workerId: worker.id,
          label: worker.definition.name,
          accent: worker.definition.accent || characterColor(index),
          mode: "idle",
          direction: "down",
          x: center.x,
          y: center.y,
          tileCol: spawn.col,
          tileRow: spawn.row,
          seatId: seat?.id ?? null,
          path: [],
          moveProgress: 0,
          frame: 0,
          frameTimer: 0,
          idleTimer: randomRange(WANDER_MIN, WANDER_MAX),
          bubbleTimer: 0,
          taskId: null,
          taskTitle: "",
          activity: "Standing by",
          progress: 0,
        };

        this.characters.set(worker.id, character);
      }

      character.label = worker.definition.name;
      character.accent = worker.definition.accent || character.accent;
      character.taskId = worker.task?.id ?? null;
      character.taskTitle = worker.task?.title ?? "";
      character.activity =
        worker.task?.progress_message ??
        (worker.task
          ? worker.task.status.replace(/_/g, " ")
          : "Standing by");
      character.progress = worker.task?.progress ?? 0;

      const wantedMode = toolMode(worker.task);

      if (worker.task && seat) {
        character.seatId = seat.id;

        const alreadyAtSeat =
          character.tileCol === seat.col &&
          character.tileRow === seat.row;

        if (!alreadyAtSeat && character.path.length === 0) {
          character.path = findPath(
            this.layout,
            character.tileCol,
            character.tileRow,
            seat.col,
            seat.row,
          );

          if (character.path.length > 0) {
            character.mode = "walk";
          }
        } else if (alreadyAtSeat && character.mode !== "walk") {
          character.mode = wantedMode === "walk" ? "type" : wantedMode;
          character.direction = seat.facing;
        }
      } else if (!worker.task) {
        if (isWorkingMode(character.mode)) {
          character.mode = "idle";
          character.bubbleTimer = 0;
          character.idleTimer = randomRange(WANDER_MIN, WANDER_MAX);
        }
      }

      if (wantedMode === "complete" && character.mode !== "walk") {
        character.mode = "complete";
        character.bubbleTimer = COMPLETE_HOLD;
      }

      if (wantedMode === "failed" && character.mode !== "walk") {
        character.mode = "failed";
        character.bubbleTimer = FAILED_HOLD;
      }

      if (
        worker.task &&
        character.mode !== "walk" &&
        wantedMode !== "walk" &&
        wantedMode !== "complete" &&
        wantedMode !== "failed"
      ) {
        character.mode = wantedMode;
      }
    });

    for (const id of this.characters.keys()) {
      if (!activeIds.has(id)) {
        this.characters.delete(id);
      }
    }
  }

  setSelected(id: string | null) {
    this.selectedCharacterId = id;
    this.cameraFollowId = id;
  }

  clearCameraFollow() {
    this.cameraFollowId = null;
  }

  pan(dx: number, dy: number) {
    this.viewport.x += dx / this.viewport.zoom;
    this.viewport.y += dy / this.viewport.zoom;
    this.clearCameraFollow();
  }

  zoomAt(
    clientX: number,
    clientY: number,
    delta: number,
  ) {
    const rect = this.canvas.getBoundingClientRect();
    const oldZoom = this.viewport.zoom;
    const nextZoom = Math.min(
      6,
      Math.max(1, oldZoom + (delta > 0 ? -0.25 : 0.25)),
    );

    if (nextZoom === oldZoom) return;

    const localX = clientX - rect.left;
    const localY = clientY - rect.top;

    const worldX =
      localX / oldZoom -
      this.viewport.x;
    const worldY =
      localY / oldZoom -
      this.viewport.y;

    this.viewport.zoom = nextZoom;

    this.viewport.x =
      localX / nextZoom -
      worldX;
    this.viewport.y =
      localY / nextZoom -
      worldY;
  }

  hitTest(clientX: number, clientY: number): OfficeHit | null {
    const rect = this.canvas.getBoundingClientRect();
    const x =
      (clientX - rect.left) / this.viewport.zoom -
      this.viewport.x;
    const y =
      (clientY - rect.top) / this.viewport.zoom -
      this.viewport.y;

    const candidates = [...this.characters.values()]
      .sort((a, b) => b.y - a.y);

    for (const character of candidates) {
      if (
        x >= character.x - 9 &&
        x <= character.x + 9 &&
        y >= character.y - 26 &&
        y <= character.y + 5
      ) {
        return { type: "character", id: character.id };
      }
    }

    return null;
  }

  private update(dt: number) {
    for (const character of this.characters.values()) {
      character.frameTimer += dt;

      if (character.bubbleTimer > 0) {
        character.bubbleTimer = Math.max(
          0,
          character.bubbleTimer - dt,
        );
      }

      if (character.mode === "walk") {
        this.updateWalk(character, dt);
      } else if (
        character.mode === "type" ||
        character.mode === "read" ||
        character.mode === "think"
      ) {
        if (character.frameTimer >= TYPE_FRAME_TIME) {
          character.frameTimer = 0;
          character.frame = (character.frame + 1) % 2;
        }
      } else if (character.mode === "idle") {
        this.updateIdle(character, dt);
      }
    }

    this.updateCamera(dt);
  }

  private updateWalk(character: OfficeCharacter, dt: number) {
    if (character.frameTimer >= WALK_FRAME_TIME) {
      character.frameTimer = 0;
      character.frame = (character.frame + 1) % 4;
    }

    const next = character.path[0];

    if (!next) {
      const seat = character.seatId
        ? this.layout.seats.find((candidate) => candidate.id === character.seatId)
        : null;

      if (seat && character.taskId) {
        character.mode = "type";
        character.direction = seat.facing;
      } else {
        character.mode = "idle";
        character.idleTimer = randomRange(WANDER_MIN, WANDER_MAX);
      }

      return;
    }

    character.direction = directionBetween(
      character.tileCol,
      character.tileRow,
      next.col,
      next.row,
    );

    character.moveProgress +=
      (WALK_SPEED / TILE_SIZE) * dt;

    const from = tileCenter(
      character.tileCol,
      character.tileRow,
    );
    const to = tileCenter(next.col, next.row);
    const t = Math.min(character.moveProgress, 1);

    character.x = from.x + (to.x - from.x) * t;
    character.y = from.y + (to.y - from.y) * t;

    if (character.moveProgress >= 1) {
      character.tileCol = next.col;
      character.tileRow = next.row;
      character.x = to.x;
      character.y = to.y;
      character.path.shift();
      character.moveProgress = 0;
    }
  }

  private updateIdle(character: OfficeCharacter, dt: number) {
    if (character.taskId) {
      return;
    }

    character.idleTimer -= dt;

    if (character.idleTimer > 0 || this.walkableTiles.length === 0) {
      return;
    }

    const target =
      this.walkableTiles[
        Math.floor(Math.random() * this.walkableTiles.length)
      ];

    const path = findPath(
      this.layout,
      character.tileCol,
      character.tileRow,
      target.col,
      target.row,
    );

    if (path.length > 0) {
      character.path = path.slice(
        0,
        Math.min(path.length, 2 + Math.floor(Math.random() * 5)),
      );
      character.moveProgress = 0;
      character.mode = "walk";
    }

    character.idleTimer = randomRange(WANDER_MIN, WANDER_MAX);
  }

  private updateCamera(dt: number) {
    if (!this.cameraFollowId) return;

    const character = this.characters.get(this.cameraFollowId);
    if (!character) return;

    const rect = this.canvas.getBoundingClientRect();
    const targetX =
      rect.width / (2 * this.viewport.zoom) -
      character.x;
    const targetY =
      rect.height / (2 * this.viewport.zoom) -
      character.y;

    const factor = 1 - Math.exp(-7 * dt);

    this.viewport.x +=
      (targetX - this.viewport.x) * factor;
    this.viewport.y +=
      (targetY - this.viewport.y) * factor;
  }

  private render() {
    const ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const rect = this.canvas.getBoundingClientRect();

    ctx.fillStyle = "#081313";
    ctx.fillRect(0, 0, rect.width, rect.height);

    ctx.save();
    ctx.scale(this.viewport.zoom, this.viewport.zoom);
    ctx.translate(this.viewport.x, this.viewport.y);

    this.renderRoom(ctx);

    const entities = [...this.characters.values()].sort(
      (a, b) => a.y - b.y,
    );

    for (const character of entities) {
      this.renderCharacter(ctx, character);
    }

    ctx.restore();

    this.renderHud(ctx, rect.width, rect.height);
  }

  private renderRoom(ctx: CanvasRenderingContext2D) {
    const width = this.layout.cols * TILE_SIZE;
    const height = this.layout.rows * TILE_SIZE;

    ctx.fillStyle = "#173533";
    ctx.fillRect(0, 0, width, height);

    // Floor.
    ctx.fillStyle = "#274a45";
    ctx.fillRect(
      0,
      TILE_SIZE * 2,
      width,
      height - TILE_SIZE * 2,
    );

    for (let row = 2; row < this.layout.rows; row += 1) {
      for (let col = 0; col < this.layout.cols; col += 1) {
        ctx.fillStyle =
          (col + row) % 2 === 0
            ? "#294d47"
            : "#244640";

        ctx.fillRect(
          col * TILE_SIZE,
          row * TILE_SIZE,
          TILE_SIZE,
          TILE_SIZE,
        );

        ctx.strokeStyle = "rgba(255,255,255,0.025)";
        ctx.strokeRect(
          col * TILE_SIZE,
          row * TILE_SIZE,
          TILE_SIZE,
          TILE_SIZE,
        );
      }
    }

    // Rear wall.
    ctx.fillStyle = "#15302f";
    ctx.fillRect(0, 0, width, TILE_SIZE * 2);

    ctx.fillStyle = "#081515";
    ctx.fillRect(
      0,
      TILE_SIZE * 2 - 3,
      width,
      3,
    );

    // JACE status board.
    ctx.fillStyle = "#0b1c1c";
    ctx.fillRect(width / 2 - 48, 10, 96, 27);
    ctx.strokeStyle = "#39756e";
    ctx.strokeRect(width / 2 - 48, 10, 96, 27);
    ctx.fillStyle = "#7ce8d9";
    ctx.font = "bold 8px monospace";
    ctx.textAlign = "center";
    ctx.fillText("J A C E  //  AGENT OPS", width / 2, 27);

    // Windows.
    this.drawWindow(ctx, 48, 12);
    this.drawWindow(ctx, width - 112, 12);

    // Desks.
    this.layout.seats.forEach((seat) => {
      this.drawDesk(
        ctx,
        seat.col * TILE_SIZE,
        (seat.row - 1) * TILE_SIZE,
      );
    });

    // Server rack.
    this.drawServerRack(ctx, TILE_SIZE, TILE_SIZE * 3);

    // Storage rack.
    this.drawStorage(ctx, width - TILE_SIZE * 2, TILE_SIZE * 3);

    // Meeting table.
    ctx.fillStyle = "#6d5037";
    ctx.fillRect(
      TILE_SIZE * 9,
      TILE_SIZE * 10,
      TILE_SIZE * 6,
      11,
    );
    ctx.fillStyle = "#9a7250";
    ctx.fillRect(
      TILE_SIZE * 9,
      TILE_SIZE * 10,
      TILE_SIZE * 6,
      3,
    );

    // Walkway stripe.
    ctx.strokeStyle = "rgba(120,220,205,0.17)";
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(TILE_SIZE * 2, TILE_SIZE * 12.4);
    ctx.lineTo(width - TILE_SIZE * 2, TILE_SIZE * 12.4);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  private drawWindow(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
  ) {
    ctx.fillStyle = "#081515";
    ctx.fillRect(x, y, 50, 28);
    ctx.fillStyle = "#173541";
    ctx.fillRect(x + 3, y + 3, 44, 22);

    ctx.fillStyle = "#59bfc6";
    ctx.fillRect(x + 9, y + 8, 2, 2);
    ctx.fillRect(x + 21, y + 13, 2, 2);
    ctx.fillRect(x + 35, y + 6, 2, 2);

    ctx.fillStyle = "#081515";
    ctx.fillRect(x + 24, y + 3, 2, 22);
    ctx.fillRect(x + 3, y + 13, 44, 2);
  }

  private drawDesk(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
  ) {
    ctx.fillStyle = "#0c1717";
    ctx.fillRect(x + 4, y + 2, 16, 13);

    ctx.fillStyle = "#17433f";
    ctx.fillRect(x + 7, y + 5, 10, 6);

    ctx.fillStyle = "#65d8c7";
    ctx.fillRect(x + 8, y + 6, 7, 1);
    ctx.fillRect(x + 8, y + 8, 5, 1);

    ctx.fillStyle = "#6d5037";
    ctx.fillRect(x, y + 16, TILE_SIZE, 5);

    ctx.fillStyle = "#956f4b";
    ctx.fillRect(x, y + 16, TILE_SIZE, 2);
  }

  private drawServerRack(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
  ) {
    ctx.fillStyle = "#0a1515";
    ctx.fillRect(x, y, 18, 58);

    for (let index = 0; index < 5; index += 1) {
      ctx.fillStyle = "#183230";
      ctx.fillRect(x + 3, y + 5 + index * 10, 12, 6);
      ctx.fillStyle = index % 2 ? "#73d8a2" : "#58c9d2";
      ctx.fillRect(x + 11, y + 7 + index * 10, 2, 2);
    }
  }

  private drawStorage(
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
  ) {
    ctx.fillStyle = "#142322";
    ctx.fillRect(x, y, 20, 54);
    ctx.fillStyle = "#3a5752";

    for (let row = 0; row < 4; row += 1) {
      ctx.fillRect(x + 2, y + 6 + row * 12, 16, 2);
    }
  }

  private renderCharacter(
    ctx: CanvasRenderingContext2D,
    character: OfficeCharacter,
  ) {
    const selected =
      character.id === this.selectedCharacterId;
    const hovered =
      character.id === this.hoveredCharacterId;

    if (selected || hovered) {
      ctx.fillStyle = selected
        ? "rgba(105,231,210,0.18)"
        : "rgba(255,255,255,0.08)";
      ctx.beginPath();
      ctx.ellipse(
        character.x,
        character.y + 2,
        12,
        5,
        0,
        0,
        Math.PI * 2,
      );
      ctx.fill();
    }

    ctx.save();
    ctx.translate(
      Math.round(character.x),
      Math.round(character.y),
    );

    const bob =
      character.mode === "walk"
        ? character.frame % 2
        : 0;

    ctx.translate(0, -bob);

    // Legs.
    ctx.fillStyle = "#18272d";
    ctx.fillRect(-6, -7, 5, 8);
    ctx.fillRect(2, -7, 5, 8);

    // Shoes.
    ctx.fillStyle = "#0b1113";
    ctx.fillRect(-7, 0, 6, 3);
    ctx.fillRect(2, 0, 6, 3);

    // Body.
    ctx.fillStyle = character.accent;
    ctx.fillRect(-8, -20, 16, 14);

    ctx.fillStyle = "rgba(0,0,0,0.15)";
    ctx.fillRect(-8, -9, 16, 3);

    // Arms / activity.
    ctx.fillStyle = "#d4a077";

    if (character.mode === "type") {
      const alternate = character.frame % 2 === 0 ? 0 : 2;
      ctx.fillRect(-11, -16 + alternate, 4, 9);
      ctx.fillRect(8, -14 - alternate, 4, 9);
    } else if (character.mode === "read") {
      ctx.fillRect(-11, -17, 4, 10);
      ctx.fillRect(8, -17, 4, 10);
      ctx.fillStyle = "#d9e9df";
      ctx.fillRect(-6, -10, 12, 7);
      ctx.fillStyle = "#63897e";
      ctx.fillRect(0, -10, 1, 7);
    } else {
      ctx.fillRect(-11, -18, 4, 10);
      ctx.fillRect(8, -18, 4, 10);
    }

    // Head.
    ctx.fillStyle = "#d4a077";
    ctx.fillRect(-6, -31, 12, 11);

    // Hair.
    ctx.fillStyle = "#2d211b";
    ctx.fillRect(-7, -34, 14, 5);
    ctx.fillRect(-7, -31, 3, 5);

    // Eyes.
    ctx.fillStyle = "#101616";
    if (character.direction !== "left") {
      ctx.fillRect(2, -27, 1, 1);
    }
    if (character.direction !== "right") {
      ctx.fillRect(-3, -27, 1, 1);
    }

    // Tool bubbles.
    if (character.mode === "think") {
      this.drawBubble(ctx, "…", "#e5f1e9");
    } else if (character.mode === "wait") {
      this.drawBubble(ctx, "!", "#efbc4c");
    } else if (
      character.mode === "complete" &&
      character.bubbleTimer > 0
    ) {
      this.drawBubble(ctx, "✓", "#73dfa8");
    } else if (
      character.mode === "failed" &&
      character.bubbleTimer > 0
    ) {
      this.drawBubble(ctx, "×", "#e5767e");
    }

    ctx.restore();

    // Name and live activity.
    ctx.textAlign = "center";
    ctx.font = "7px monospace";

    const nameWidth = Math.max(
      58,
      ctx.measureText(character.label).width + 8,
    );

    ctx.fillStyle = "rgba(5,15,16,0.88)";
    ctx.fillRect(
      character.x - nameWidth / 2,
      character.y + 7,
      nameWidth,
      character.taskId ? 22 : 13,
    );

    ctx.strokeStyle =
      character.id === this.selectedCharacterId
        ? character.accent
        : "rgba(100,205,205,0.13)";
    ctx.strokeRect(
      character.x - nameWidth / 2,
      character.y + 7,
      nameWidth,
      character.taskId ? 22 : 13,
    );

    ctx.fillStyle = "#d9eeee";
    ctx.fillText(
      character.label,
      character.x,
      character.y + 16,
    );

    if (character.taskId) {
      const activity =
        character.activity.length > 18
          ? `${character.activity.slice(0, 17)}…`
          : character.activity;

      ctx.fillStyle = "#8caeaa";
      ctx.font = "6px monospace";
      ctx.fillText(
        activity,
        character.x,
        character.y + 24,
      );

      ctx.fillStyle = "rgba(255,255,255,0.08)";
      ctx.fillRect(
        character.x - nameWidth / 2 + 3,
        character.y + 27,
        nameWidth - 6,
        2,
      );
      ctx.fillStyle = character.accent;
      ctx.fillRect(
        character.x - nameWidth / 2 + 3,
        character.y + 27,
        (nameWidth - 6) *
          Math.max(0, Math.min(1, character.progress)),
        2,
      );
    }
  }

  private drawBubble(
    ctx: CanvasRenderingContext2D,
    text: string,
    background: string,
  ) {
    ctx.fillStyle = "#091212";
    ctx.fillRect(7, -46, 18, 15);
    ctx.fillStyle = background;
    ctx.fillRect(9, -44, 14, 11);
    ctx.fillRect(10, -32, 4, 3);

    ctx.fillStyle = "#101616";
    ctx.font = "bold 9px monospace";
    ctx.textAlign = "center";
    ctx.fillText(text, 16, -35);
  }

  private renderHud(
    ctx: CanvasRenderingContext2D,
    width: number,
    height: number,
  ) {
    const selected = this.selectedCharacterId
      ? this.characters.get(this.selectedCharacterId)
      : null;

    ctx.setTransform(1, 0, 0, 1, 0, 0);

    if (selected) {
      ctx.fillStyle = "rgba(4,12,13,0.88)";
      ctx.fillRect(10, height - 40, Math.min(width - 20, 320), 28);
      ctx.strokeStyle = "rgba(100,220,213,0.18)";
      ctx.strokeRect(10, height - 40, Math.min(width - 20, 320), 28);

      ctx.textAlign = "left";
      ctx.fillStyle = "#d8efec";
      ctx.font = "bold 10px monospace";
      ctx.fillText(selected.label, 18, height - 27);

      ctx.fillStyle = "#7ea29e";
      ctx.font = "8px monospace";
      ctx.fillText(
        selected.taskId
          ? selected.taskTitle.slice(0, 48)
          : "Standing by",
        18,
        height - 16,
      );
    }

    ctx.textAlign = "right";
    ctx.fillStyle = "rgba(180,220,215,0.38)";
    ctx.font = "7px monospace";
    ctx.fillText(
      "drag: pan  •  wheel: zoom  •  click: follow",
      width - 12,
      height - 10,
    );
  }
}
