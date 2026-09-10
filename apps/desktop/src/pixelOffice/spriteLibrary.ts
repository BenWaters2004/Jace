import {
  CHARACTER_ASSET_URLS,
  FURNITURE_ASSET_URL,
} from "./assets";
import {
  CHARACTER_SPRITE_DEFINITION,
  FURNITURE_FRAME_SIZE,
  FURNITURE_SPRITES,
} from "./spriteManifest";
import type {
  CharacterMode,
  FurnitureSpriteId,
  OfficeDirection,
} from "./types";

type SpecialistId =
  | "research"
  | "code"
  | "files"
  | "analyst"
  | "general";

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();

    image.onload = () => resolve(image);
    image.onerror = () =>
      reject(
        new Error(`Could not load pixel-office asset: ${url}`),
      );

    image.src = url;
  });
}

function characterRow(
  mode: CharacterMode,
  direction: OfficeDirection,
): number {
  if (mode === "walk") {
    return CHARACTER_SPRITE_DEFINITION.rows[direction];
  }

  if (mode === "type") {
    return CHARACTER_SPRITE_DEFINITION.rows.type;
  }

  if (mode === "read") {
    return CHARACTER_SPRITE_DEFINITION.rows.read;
  }

  if (mode === "think") {
    return CHARACTER_SPRITE_DEFINITION.rows.think;
  }

  return CHARACTER_SPRITE_DEFINITION.rows.idle;
}

export class PixelSpriteLibrary {
  private characters = new Map<string, HTMLImageElement>();
  private furniture: HTMLImageElement | null = null;
  private loading: Promise<void> | null = null;

  ready = false;
  error: string | null = null;

  load(): Promise<void> {
    if (this.loading) return this.loading;

    this.loading = this.loadInternal();
    return this.loading;
  }

  private async loadInternal() {
    try {
      const entries = Object.entries(
        CHARACTER_ASSET_URLS,
      ) as Array<[SpecialistId, string]>;

      const images = await Promise.all(
        entries.map(
          async ([id, url]) =>
            [id, await loadImage(url)] as const,
        ),
      );

      for (const [id, image] of images) {
        this.characters.set(id, image);
      }

      this.furniture = await loadImage(FURNITURE_ASSET_URL);

      this.ready = true;
      this.error = null;
    } catch (error) {
      this.ready = false;
      this.error =
        error instanceof Error
          ? error.message
          : "Pixel office assets failed to load.";
    }
  }

  drawCharacter(
    ctx: CanvasRenderingContext2D,
    specialistId: string,
    mode: CharacterMode,
    direction: OfficeDirection,
    frame: number,
    x: number,
    y: number,
    scale = 1,
  ): boolean {
    const image =
      this.characters.get(specialistId) ??
      this.characters.get("general");

    if (!image) return false;

    const definition = CHARACTER_SPRITE_DEFINITION;
    const row = characterRow(mode, direction);
    const frameCount = mode === "walk" ? 4 : 2;
    const column = Math.abs(frame) % frameCount;

    ctx.imageSmoothingEnabled = false;

    ctx.drawImage(
      image,
      column * definition.frameWidth,
      row * definition.frameHeight,
      definition.frameWidth,
      definition.frameHeight,
      Math.round(x - (definition.frameWidth * scale) / 2),
      Math.round(y - definition.frameHeight * scale + 4 * scale),
      definition.frameWidth * scale,
      definition.frameHeight * scale,
    );

    return true;
  }

  drawFurniture(
    ctx: CanvasRenderingContext2D,
    id: FurnitureSpriteId,
    x: number,
    y: number,
    scale = 1,
  ): boolean {
    if (!this.furniture) return false;

    const definition = FURNITURE_SPRITES[id];

    ctx.imageSmoothingEnabled = false;

    ctx.drawImage(
      this.furniture,
      definition.index * FURNITURE_FRAME_SIZE,
      0,
      definition.width,
      definition.height,
      Math.round(x - definition.anchorX * scale),
      Math.round(y - definition.anchorY * scale),
      definition.width * scale,
      definition.height * scale,
    );

    return true;
  }
}
