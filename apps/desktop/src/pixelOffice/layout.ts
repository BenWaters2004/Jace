import type {
  FurniturePlacement,
  OfficeLayoutConfig,
  OfficePoint,
  OfficeSeat,
} from "./types";

export const TILE_SIZE = 24;
export const OFFICE_LAYOUT_STORAGE_KEY =
  "jace.pixelOffice.layout.v1";
export const OFFICE_CAMERA_STORAGE_KEY =
  "jace.pixelOffice.camera.v1";

const SPECIALIST_SEATS: OfficeSeat[] = [
  { id: "research", specialist: "research", col: 3, row: 5, facing: "up" },
  { id: "code", specialist: "code", col: 7, row: 5, facing: "up" },
  { id: "files", specialist: "files", col: 11, row: 5, facing: "up" },
  { id: "analyst", specialist: "analyst", col: 15, row: 5, facing: "up" },
  { id: "general", specialist: "general", col: 19, row: 5, facing: "up" },
];

const OVERFLOW_SEATS: OfficeSeat[] = [
  { id: "overflow-1", col: 7, row: 9, facing: "up" },
  { id: "overflow-2", col: 11, row: 9, facing: "up" },
  { id: "overflow-3", col: 15, row: 9, facing: "up" },
];

function deskFurniture(
  seat: OfficeSeat,
  prefix = "desk",
): FurniturePlacement[] {
  return [
    {
      id: `${prefix}-${seat.id}`,
      sprite: "desk",
      col: seat.col,
      row: seat.row - 1,
      blocks: true,
    },
    {
      id: `chair-${seat.id}`,
      sprite: "chair",
      col: seat.col,
      row: seat.row,
      blocks: false,
    },
  ];
}

export function createDefaultOfficeLayout(): OfficeLayoutConfig {
  const furniture: FurniturePlacement[] = [
    ...SPECIALIST_SEATS.flatMap((seat) => deskFurniture(seat)),
    ...OVERFLOW_SEATS.flatMap((seat) => deskFurniture(seat, "hotdesk")),
    { id: "server-a", sprite: "server", col: 1, row: 4, blocks: true },
    { id: "server-b", sprite: "server", col: 1, row: 6, blocks: true },
    { id: "shelf", sprite: "shelf", col: 21, row: 4, blocks: true },
    { id: "cabinet", sprite: "cabinet", col: 21, row: 6, blocks: true },
    { id: "coffee", sprite: "coffee", col: 2, row: 10, blocks: true },
    { id: "printer", sprite: "printer", col: 20, row: 10, blocks: true },
    { id: "plant-left", sprite: "plant", col: 1, row: 10 },
    { id: "plant-right", sprite: "plant", col: 21, row: 10 },
    { id: "lamp-left", sprite: "lamp", col: 5, row: 2, wallMounted: true },
    { id: "lamp-right", sprite: "lamp", col: 17, row: 2, wallMounted: true },
    { id: "rug-centre", sprite: "rug", col: 11, row: 11 },
  ];

  return {
    version: 1,
    cols: 23,
    rows: 13,
    seats: [...SPECIALIST_SEATS, ...OVERFLOW_SEATS],
    furniture,
  };
}

function validLayout(value: unknown): value is OfficeLayoutConfig {
  if (!value || typeof value !== "object") return false;

  const candidate = value as Partial<OfficeLayoutConfig>;

  return (
    candidate.version === 1 &&
    typeof candidate.cols === "number" &&
    typeof candidate.rows === "number" &&
    Array.isArray(candidate.seats) &&
    Array.isArray(candidate.furniture)
  );
}

export function loadOfficeLayout(): OfficeLayoutConfig {
  try {
    const raw = window.localStorage.getItem(OFFICE_LAYOUT_STORAGE_KEY);

    if (raw) {
      const parsed: unknown = JSON.parse(raw);

      if (validLayout(parsed)) {
        return parsed;
      }
    }
  } catch {
    // Corrupt saved layout should not prevent office startup.
  }

  const fallback = createDefaultOfficeLayout();
  saveOfficeLayout(fallback);
  return fallback;
}

