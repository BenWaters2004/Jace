import type {
  CarpetZone,
  FurniturePlacement,
  OfficeLayoutConfig,
  OfficePoint,
  OfficeRoomZone,
  OfficeSeat,
  OfficeWallSegment,
} from "./types";

export const TILE_SIZE = 16;

export const OFFICE_LAYOUT_STORAGE_KEY =
  "jace.pixelOffice.layout.pixelAgents.v1";

export const OFFICE_CAMERA_STORAGE_KEY =
  "jace.pixelOffice.camera.pixelAgents.v1";

const SPECIALIST_SEATS: OfficeSeat[] = [
  { id: "research", specialist: "research", col: 4, row: 8, facing: "up" },
  { id: "code", specialist: "code", col: 10, row: 8, facing: "up" },
  { id: "files", specialist: "files", col: 16, row: 8, facing: "up" },
  { id: "analyst", specialist: "analyst", col: 22, row: 8, facing: "up" },
  { id: "general", specialist: "general", col: 28, row: 8, facing: "up" },
];

const OVERFLOW_SEATS: OfficeSeat[] = [
  { id: "overflow-1", col: 9, row: 14, facing: "up" },
  { id: "overflow-2", col: 17, row: 14, facing: "up" },
  { id: "overflow-3", col: 25, row: 14, facing: "up" },
];

const ROOMS: OfficeRoomZone[] = [
  {
    id: "office",
    label: "Main Office",
    theme: "office",
    col: 2,
    row: 2,
    width: 33,
    height: 17,
    floorPattern: 0,
    floorTint: "#315851",
  },
  {
    id: "break",
    label: "Break Room",
    theme: "break",
    col: 2,
    row: 19,
    width: 16,
    height: 9,
    floorPattern: 7,
    floorTint: "#5b6240",
  },
  {
    id: "lounge",
    label: "Lounge",
    theme: "lounge",
    col: 18,
    row: 19,
    width: 17,
    height: 9,
    floorPattern: 8,
    floorTint: "#66543e",
  },
  {
    id: "server",
    label: "Server Room",
    theme: "server",
    col: 35,
    row: 2,
    width: 15,
    height: 11,
    floorPattern: 1,
    floorTint: "#314a59",
  },
  {
    id: "meeting",
    label: "Meeting Room",
    theme: "meeting",
    col: 35,
    row: 13,
    width: 15,
    height: 15,
    floorPattern: 4,
    floorTint: "#504456",
  },
];

const WALLS: OfficeWallSegment[] = [
  { id: "north", orientation: "horizontal", col: 2, row: 2, length: 48 },
  { id: "west", orientation: "vertical", col: 2, row: 2, length: 26 },
  { id: "east", orientation: "vertical", col: 49, row: 2, length: 26 },
  { id: "south", orientation: "horizontal", col: 2, row: 27, length: 48 },

  {
    id: "office-south",
    orientation: "horizontal",
    col: 2,
    row: 18,
    length: 33,
    doorways: [
      { offset: 7, size: 3 },
      { offset: 22, size: 3 },
    ],
  },
  {
    id: "office-right",
    orientation: "vertical",
    col: 34,
    row: 2,
    length: 17,
    doorways: [
      { offset: 4, size: 3 },
      { offset: 12, size: 3 },
    ],
  },
  {
    id: "break-lounge",
    orientation: "vertical",
    col: 17,
    row: 19,
    length: 9,
    doorways: [
      { offset: 3, size: 3 },
    ],
  },
  {
    id: "server-meeting",
    orientation: "horizontal",
    col: 35,
    row: 12,
    length: 15,
    doorways: [
      { offset: 6, size: 3 },
    ],
  },
];

const CARPETS: CarpetZone[] = [
  {
    id: "break-carpet",
    carpetIndex: 0,
    col: 8,
    row: 22,
    width: 6,
    height: 4,
  },
  {
    id: "lounge-carpet",
    carpetIndex: 0,
    col: 21,
    row: 22,
    width: 9,
    height: 4,
  },
];

