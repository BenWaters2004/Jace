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

/**
 * Pixel Agents' published default office is a 21 x 22 layout. This key is
 * intentionally new so older Jace office layouts cannot override the corrected
 * default after the upgrade.
 */
export const OFFICE_LAYOUT_STORAGE_KEY =
  "jace.pixelOffice.layout.pixelAgents.default.v8";

export const OFFICE_CAMERA_STORAGE_KEY =
  "jace.pixelOffice.camera.pixelAgents.v3";

/**
 * Match the darker blue-grey wall tone from the reference office while still
 * preserving the Pixel Agents wall shapes and shading.
 */
export const WALL_TINT =
  "#2E435B";

const LAYOUT_VERSION = 13;

/**
 * Pixel Agents derives seats from chair furniture. Jace currently keeps seats
 * explicitly because workers are mapped to named specialists, so these seats
 * mirror the chairs/benches/sofas in the upstream default office.
 */
const SPECIALIST_SEATS: OfficeSeat[] = [
  {
    id: "research",
    specialist: "research",
    col: 4,
    row: 14,
    facing: "up",
  },
  {
    id: "code",
    specialist: "code",
    col: 8,
    row: 14,
    facing: "up",
  },
  {
    id: "files",
    specialist: "files",
    col: 4,
    row: 15,
    facing: "right",
  },
  {
    id: "analyst",
    specialist: "analyst",
    col: 8,
    row: 15,
    facing: "left",
  },
  {
    id: "general",
    specialist: "general",
    col: 4,
    row: 17,
    facing: "right",
  },
];

const OVERFLOW_SEATS: OfficeSeat[] = [
  {
    id: "overflow-1",
    col: 8,
    row: 17,
    facing: "left",
  },
  {
    id: "overflow-2",
    col: 14,
    row: 15,
    facing: "right",
  },
  {
    id: "overflow-3",
    col: 17,
    row: 15,
    facing: "left",
  },
];

/**
 * Jace models floor regions as room zones. These bounds describe only the
 * interior floor area inside the walls so the renderer can draw the correct
 * reference-like flooring without bleeding underneath wall tiles.
 */
const ROOMS: OfficeRoomZone[] = [
  {
    id: "office",
    label: "",
    theme: "office",
    col: 2,
    row: 11,
    width: 9,
    height: 10,
    floorPattern: 0,
    floorTint: "#7A5434",
  },
  {
    id: "lounge",
    label: "",
    theme: "lounge",
    col: 11,
    row: 11,
    width: 9,
    height: 8,
    floorPattern: 0,
    floorTint: "#55789F",
  },
  {
    id: "break",
    label: "",
    theme: "break",
    col: 11,
    row: 19,
    width: 9,
    height: 2,
    floorPattern: 0,
    floorTint: "#DADFE3",
  },
];

const WALLS: OfficeWallSegment[] = [
  {
    id: "north",
    orientation: "horizontal",
    col: 1,
    row: 10,
    length: 20,
  },
  {
    id: "west",
    orientation: "vertical",
    col: 1,
    row: 10,
    length: 11,
  },
  {
    id: "east",
    orientation: "vertical",
    col: 20,
    row: 10,
    length: 11,
  },
  {
    id: "centre-divider",
    orientation: "vertical",
    col: 11,
    row: 10,
    length: 11,
    doorways: [
      {
        offset: 5,
        size: 4,
      },
    ],
  },
];

const CARPETS: CarpetZone[] = [];

function wallItem(
  id: string,
  assetGroup: string,
  col: number,
  wallRow: number,
  footprintW: number,
  footprintH: number,
): FurniturePlacement {
  return {
    id,
    assetGroup,
    col,
    row:
      wallRow -
      footprintH +
      1,
    footprintW,
    footprintH,
    wallMounted: true,
    blocks: false,
  };
}

