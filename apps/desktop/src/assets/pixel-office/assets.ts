import type {
  PixelAgentsAssetIndex,
} from "./types";

export const PIXEL_AGENTS_ASSET_ROOT =
  "pixel-agents-assets";

export const PIXEL_AGENTS_INDEX_URL =
  `${PIXEL_AGENTS_ASSET_ROOT}/_jace-asset-index.json`;

export function pixelAssetUrl(
  relativePath: string,
): string {
  const clean =
    relativePath.replace(/^\/+/, "");

  return `${PIXEL_AGENTS_ASSET_ROOT}/${clean}`;
}

export async function loadPixelAgentsAssetIndex():
  Promise<PixelAgentsAssetIndex> {
  const response =
    await fetch(
      PIXEL_AGENTS_INDEX_URL,
      {
        cache: "no-cache",
      },
    );

  if (!response.ok) {
    throw new Error(
      "Pixel Agents assets are not installed. " +
      "Run scripts/sync-pixel-agents-assets.ps1 from the Jace repository root.",
    );
  }

  const value =
    await response.json() as PixelAgentsAssetIndex;

  if (
    value.version !== 1 ||
    !Array.isArray(value.characters) ||
    !Array.isArray(value.furniture)
  ) {
    throw new Error(
      "The local Pixel Agents asset index is invalid. " +
      "Run sync-pixel-agents-assets.ps1 -Force.",
    );
  }

  return value;
}

export const SPECIALIST_CHARACTER_INDEX:
  Record<string, number> = {
    research: 0,
    code: 1,
    files: 2,
    analyst: 3,
    general: 4,
  };