function deskStation(
  seat: OfficeSeat,
  deskCol: number,
  deskRow: number,
  prefix = "desk",
): FurniturePlacement[] {
  return [
    {
      id: `${prefix}-${seat.id}`,
      assetGroup: "DESK",
      orientation: "front",
      col: deskCol,
      row: deskRow,
      footprintW: 3,
      footprintH: 2,
      blocks: true,
    },
    {
      id: `pc-${seat.id}`,
      assetGroup: "PC",
      orientation: "front",
      state: "off",
      linkedSeatId: seat.id,
      col: deskCol + 1,
      row: deskRow,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
      surface: true,
    },
    {
      id: `chair-${seat.id}`,
      assetGroup: "CUSHIONED_CHAIR",
      orientation: "back",
      col: seat.col,
      row: seat.row,
      footprintW: 1,
      footprintH: 1,
      blocks: false,
    },
  ];
}

export function createDefaultOfficeLayout():
  OfficeLayoutConfig {
  const furniture: FurniturePlacement[] = [
    ...deskStation(SPECIALIST_SEATS[0], 3, 6),
    ...deskStation(SPECIALIST_SEATS[1], 9, 6),
    ...deskStation(SPECIALIST_SEATS[2], 15, 6),
    ...deskStation(SPECIALIST_SEATS[3], 21, 6),
    ...deskStation(SPECIALIST_SEATS[4], 27, 6),

    ...deskStation(OVERFLOW_SEATS[0], 8, 12, "hotdesk"),
    ...deskStation(OVERFLOW_SEATS[1], 16, 12, "hotdesk"),
    ...deskStation(OVERFLOW_SEATS[2], 24, 12, "hotdesk"),

    // Main office.
    {
      id: "office-books",
      assetGroup: "BOOKSHELF",
      col: 3,
      row: 3,
      footprintW: 2,
      footprintH: 1,
      wallMounted: true,
    },
    {
      id: "office-clock",
      assetGroup: "CLOCK",
      col: 16,
      row: 3,
      footprintW: 1,
      footprintH: 2,
      wallMounted: true,
    },
    {
      id: "office-plant",
      assetGroup: "PLANT",
      col: 31,
      row: 15,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "office-bin",
      assetGroup: "BIN",
      col: 32,
      row: 9,
      footprintW: 1,
      footprintH: 1,
      blocks: true,
    },

    // Break room.
    {
      id: "break-table",
      assetGroup: "SMALL_TABLE",
      orientation: "front",
      col: 5,
      row: 22,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "break-coffee",
      assetGroup: "COFFEE",
      col: 5,
      row: 22,
      footprintW: 1,
      footprintH: 1,
      surface: true,
      offsetX: 8,
      offsetY: -8,
    },
    {
      id: "break-chair-a",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      col: 4,
      row: 23,
      footprintW: 1,
      footprintH: 2,
    },
    {
      id: "break-chair-b",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      mirrorX: true,
      col: 7,
      row: 23,
      footprintW: 1,
      footprintH: 2,
    },
    {
      id: "break-bench-a",
      assetGroup: "CUSHIONED_BENCH",
      col: 10,
      row: 24,
      footprintW: 1,
      footprintH: 1,
    },
    {
      id: "break-bench-b",
      assetGroup: "CUSHIONED_BENCH",
      col: 12,
      row: 24,
      footprintW: 1,
      footprintH: 1,
    },
    {
      id: "break-plant",
      assetGroup: "PLANT",
      col: 15,
      row: 24,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "break-painting",
      assetGroup: "SMALL_PAINTING",
      col: 7,
      row: 20,
      footprintW: 1,
      footprintH: 2,
      wallMounted: true,
    },

    // Lounge.
    {
      id: "lounge-sofa",
      assetGroup: "SOFA",
      orientation: "front",
      col: 21,
      row: 24,
      footprintW: 2,
      footprintH: 1,
      blocks: true,
    },
    {
      id: "lounge-sofa-side",
      assetGroup: "SOFA",
      orientation: "side",
      col: 29,
      row: 22,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "lounge-coffee-table",
      assetGroup: "COFFEE_TABLE",
      col: 24,
      row: 23,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "lounge-books",
      assetGroup: "DOUBLE_BOOKSHELF",
      col: 19,
      row: 20,
      footprintW: 2,
      footprintH: 2,
      wallMounted: true,
    },
    {
      id: "lounge-large-plant",
      assetGroup: "LARGE_PLANT",
      col: 31,
      row: 23,
      footprintW: 2,
      footprintH: 3,
      blocks: true,
    },
    {
      id: "lounge-painting",
      assetGroup: "LARGE_PAINTING",
      col: 25,
      row: 20,
      footprintW: 2,
      footprintH: 2,
      wallMounted: true,
    },

    // Server room.
    {
      id: "server-desk-a",
      assetGroup: "DESK",
      orientation: "front",
      col: 37,
      row: 5,
      footprintW: 3,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "server-pc-a",
      assetGroup: "PC",
      orientation: "front",
      state: "on",
      col: 38,
      row: 5,
      footprintW: 1,
      footprintH: 2,
      surface: true,
    },
    {
      id: "server-desk-b",
      assetGroup: "DESK",
      orientation: "front",
      col: 43,
      row: 5,
      footprintW: 3,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "server-pc-b",
      assetGroup: "PC",
      orientation: "front",
      state: "on",
      col: 44,
      row: 5,
      footprintW: 1,
      footprintH: 2,
      surface: true,
    },
    {
      id: "server-storage-a",
      assetGroup: "DOUBLE_BOOKSHELF",
      col: 37,
      row: 9,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "server-storage-b",
      assetGroup: "DOUBLE_BOOKSHELF",
      col: 46,
      row: 9,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },

    // Meeting room.
    {
      id: "meeting-table",
      assetGroup: "TABLE_FRONT",
      col: 40,
      row: 17,
      footprintW: 3,
      footprintH: 4,
      blocks: true,
    },
    {
      id: "meeting-chair-left-a",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      col: 38,
      row: 18,
      footprintW: 1,
      footprintH: 2,
    },
    {
      id: "meeting-chair-left-b",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      col: 38,
      row: 22,
      footprintW: 1,
      footprintH: 2,
    },
    {
      id: "meeting-chair-right-a",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      mirrorX: true,
      col: 44,
      row: 18,
      footprintW: 1,
      footprintH: 2,
    },
    {
      id: "meeting-chair-right-b",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      mirrorX: true,
      col: 44,
      row: 22,
      footprintW: 1,
      footprintH: 2,
    },
    {
      id: "meeting-whiteboard",
      assetGroup: "WHITEBOARD",
      col: 40,
      row: 14,
      footprintW: 2,
      footprintH: 2,
      wallMounted: true,
    },
    {
      id: "meeting-plant",
      assetGroup: "PLANT",
      col: 47,
      row: 24,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
  ];

  return {
    version: 3,
    cols: 52,
    rows: 30,
    seats: [
      ...SPECIALIST_SEATS,
      ...OVERFLOW_SEATS,
    ],
    furniture,
    rooms: ROOMS,
    walls: WALLS,
    carpets: CARPETS,
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
    candidate.version === 3 &&
    typeof candidate.cols === "number" &&
    typeof candidate.rows === "number" &&
    Array.isArray(candidate.seats) &&
    Array.isArray(candidate.furniture) &&
    Array.isArray(candidate.rooms) &&
    Array.isArray(candidate.walls) &&
    Array.isArray(candidate.carpets)
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
      const parsed: unknown =
        JSON.parse(raw);

      if (validLayout(parsed)) {
        return parsed;
      }
    }
  } catch {
    // Corrupt saved layout should not break the office.
  }

  const fallback =
    createDefaultOfficeLayout();

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
  const layout =
    createDefaultOfficeLayout();

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
    x:
      col * TILE_SIZE +
      TILE_SIZE / 2,
    y:
      row * TILE_SIZE +
      TILE_SIZE / 2,
  };
}