export function createDefaultOfficeLayout():
  OfficeLayoutConfig {
  const furniture: FurniturePlacement[] = [
    // -------------------------------------------------------------------
    // Pixel Agents default layout. Keep the original furniture placement and
    // only swap the wall clock for the custom BW plaque.
    // -------------------------------------------------------------------
    {
      id: "default-table-front",
      assetGroup: "TABLE_FRONT",
      col: 5,
      row: 15,
      footprintW: 3,
      footprintH: 4,
      blocks: true,
    },
    {
      id: "default-coffee-table",
      assetGroup: "COFFEE_TABLE",
      col: 15,
      row: 14,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-sofa-left",
      assetGroup: "SOFA",
      orientation: "side",
      col: 14,
      row: 14,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-sofa-back",
      assetGroup: "SOFA",
      orientation: "back",
      col: 15,
      row: 16,
      footprintW: 2,
      footprintH: 1,
      blocks: true,
    },
    {
      id: "default-sofa-front",
      assetGroup: "SOFA",
      orientation: "front",
      col: 15,
      row: 13,
      footprintW: 2,
      footprintH: 1,
      blocks: true,
    },
    {
      id: "default-sofa-right",
      assetGroup: "SOFA",
      orientation: "side",
      mirrorX: true,
      col: 17,
      row: 14,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },

    wallItem(
      "default-hanging-plant-right",
      "HANGING_PLANT",
      10,
      10,
      1,
      2,
    ),
    wallItem(
      "default-hanging-plant-left",
      "HANGING_PLANT",
      2,
      10,
      1,
      2,
    ),
    wallItem(
      "default-bookshelf-right",
      "DOUBLE_BOOKSHELF",
      8,
      10,
      2,
      2,
    ),
    wallItem(
      "default-bookshelf-left",
      "DOUBLE_BOOKSHELF",
      3,
      10,
      2,
      2,
    ),
    wallItem(
      "default-small-painting",
      "SMALL_PAINTING",
      13,
      10,
      1,
      2,
    ),
    {
      id: "default-bw-plaque",
      assetGroup: "BW_LOGO_PLAQUE",
      col: 5,
      row: 9,
      footprintW: 2,
      footprintH: 2,
      wallMounted: true,
      blocks: false,
      offsetX: 8,
    },

    {
      id: "default-plant-right",
      assetGroup: "PLANT",
      col: 19,
      row: 10,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-coffee-lounge",
      assetGroup: "COFFEE",
      col: 15,
      row: 15,
      footprintW: 1,
      footprintH: 1,
      blocks: false,
      surface: true,
    },

    {
      id: "default-chair-left-bottom",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      col: 4,
      row: 17,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
    },
    {
      id: "default-chair-left-top",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      col: 4,
      row: 15,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
    },
    {
      id: "default-chair-right-top",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      mirrorX: true,
      col: 8,
      row: 15,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
    },
    {
      id: "default-chair-right-bottom",
      assetGroup: "WOODEN_CHAIR",
      orientation: "side",
      mirrorX: true,
      col: 8,
      row: 17,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
    },

    {
      id: "default-desk-left",
      assetGroup: "DESK",
      orientation: "front",
      col: 3,
      row: 12,
      footprintW: 3,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-desk-right",
      assetGroup: "DESK",
      orientation: "front",
      col: 7,
      row: 12,
      footprintW: 3,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-bench-left",
      assetGroup: "CUSHIONED_BENCH",
      col: 4,
      row: 14,
      footprintW: 1,
      footprintH: 1,
      blocks: false,
    },
    {
      id: "default-bench-right",
      assetGroup: "CUSHIONED_BENCH",
      col: 8,
      row: 14,
      footprintW: 1,
      footprintH: 1,
      blocks: false,
    },
    {
      id: "default-pc-right",
      assetGroup: "PC",
      orientation: "front",
      state: "off",
      linkedSeatId: "code",
      col: 8,
      row: 12,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
      surface: true,
    },
    {
      id: "default-pc-left",
      assetGroup: "PC",
      orientation: "front",
      state: "off",
      linkedSeatId: "research",
      col: 4,
      row: 12,
      footprintW: 1,
      footprintH: 2,
      blocks: false,
      surface: true,
    },

    {
      id: "default-pc-table-left-top",
      assetGroup: "PC",
      orientation: "side",
      linkedSeatId: "files",
      col: 5,
      row: 16,
      footprintW: 2,
      footprintH: 1,
      blocks: false,
      surface: true,
    },
    {
      id: "default-pc-table-left-bottom",
      assetGroup: "PC",
      orientation: "side",
      linkedSeatId: "general",
      col: 5,
      row: 18,
      footprintW: 2,
      footprintH: 1,
      blocks: false,
      surface: true,
    },
    {
      id: "default-pc-table-right-top",
      assetGroup: "PC",
      orientation: "side",
      mirrorX: true,
      linkedSeatId: "analyst",
      col: 7,
      row: 16,
      footprintW: 2,
      footprintH: 1,
      blocks: false,
      surface: true,
    },
    {
      id: "default-pc-table-right-bottom",
      assetGroup: "PC",
      orientation: "side",
      mirrorX: true,
      linkedSeatId: "overflow-1",
      col: 7,
      row: 18,
      footprintW: 2,
      footprintH: 1,
      blocks: false,
      surface: true,
    },

    {
      id: "default-divider-plant",
      assetGroup: "PLANT",
      col: 12,
      row: 10,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    wallItem(
      "default-large-painting",
      "LARGE_PAINTING",
      15,
      10,
      2,
      2,
    ),
    {
      id: "default-bin",
      assetGroup: "BIN",
      col: 3,
      row: 20,
      footprintW: 1,
      footprintH: 1,
      blocks: true,
    },
    {
      id: "default-small-table-right",
      assetGroup: "SMALL_TABLE",
      orientation: "front",
      col: 18,
      row: 19,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-small-table-left",
      assetGroup: "SMALL_TABLE",
      orientation: "side",
      col: 2,
      row: 19,
      footprintW: 2,
      footprintH: 2,
      blocks: true,
    },
    {
      id: "default-coffee-left",
      assetGroup: "COFFEE",
      col: 2,
      row: 19,
      footprintW: 1,
      footprintH: 1,
      blocks: false,
      surface: true,
    },
    {
      id: "default-lower-left-plant",
      assetGroup: "PLANT",
      col: 2,
      row: 17,
      footprintW: 1,
      footprintH: 2,
      blocks: true,
    },
    wallItem(
      "default-small-painting-right",
      "SMALL_PAINTING",
      18,
      10,
      1,
      2,
    ),
  ];

  return {
    version: LAYOUT_VERSION,
    cols: 21,
    rows: 22,
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
  if (
    !value ||
    typeof value !== "object"
  ) {
    return false;
  }

  const candidate =
    value as Partial<OfficeLayoutConfig>;

  return (
    candidate.version === LAYOUT_VERSION &&
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

      if (
        validLayout(
          parsed,
        )
      ) {
        return parsed;
      }
    }
  } catch {
    // Corrupt saved layouts should never prevent the office loading.
  }

  const fallback =
    createDefaultOfficeLayout();

  saveOfficeLayout(
    fallback,
  );

  return fallback;
}

export function saveOfficeLayout(
  layout:
    OfficeLayoutConfig,
) {
  try {
    window.localStorage.setItem(
      OFFICE_LAYOUT_STORAGE_KEY,
      JSON.stringify(
        layout,
      ),
    );
  } catch {
    // Persistence is best-effort.
  }
}

export function resetOfficeLayout() {
  const layout =
    createDefaultOfficeLayout();

  saveOfficeLayout(
    layout,
  );

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
      col *
        TILE_SIZE +
      TILE_SIZE /
        2,
    y:
      row *
        TILE_SIZE +
      TILE_SIZE /
        2,
  };
}

