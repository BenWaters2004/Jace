import type {
  FurniturePlacement,
  OfficeLayoutConfig,
  OfficePoint,
  OfficeRoomZone,
  OfficeSeat,
  OfficeWallSegment,
} from "./types";

export const TILE_SIZE = 24;
export const OFFICE_LAYOUT_STORAGE_KEY =
  "jace.pixelOffice.layout.v2";
export const OFFICE_CAMERA_STORAGE_KEY =
  "jace.pixelOffice.camera.v2";

const SPECIALIST_SEATS: OfficeSeat[] = [
  { id: "research", specialist: "research", col: 5, row: 6, facing: "up" },
  { id: "code", specialist: "code", col: 9, row: 6, facing: "up" },
  { id: "files", specialist: "files", col: 13, row: 6, facing: "up" },
  { id: "analyst", specialist: "analyst", col: 17, row: 6, facing: "up" },
  { id: "general", specialist: "general", col: 20, row: 9, facing: "left" },
];

const OVERFLOW_SEATS: OfficeSeat[] = [
  { id: "overflow-1", col: 5, row: 10, facing: "up" },
  { id: "overflow-2", col: 9, row: 10, facing: "up" },
  { id: "overflow-3", col: 13, row: 10, facing: "up" },
];

const ROOMS: OfficeRoomZone[] = [
  {
    id: "office",
    label: "Main Office",
    theme: "office",
    col: 2,
    row: 2,
    width: 20,
    height: 10,
  },
  {
    id: "break",
    label: "Break Room",
    theme: "break",
    col: 2,
    row: 13,
    width: 10,
    height: 6,
  },
  {
    id: "lounge",
    label: "Lounge",
    theme: "lounge",
    col: 13,
    row: 13,
    width: 9,
    height: 6,
  },
  {
    id: "server",
    label: "Server Room",
    theme: "server",
    col: 23,
    row: 2,
    width: 10,
    height: 7,
  },
  {
    id: "meeting",
    label: "Meeting Room",
    theme: "meeting",
    col: 23,
    row: 10,
    width: 10,
    height: 9,
  },
];

