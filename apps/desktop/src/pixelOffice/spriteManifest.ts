import type {
  CharacterSpriteDefinition,
  FurnitureSpriteId,
} from "./types";

export const CHARACTER_SPRITE_DEFINITION:
  CharacterSpriteDefinition = {
    frameWidth: 16,
    frameHeight: 24,
    columns: 4,
    rows: {
      down: 0,
      left: 1,
      right: 2,
      up: 3,
      idle: 4,
      type: 5,
      read: 6,
      think: 7,
    },
  };

export interface FurnitureSpriteDefinition {
  index: number;
  width: number;
  height: number;
  anchorX: number;
  anchorY: number;
}

export const FURNITURE_FRAME_SIZE = 32;

export const FURNITURE_SPRITES:
  Record<FurnitureSpriteId, FurnitureSpriteDefinition> = {
    desk: { index: 0, width: 32, height: 32, anchorX: 16, anchorY: 29 },
    chair: { index: 1, width: 32, height: 32, anchorX: 16, anchorY: 29 },
    server: { index: 2, width: 32, height: 32, anchorX: 16, anchorY: 31 },
    shelf: { index: 3, width: 32, height: 32, anchorX: 16, anchorY: 31 },
    plant: { index: 4, width: 32, height: 32, anchorX: 16, anchorY: 31 },
    cabinet: { index: 5, width: 32, height: 32, anchorX: 16, anchorY: 31 },
    coffee: { index: 6, width: 32, height: 32, anchorX: 16, anchorY: 31 },
    meeting_table: { index: 7, width: 32, height: 32, anchorX: 16, anchorY: 27 },
    printer: { index: 8, width: 32, height: 32, anchorX: 16, anchorY: 30 },
    lamp: { index: 9, width: 32, height: 32, anchorX: 16, anchorY: 31 },
    rug: { index: 10, width: 32, height: 32, anchorX: 16, anchorY: 24 },
  };
