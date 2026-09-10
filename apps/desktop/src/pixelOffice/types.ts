import type { AgentTask } from "../agents/types";

export type OfficeDirection =
  | "up"
  | "down"
  | "left"
  | "right";

export type CharacterMode =
  | "idle"
  | "walk"
  | "queued"
  | "type"
  | "read"
  | "think"
  | "wait"
  | "complete"
  | "failed";

export interface OfficePoint {
  col: number;
  row: number;
}

export interface OfficeSeat {
  id: string;
  col: number;
  row: number;
  facing: OfficeDirection;
  specialist?: string;
}

export type FurnitureSpriteId =
  | "desk"
  | "chair"
  | "server"
  | "shelf"
  | "plant"
  | "cabinet"
  | "coffee"
  | "meeting_table"
  | "printer"
  | "lamp"
  | "rug";

export interface FurniturePlacement {
  id: string;
  sprite: FurnitureSpriteId;
  col: number;
  row: number;
  widthTiles?: number;
  heightTiles?: number;
  blocks?: boolean;
  wallMounted?: boolean;
}

export interface OfficeLayoutConfig {
  version: number;
  cols: number;
  rows: number;
  seats: OfficeSeat[];
  furniture: FurniturePlacement[];
}

export interface CharacterSpriteDefinition {
  frameWidth: number;
  frameHeight: number;
  columns: number;
  rows: Record<
    "down" | "left" | "right" | "up" | "idle" |
    "type" | "read" | "think",
    number
  >;
}

export interface OfficeCharacter {
  id: string;
  workerId: string;
  specialistId: string;
  label: string;
  accent: string;

  mode: CharacterMode;
  desiredMode: CharacterMode;
  direction: OfficeDirection;

  x: number;
  y: number;
  tileCol: number;
  tileRow: number;

  path: OfficePoint[];
  moveProgress: number;

  frame: number;
  frameTimer: number;
  idleTimer: number;
  bubbleTimer: number;

  seatId: string;
  taskId: string | null;
  taskTitle: string;
  activity: string;
  currentTool: string | null;
  progress: number;
  task: AgentTask | null;
}

export interface CameraState {
  x: number;
  y: number;
  zoom: number;
}

export interface OfficeHit {
  characterId: string;
}