export function tileBottomCenter(
  col: number,
  row: number,
) {
  return {
    x:
      col *
        TILE_SIZE +
      TILE_SIZE /
        2,
    y:
      (
        row +
        1
      ) *
      TILE_SIZE,
  };
}

function inDoorway(
  wall:
    OfficeWallSegment,
  offset:
    number,
) {
  return (
    wall.doorways
      ?.some(
        (doorway) =>
          offset >=
            doorway.offset &&
          offset <
            doorway.offset +
              doorway.size,
      ) ??
    false
  );
}

export function buildWallTiles(
  layout:
    OfficeLayoutConfig,
): Set<string> {
  const walls =
    new Set<string>();

  for (
    const wall
    of layout.walls
  ) {
    for (
      let index = 0;
      index <
        wall.length;
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
        wall.orientation ===
        "horizontal"
          ? wall.col +
            index
          : wall.col;

      const row =
        wall.orientation ===
        "vertical"
          ? wall.row +
            index
          : wall.row;

      walls.add(
        tileKey(
          col,
          row,
        ),
      );
    }
  }

  return walls;
}

export function findRoomForTile(
  layout:
    OfficeLayoutConfig,
  col:
    number,
  row:
    number,
): OfficeRoomZone | null {
  return (
    layout.rooms.find(
      (room) =>
        col >=
          room.col &&
        col <
          room.col +
            room.width &&
        row >=
          room.row &&
        row <
          room.row +
            room.height,
    ) ??
    null
  );
}