const WALLS: OfficeWallSegment[] = [
  // Outer walls.
  { id: "north", orientation: "horizontal", col: 2, row: 2, length: 31 },
  { id: "south", orientation: "horizontal", col: 2, row: 18, length: 31 },
  { id: "west", orientation: "vertical", col: 2, row: 2, length: 17 },
  { id: "east", orientation: "vertical", col: 32, row: 2, length: 17 },

  // Internal separators.
  {
    id: "office-south",
    orientation: "horizontal",
    col: 2,
    row: 12,
    length: 20,
    doorways: [{ offset: 9, size: 3 }],
  },
  {
    id: "right-wing",
    orientation: "vertical",
    col: 22,
    row: 2,
    length: 17,
    doorways: [{ offset: 4, size: 2 }, { offset: 10, size: 2 }],
  },
  {
    id: "break-lounge",
    orientation: "vertical",
    col: 12,
    row: 13,
    length: 6,
    doorways: [{ offset: 2, size: 2 }],
  },
  {
    id: "server-meeting",
    orientation: "horizontal",
    col: 23,
    row: 9,
    length: 10,
    doorways: [{ offset: 4, size: 2 }],
  },
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

export function createDefaultOfficeLayout():
  OfficeLayoutConfig {
  const furniture: FurniturePlacement[] = [
    ...SPECIALIST_SEATS.flatMap((seat) =>
      deskFurniture(seat),
    ),
    ...OVERFLOW_SEATS.flatMap((seat) =>
      deskFurniture(seat, "hotdesk"),
    ),

    { id: "server-a", sprite: "server", col: 25, row: 4, blocks: true },
    { id: "server-b", sprite: "server", col: 28, row: 4, blocks: true },
    { id: "server-shelf", sprite: "shelf", col: 30, row: 4, blocks: true },

    { id: "meeting-table", sprite: "meeting_table", col: 27, row: 14, blocks: true, widthTiles: 2, heightTiles: 2 },
    { id: "meeting-plant", sprite: "plant", col: 31, row: 16 },

    { id: "break-coffee", sprite: "coffee", col: 4, row: 15, blocks: true },
    { id: "break-rug", sprite: "rug", col: 7, row: 16 },
    { id: "break-chair-a", sprite: "chair", col: 8, row: 15 },
    { id: "break-chair-b", sprite: "chair", col: 9, row: 16 },
    { id: "break-plant", sprite: "plant", col: 10, row: 16 },

    { id: "lounge-cabinet", sprite: "cabinet", col: 16, row: 15, blocks: true },
    { id: "lounge-printer", sprite: "printer", col: 20, row: 16, blocks: true },

    { id: "office-lamp-left", sprite: "lamp", col: 6, row: 3, wallMounted: true },
    { id: "office-lamp-right", sprite: "lamp", col: 17, row: 3, wallMounted: true },
    { id: "meeting-lamp", sprite: "lamp", col: 27, row: 11, wallMounted: true },
    { id: "server-lamp", sprite: "lamp", col: 28, row: 3, wallMounted: true },
  ];

  return {
    version: 2,
    cols: 35,
    rows: 21,
    seats: [
      ...SPECIALIST_SEATS,
      ...OVERFLOW_SEATS,
    ],
    furniture,
    rooms: ROOMS,
    walls: WALLS,
  };
}

function validLayout(
  value: unknown,
): value is OfficeLayoutConfig {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate =
    value as Partial<OfficeLayoutConfig>;

  return (
    candidate.version === 2 &&
    typeof candidate.cols === "number" &&
    typeof candidate.rows === "number" &&
    Array.isArray(candidate.seats) &&
    Array.isArray(candidate.furniture) &&
    Array.isArray(candidate.rooms) &&
    Array.isArray(candidate.walls)
  );
}

export function loadOfficeLayout():
  OfficeLayoutConfig {
  try {
    const raw =
      window.localStorage.getItem(
        OFFICE_LAYOUT_STORAGE_KEY,
      );

    if (raw) {
      const parsed: unknown = JSON.parse(raw);

      if (validLayout(parsed)) {
        return parsed;
      }
    }
  } catch {
    // Corrupt saved layout should never break the office.
  }

  const fallback = createDefaultOfficeLayout();
  saveOfficeLayout(fallback);
  return fallback;
}

export function saveOfficeLayout(
  layout: OfficeLayoutConfig,
) {
  try {
    window.localStorage.setItem(
      OFFICE_LAYOUT_STORAGE_KEY,
      JSON.stringify(layout),
    );
  } catch {
    // Persistence is best-effort.
  }
}

export function resetOfficeLayout() {
  const layout = createDefaultOfficeLayout();
  saveOfficeLayout(layout);
  return layout;
}

export function tileKey(
  col: number,
  row: number,
): string {
  return `${col},${row}`;
}

export function tileCenter(
  col: number,
  row: number,
) {
  return {
    x: col * TILE_SIZE + TILE_SIZE / 2,
    y: row * TILE_SIZE + TILE_SIZE / 2,
  };
}

function inDoorway(
  wall: OfficeWallSegment,
  offset: number,
) {
  return (
    wall.doorways?.some((doorway) =>
      offset >= doorway.offset &&
      offset < doorway.offset + doorway.size
    ) ?? false
  );
}

export function findRoomForTile(
  layout: OfficeLayoutConfig,
  col: number,
  row: number,
): OfficeRoomZone | null {
  return (
    layout.rooms.find(
      (room) =>
        col >= room.col &&
        col < room.col + room.width &&
        row >= room.row &&
        row < room.row + room.height,
    ) ?? null
  );
}

export function buildBlockedTiles(
  layout: OfficeLayoutConfig,
): Set<string> {
  const blocked = new Set<string>();

  for (const furniture of layout.furniture) {
    if (!furniture.blocks) continue;

    const width =
      Math.max(1, furniture.widthTiles ?? 1);
    const height =
      Math.max(1, furniture.heightTiles ?? 1);

    for (
      let rowOffset = 0;
      rowOffset < height;
      rowOffset += 1
    ) {
      for (
        let colOffset = 0;
        colOffset < width;
        colOffset += 1
      ) {
        blocked.add(
          tileKey(
            furniture.col + colOffset,
            furniture.row + rowOffset,
          ),
        );
      }
    }
  }

  for (const wall of layout.walls) {
    for (let index = 0; index < wall.length; index += 1) {
      if (inDoorway(wall, index)) {
        continue;
      }

      const col =
        wall.orientation === "horizontal"
          ? wall.col + index
          : wall.col;
      const row =
        wall.orientation === "vertical"
          ? wall.row + index
          : wall.row;

      blocked.add(tileKey(col, row));
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
  const room = findRoomForTile(layout, col, row);

  return (
    room !== null &&
    col >= 0 &&
    row >= 0 &&
    col < layout.cols &&
    row < layout.rows &&
    !blocked.has(tileKey(col, row))
  );
}

export function collectWalkableTiles(
  layout: OfficeLayoutConfig,
  blocked: Set<string>,
  allowedRoomIds?: string[],
): OfficePoint[] {
  const allowed =
    allowedRoomIds ? new Set(allowedRoomIds) : null;
  const output: OfficePoint[] = [];

  for (const room of layout.rooms) {
    if (allowed && !allowed.has(room.id)) {
      continue;
    }

    for (
      let row = room.row;
      row < room.row + room.height;
      row += 1
    ) {
      for (
        let col = room.col;
        col < room.col + room.width;
        col += 1
      ) {
        if (
          isWalkable(layout, blocked, col, row)
        ) {
          output.push({ col, row });
        }
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
  if (
    startCol === targetCol &&
    startRow === targetRow
  ) {
    return [];
  }

  if (
    !isWalkable(
      layout,
      blocked,
      targetCol,
      targetRow,
    )
  ) {
    return [];
  }

  const startKey =
    tileKey(startCol, startRow);
  const targetKey =
    tileKey(targetCol, targetRow);

  const queue: OfficePoint[] = [
    { col: startCol, row: startRow },
  ];

  const visited =
    new Set<string>([startKey]);
  const previous =
    new Map<string, string>();

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
      const col =
        current.col + direction.dc;
      const row =
        current.row + direction.dr;

      if (
        !isWalkable(
          layout,
          blocked,
          col,
          row,
        )
      ) {
        continue;
      }

      const key = tileKey(col, row);

      if (visited.has(key)) {
        continue;
      }

      visited.add(key);
      previous.set(
        key,
        tileKey(
          current.col,
          current.row,
        ),
      );

      if (key === targetKey) {
        const path: OfficePoint[] = [];
        let step = targetKey;

        while (step !== startKey) {
          const [stepCol, stepRow] =
            step.split(",").map(Number);

          path.push({
            col: stepCol,
            row: stepRow,
          });

          step =
            previous.get(step) ??
            startKey;
        }

        path.reverse();
        return path;
      }

      queue.push({ col, row });
    }
  }

  return [];
}
