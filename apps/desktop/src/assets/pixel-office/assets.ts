import type {
  PixelAgentsAssetIndex,
} from "./types";

const ASSET_FOLDER =
  "pixel-agents-assets";

let resolvedAssetRoot:
  string | null = null;

function trimTrailingSlash(
  value: string,
): string {
  return value.replace(
    /\/+$/,
    "",
  );
}

function candidateAssetRoots():
  string[] {
  const roots:
    string[] = [];

  const viteEnv =
    (
      import.meta as ImportMeta & {
        env?: {
          BASE_URL?: string;
        };
      }
    ).env;

  const viteBase =
    viteEnv?.BASE_URL ??
    "/";

  const base =
    trimTrailingSlash(
      viteBase,
    );

  roots.push(
    `${base}/${ASSET_FOLDER}`,
  );

  roots.push(
    `/${ASSET_FOLDER}`,
  );

  try {
    const relative =
      new URL(
        `${ASSET_FOLDER}/`,
        window.location.href,
      )
        .toString()
        .replace(
          /\/$/,
          "",
        );

    roots.push(
      relative,
    );
  } catch {
    // The normal Vite/Tauri candidates above remain available.
  }

  return [
    ...new Set(
      roots
        .map(
          (root) =>
            root.replace(
              /([^:]\/)\/+/g,
              "$1",
            ),
        )
        .filter(Boolean),
    ),
  ];
}

function validateIndex(
  value:
    unknown,
): value is PixelAgentsAssetIndex {
  if (
    !value ||
    typeof value !== "object"
  ) {
    return false;
  }

  const index =
    value as Partial<
      PixelAgentsAssetIndex
    >;

  return (
    index.version === 1 &&
    Array.isArray(
      index.characters,
    ) &&
    Array.isArray(
      index.floors,
    ) &&
    Array.isArray(
      index.walls,
    ) &&
    Array.isArray(
      index.carpets,
    ) &&
    Array.isArray(
      index.pets,
    ) &&
    Array.isArray(
      index.furniture,
    )
  );
}

export async function loadPixelAgentsAssetIndex():
  Promise<PixelAgentsAssetIndex> {
  const failures:
    string[] = [];

  for (
    const root
    of candidateAssetRoots()
  ) {
    const url =
      `${root}/_jace-asset-index.json`;

    try {
      const response =
        await fetch(
          url,
          {
            cache:
              "no-store",
          },
        );

      if (
        !response.ok
      ) {
        failures.push(
          `${url} -> HTTP ${response.status}`,
        );

        continue;
      }

      const value:
        unknown =
          await response.json();

      if (
        !validateIndex(
          value,
        )
      ) {
        failures.push(
          `${url} -> invalid index`,
        );

        continue;
      }

      resolvedAssetRoot =
        root;

      return value;
    } catch (error) {
      failures.push(
        `${url} -> ${
          error instanceof Error
            ? error.message
            : "request failed"
        }`,
      );
    }
  }

  throw new Error(
    "Pixel Agents assets exist locally but Jace could not load the asset index. " +
    "Run scripts/test-pixel-agents-assets.ps1 while 'npm run tauri dev' is running. " +
    `Tried: ${failures.join(" | ")}`,
  );
}

export function getPixelAgentsAssetRoot():
  string | null {
  return resolvedAssetRoot;
}

export function pixelAssetUrl(
  relativePath: string,
): string {
  const clean =
    relativePath.replace(
      /^\/+/,
      "",
    );

  const root =
    resolvedAssetRoot ??
    candidateAssetRoots()[0];

  return `${root}/${clean}`;
}

export const SPECIALIST_CHARACTER_INDEX:
  Record<string, number> = {
    research: 0,
    code: 1,
    files: 2,
    analyst: 3,
    general: 4,
  };
