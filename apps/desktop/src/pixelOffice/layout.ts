import type {
  OfficeDirection,
  OfficeLayout,
  OfficeSeat,
  OfficeTile,
} from "./types";

export const TILE_SIZE = 24;

export function tileKey(col: number, row: number): string {
  return `${col},${row}`;
}

export function tileCenter(col: number, row: number) {
  return {
    x: col * TILE_SIZE + TILE_SIZE / 2,
    y: row * TILE_SIZE + TILE_SIZE / 2,
  };
}

function seat(
  id: string,
  col: number,
  row: number,
  facing: OfficeDirection,
): OfficeSeat {
  return { id, col, row, facing };
}

export function createJaceOfficeLayout(): OfficeLayout {
  const cols = 24;
  const rows = 14;

  const seats = [
    seat("research", 4, 5, "up"),
    seat("code", 8, 5, "up"),
    seat("files", 12, 5, "up"),
    seat("analyst", 16, 5, "up"),
    seat("general", 20, 5, "up"),
  ];

  const blocked = new Set<string>();

  // Main top-row desks and monitors.
  for (const s of seats) {
    blocked.add(tileKey(s.col, s.row - 1));
  }

  // Left server bank.
  for (let row = 3; row <= 7; row += 1) {
    blocked.add(tileKey(1, row));
  }

  // Right storage / infrastructure.
  for (let row = 3; row <= 6; row += 1) {
    blocked.add(tileKey(22, row));
  }

  // Meeting table.
  for (let col = 9; col <= 14; col += 1) {
    blocked.add(tileKey(col, 10));
  }

  return { cols, rows, seats, blocked };
}

export function isInside(
  layout: OfficeLayout,
  col: number,
  row: number,
): boolean {
  return (
    col >= 0 &&
    row >= 0 &&
    col < layout.cols &&
    row < layout.rows
  );
}

export function isWalkable(
  layout: OfficeLayout,
  col: number,
  row: number,
): boolean {
  return (
    isInside(layout, col, row) &&
    !layout.blocked.has(tileKey(col, row))
  );
}

export function getWalkableTiles(layout: OfficeLayout): OfficeTile[] {
  const tiles: OfficeTile[] = [];

  for (let row = 0; row < layout.rows; row += 1) {
    for (let col = 0; col < layout.cols; col += 1) {
      if (isWalkable(layout, col, row)) {
        tiles.push({ col, row });
      }
    }
  }

  return tiles;
}

export function findPath(
  layout: OfficeLayout,
  startCol: number,
  startRow: number,
  targetCol: number,
  targetRow: number,
): OfficeTile[] {
  if (startCol === targetCol && startRow === targetRow) {
    return [];
  }

  if (!isWalkable(layout, targetCol, targetRow)) {
    return [];
  }

  const start = tileKey(startCol, startRow);
  const target = tileKey(targetCol, targetRow);

  const queue: OfficeTile[] = [{ col: startCol, row: startRow }];
  const visited = new Set<string>([start]);
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

      if (!isWalkable(layout, col, row)) continue;

      const key = tileKey(col, row);
      if (visited.has(key)) continue;

      visited.add(key);
      previous.set(key, tileKey(current.col, current.row));

      if (key === target) {
        const path: OfficeTile[] = [];
        let step = target;

        while (step !== start) {
          const [stepCol, stepRow] = step.split(",").map(Number);
          path.push({ col: stepCol, row: stepRow });
          step = previous.get(step) ?? start;
        }

        path.reverse();
        return path;
      }

      queue.push({ col, row });
    }
  }

  return [];
}