export function buildBlockedTiles(
  layout:
    OfficeLayoutConfig,
): Set<string> {
  const blocked =
    buildWallTiles(
      layout,
    );

  for (
    const furniture
    of layout.furniture
  ) {
    if (
      !furniture.blocks
    ) {
      continue;
    }

    for (
      let rowOffset =
        0;
      rowOffset <
        furniture.footprintH;
      rowOffset +=
        1
    ) {
      for (
        let colOffset =
          0;
        colOffset <
          furniture.footprintW;
        colOffset +=
          1
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

  for (
    const seat
    of layout.seats
  ) {
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
  layout:
    OfficeLayoutConfig,
  blocked:
    Set<string>,
  col:
    number,
  row:
    number,
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
    col <
      layout.cols &&
    row <
      layout.rows &&
    !blocked.has(
      tileKey(
        col,
        row,
      ),
    )
  );
}

export function collectWalkableTiles(
  layout:
    OfficeLayoutConfig,
  blocked:
    Set<string>,
  allowedRoomIds?:
    string[],
): OfficePoint[] {
  const allowed =
    allowedRoomIds
      ? new Set(
          allowedRoomIds,
        )
      : null;

  const output:
    OfficePoint[] = [];

  for (
    const room
    of layout.rooms
  ) {
    if (
      allowed &&
      !allowed.has(
        room.id,
      )
    ) {
      continue;
    }

    for (
      let row =
        room.row;
      row <
        room.row +
          room.height;
      row +=
        1
    ) {
      for (
        let col =
          room.col;
        col <
          room.col +
            room.width;
        col +=
          1
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
  layout:
    OfficeLayoutConfig,
  blocked:
    Set<string>,
  startCol:
    number,
  startRow:
    number,
  targetCol:
    number,
  targetRow:
    number,
): OfficePoint[] {
  if (
    startCol ===
      targetCol &&
    startRow ===
      targetRow
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

  const queue:
    OfficePoint[] = [
      {
        col:
          startCol,
        row:
          startRow,
      },
    ];

  const visited =
    new Set<string>([
      startKey,
    ]);

  const previous =
    new Map<
      string,
      string
    >();

  const directions = [
    {
      dc: 1,
      dr: 0,
    },
    {
      dc: -1,
      dr: 0,
    },
    {
      dc: 0,
      dr: 1,
    },
    {
      dc: 0,
      dr: -1,
    },
  ];

  let cursor =
    0;

  while (
    cursor <
    queue.length
  ) {
    const current =
      queue[cursor];

    cursor +=
      1;

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
        tileKey(
          col,
          row,
        );

      if (
        visited.has(
          key,
        )
      ) {
        continue;
      }

      visited.add(
        key,
      );

      previous.set(
        key,
        tileKey(
          current.col,
          current.row,
        ),
      );

      if (
        key ===
        targetKey
      ) {
        const path:
          OfficePoint[] = [];

        let step =
          targetKey;

        while (
          step !==
          startKey
        ) {
          const [
            stepCol,
            stepRow,
          ] =
            step
              .split(
                ",",
              )
              .map(
                Number,
              );

          path.push({
            col:
              stepCol,
            row:
              stepRow,
          });

          step =
            previous.get(
              step,
            ) ??
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