export function tileBottomCenter(
  col: number,
  row: number,
) {
  return {
    x:
      col * TILE_SIZE +
      TILE_SIZE / 2,
    y:
      (row + 1) * TILE_SIZE,
  };
}

function inDoorway(
  wall: OfficeWallSegment,
  offset: number,
) {
  return (
    wall.doorways?.some(
      (doorway) =>
        offset >= doorway.offset &&
        offset <
          doorway.offset +
            doorway.size,
    ) ?? false
  );
}

export function buildWallTiles(
  layout: OfficeLayoutConfig,
): Set<string> {
  const walls =
    new Set<string>();

  for (const wall of layout.walls) {
    for (
      let index = 0;
      index < wall.length;
      index += 1
    ) {
      if (
        inDoorway(
          wall,
          index,
        )
      ) {
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

      walls.add(
        tileKey(col, row),
      );
    }
  }

  return walls;
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
        col <
          room.col + room.width &&
        row >= room.row &&
        row <
          room.row + room.height,
    ) ?? null
  );
}

export function buildBlockedTiles(
  layout: OfficeLayoutConfig,
): Set<string> {
  const blocked =
    buildWallTiles(layout);

  for (
    const furniture
    of layout.furniture
  ) {
    if (!furniture.blocks) {
      continue;
    }

    for (
      let rowOffset = 0;
      rowOffset <
        furniture.footprintH;
      rowOffset += 1
    ) {
      for (
        let colOffset = 0;
        colOffset <
          furniture.footprintW;
        colOffset += 1
      ) {
        blocked.add(
          tileKey(
            furniture.col +
              colOffset,
            furniture.row +
              rowOffset,
          ),
        );
      }
    }
  }

  for (const seat of layout.seats) {
    blocked.delete(
      tileKey(
        seat.col,
        seat.row,
      ),
    );
  }

  return blocked;
}

