/**
 * Native Pixel Agents v1.4.x sprite geometry.
 *
 * Characters:
 *   112x96 image
 *   7 columns x 3 rows
 *   each frame 16x32
 *
 * Row order:
 *   0 = down
 *   1 = up
 *   2 = right
 * Left is rendered by horizontally mirroring the right row.
 *
 * Frame order:
 *   0,1,2 = walk
 *   3,4   = type
 *   5,6   = read
 * idle uses frame 1
 */
export const UPSTREAM_CHARACTER = {
  frameWidth: 16,
  frameHeight: 32,
  framesPerRow: 7,
  rows: {
    down: 0,
    up: 1,
    right: 2,
  },
  walk: [0, 1, 2, 1] as const,
  idle: 1,
  type: [3, 4] as const,
  read: [5, 6] as const,
};

/**
 * Native wall sheet:
 * 64x128, 4x4 bitmask grid, each piece 16x32.
 */
export const UPSTREAM_WALL = {
  pieceWidth: 16,
  pieceHeight: 32,
  columns: 4,
  masks: 16,
};

/**
 * Native carpet sheet:
 * 64x64, 4x4 marching-square grid, each piece 16x16.
 */
export const UPSTREAM_CARPET = {
  pieceWidth: 16,
  pieceHeight: 16,
  columns: 4,
  cases: 16,
};

/**
 * Native pet sheet:
 * 96x96.
 *
 * Row 0: 3 x 16px walk-down + 3 x 16px idle-down
 * Row 1: 3 x 16px walk-up   + 3 x 16px idle-up
 * Row 2: 3 x 32px walk-right
 *
 * Left is mirrored right.
 */
export const UPSTREAM_PET = {
  imageWidth: 96,
  imageHeight: 96,
  frameHeight: 32,
  smallFrameWidth: 16,
  largeFrameWidth: 32,
  verticalWalkFrames: 3,
  verticalIdleFrames: 3,
  horizontalWalkFrames: 3,
};
