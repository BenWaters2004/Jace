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

export type RoomTheme =
  | "office"
  | "break"
  | "meeting"
  | "server"
  | "lounge";

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

export interface FurniturePlacement {
  id: string;
  assetGroup: string;
  col: number;
  row: number;
  orientation?: "front" | "back" | "side" | "left" | "right";
  state?: string;
  mirrorX?: boolean;
  linkedSeatId?: string;
  footprintW: number;
  footprintH: number;
  blocks?: boolean;
  wallMounted?: boolean;
  surface?: boolean;
  offsetX?: number;
  offsetY?: number;
}

export interface CarpetZone {
  id: string;
  carpetIndex: number;
  col: number;
  row: number;
  width: number;
  height: number;
}

export interface OfficeRoomZone {
  id: string;
  label: string;
  theme: RoomTheme;
  col: number;
  row: number;
  width: number;
  height: number;
  floorPattern: number;
  floorTint: string;
}

export interface WallDoorway {
  offset: number;
  size: number;
}

export interface OfficeWallSegment {
  id: string;
  orientation: "horizontal" | "vertical";
  col: number;
  row: number;
  length: number;
  doorways?: WallDoorway[];
  wallSet?: number;
}

export interface OfficeLayoutConfig {
  version: number;
  cols: number;
  rows: number;
  seats: OfficeSeat[];
  furniture: FurniturePlacement[];
  rooms: OfficeRoomZone[];
  walls: OfficeWallSegment[];
  carpets: CarpetZone[];
}

export interface OfficeCharacter {
  id: string;
  workerId: string;
  specialistId: string;
  spriteIndex: number;
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

export type PetMode =
  | "idle"
  | "walk"
  | "nap";

export interface OfficePet {
  id: string;
  assetId: string;
  name: string;
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

  mode: PetMode;
  allowedRoomIds: string[];
}

export interface CameraState {
  x: number;
  y: number;
  zoom: number;
}

export interface OfficeHit {
  characterId?: string;
  petId?: string;
}

export interface PixelAgentsAssetIndex {
  version: number;
  source: {
    repository: string;
    ref: string;
    syncedAt: string;
  };
  characters: string[];
  floors: string[];
  walls: string[];
  carpets: string[];
  pets: Array<{
    id: string;
    name: string;
    folder: string;
    manifest: string;
    image: string;
  }>;
  furniture: Array<{
    folder: string;
    manifest: string;
  }>;
}

export type UpstreamFurnitureOrientation =
  | "front"
  | "back"
  | "side"
  | "left"
  | "right";

export interface UpstreamFurnitureAssetNode {
  type: "asset";
  id: string;
  file?: string;
  width: number;
  height: number;
  footprintW: number;
  footprintH: number;
  orientation?: UpstreamFurnitureOrientation;
  state?: string;
  frame?: number;
  mirrorSide?: boolean;
}

export interface UpstreamFurnitureGroupNode {
  type: "group";
  id?: string;
  name?: string;
  category?: string;
  groupType?: "rotation" | "state" | "animation" | string;
  rotationScheme?: string;
  orientation?: UpstreamFurnitureOrientation;
  state?: string;
  mirrorSide?: boolean;
  members: UpstreamFurnitureManifestNode[];
}

export type UpstreamFurnitureManifestNode =
  | UpstreamFurnitureAssetNode
  | UpstreamFurnitureGroupNode;

export type UpstreamFurnitureManifest =
  | (UpstreamFurnitureAssetNode & {
      id: string;
      name: string;
      category: string;
      canPlaceOnWalls: boolean;
      canPlaceOnSurfaces: boolean;
      backgroundTiles: number;
    })
  | (UpstreamFurnitureGroupNode & {
      id: string;
      name: string;
      category: string;
      canPlaceOnWalls: boolean;
      canPlaceOnSurfaces: boolean;
      backgroundTiles: number;
    });

export interface ResolvedFurnitureAsset {
  rootId: string;
  name: string;
  category: string;
  folder: string;
  assetId: string;
  file: string;
  width: number;
  height: number;
  footprintW: number;
  footprintH: number;
  backgroundTiles: number;
  orientation?: UpstreamFurnitureOrientation;
  state?: string;
  frame?: number;
  mirrorSide: boolean;
  canPlaceOnWalls: boolean;
  canPlaceOnSurfaces: boolean;
}