export function isWalkable(
  layout: OfficeLayoutConfig,
  blocked: Set<string>,
  col: number,
  row: number,
): boolean {
  const room =
    findRoomForTile(
      layout,
      col,
      row,
    );

  return (
    room !== null &&
    col >= 0 &&
    row >= 0 &&
    col < layout.cols &&
    row < layout.rows &&
    !blocked.has(
      tileKey(col, row),
    )
  );
}

export function collectWalkableTiles(
  layout: OfficeLayoutConfig,
  blocked: Set<string>,
  allowedRoomIds?: string[],
): OfficePoint[] {
  const allowed =
    allowedRoomIds
      ? new Set(allowedRoomIds)
      : null;

  const output: OfficePoint[] = [];

  for (const room of layout.rooms) {
    if (
      allowed &&
      !allowed.has(room.id)
    ) {
      continue;
    }

    for (
      let row = room.row;
      row <
        room.row + room.height;
      row += 1
    ) {
      for (
        let col = room.col;
        col <
          room.col + room.width;
        col += 1
      ) {
        if (
          isWalkable(
            layout,
            blocked,
            col,
            row,
          )
        ) {
          output.push({
            col,
            row,
          });
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
    tileKey(
      startCol,
      startRow,
    );

  const targetKey =
    tileKey(
      targetCol,
      targetRow,
    );

  const queue: OfficePoint[] = [
    {
      col: startCol,
      row: startRow,
    },
  ];

  const visited =
    new Set<string>([
      startKey,
    ]);

  const previous =
    new Map<string, string>();

  const directions = [
    { dc: 1, dr: 0 },
    { dc: -1, dr: 0 },
    { dc: 0, dr: 1 },
    { dc: 0, dr: -1 },
  ];

  let cursor = 0;

  while (
    cursor < queue.length
  ) {
    const current =
      queue[cursor];

    cursor += 1;

    for (
      const direction
      of directions
    ) {
      const col =
        current.col +
        direction.dc;

      const row =
        current.row +
        direction.dr;

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

      const key =
        tileKey(col, row);

      if (
        visited.has(key)
      ) {
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

      if (
        key === targetKey
      ) {
        const path:
          OfficePoint[] = [];

        let step =
          targetKey;

        while (
          step !== startKey
        ) {
          const [
            stepCol,
            stepRow,
          ] =
            step
              .split(",")
              .map(Number);

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

      queue.push({
        col,
        row,
      });
    }
  }

  return [];
}
