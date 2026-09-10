export type OfficeDirection = "up" | "down" | "left" | "right";

export type OfficeCharacterMode =
  | "idle"
  | "walk"
  | "type"
  | "read"
  | "think"
  | "wait"
  | "complete"
  | "failed";

export interface OfficeTile {
  col: number;
  row: number;
}

export interface OfficeSeat {
  id: string;
  col: number;
  row: number;
  facing: OfficeDirection;
}

export interface OfficeCharacter {
  id: string;
  workerId: string;
  label: string;
  accent: string;
  mode: OfficeCharacterMode;
  direction: OfficeDirection;

  x: number;
  y: number;
  tileCol: number;
  tileRow: number;

  seatId: string | null;
  path: OfficeTile[];
  moveProgress: number;

  frame: number;
  frameTimer: number;
  idleTimer: number;
  bubbleTimer: number;

  taskId: string | null;
  taskTitle: string;
  activity: string;
  progress: number;
}

export interface OfficeViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface OfficeLayout {
  cols: number;
  rows: number;
  seats: OfficeSeat[];
  blocked: Set<string>;
}

export interface OfficeHit {
  type: "character";
  id: string;
}