export function saveOfficeLayout(layout: OfficeLayoutConfig) {
  try {
    window.localStorage.setItem(
      OFFICE_LAYOUT_STORAGE_KEY,
      JSON.stringify(layout),
    );
  } catch {
    // Best-effort persistence.
  }
}

export function resetOfficeLayout() {
  const layout = createDefaultOfficeLayout();
  saveOfficeLayout(layout);
  return layout;
}

export function tileKey(col: number, row: number): string {
  return `${col},${row}`;
}

export function tileCenter(col: number, row: number) {
  return {
    x: col * TILE_SIZE + TILE_SIZE / 2,
    y: row * TILE_SIZE + TILE_SIZE / 2,
  };
}

export function buildBlockedTiles(
  layout: OfficeLayoutConfig,
): Set<string> {
  const blocked = new Set<string>();

  for (const furniture of layout.furniture) {
    if (!furniture.blocks) continue;

    const width = Math.max(1, furniture.widthTiles ?? 1);
    const height = Math.max(1, furniture.heightTiles ?? 1);

    for (let rowOffset = 0; rowOffset < height; rowOffset += 1) {
      for (let colOffset = 0; colOffset < width; colOffset += 1) {
        blocked.add(
          tileKey(
            furniture.col + colOffset,
            furniture.row + rowOffset,
          ),
        );
      }
    }
  }

  for (const seat of layout.seats) {
    blocked.delete(tileKey(seat.col, seat.row));
  }

  return blocked;
}

export function isWalkable(
  layout: OfficeLayoutConfig,
  blocked: Set<string>,
  col: number,
  row: number,
): boolean {
  return (
    col >= 0 &&
    row >= 2 &&
    col < layout.cols &&
    row < layout.rows &&
    !blocked.has(tileKey(col, row))
  );
}

export function collectWalkableTiles(
  layout: OfficeLayoutConfig,
  blocked: Set<string>,
): OfficePoint[] {
  const output: OfficePoint[] = [];

  for (let row = 2; row < layout.rows; row += 1) {
    for (let col = 0; col < layout.cols; col += 1) {
      if (isWalkable(layout, blocked, col, row)) {
        output.push({ col, row });
      }
    }
  }

  return output;
}

export function findPath(
  layout: OfficeLayoutConfig,
  blocked: Set<string>,
  startCol: number,
  startRow: number,
  targetCol: number,
  targetRow: number,
): OfficePoint[] {
  if (startCol === targetCol && startRow === targetRow) {
    return [];
  }

  if (!isWalkable(layout, blocked, targetCol, targetRow)) {
    return [];
  }

  const startKey = tileKey(startCol, startRow);
  const targetKey = tileKey(targetCol, targetRow);

  const queue: OfficePoint[] = [{ col: startCol, row: startRow }];
  const visited = new Set<string>([startKey]);
  const previous = new Map<string, string>();
  const directions = [
    { dc: 1, dr: 0 },
    { dc: -1, dr: 0 },
    { dc: 0, dr: 1 },
    { dc: 0, dr: -1 },
  ];

  let cursor = 0;

  while (cursor < queue.length) {
    const current = queue[cursor];
    cursor += 1;

    for (const direction of directions) {
      const col = current.col + direction.dc;
      const row = current.row + direction.dr;

      if (!isWalkable(layout, blocked, col, row)) {
        continue;
      }

      const key = tileKey(col, row);

      if (visited.has(key)) {
        continue;
      }

      visited.add(key);
      previous.set(key, tileKey(current.col, current.row));

      if (key === targetKey) {
        const path: OfficePoint[] = [];
        let step = targetKey;

        while (step !== startKey) {
          const [stepCol, stepRow] = step.split(",").map(Number);
          path.push({ col: stepCol, row: stepRow });
          step = previous.get(step) ?? startKey;
        }

        path.reverse();
        return path;
      }

      queue.push({ col, row });
    }
  }

  return [];
}
