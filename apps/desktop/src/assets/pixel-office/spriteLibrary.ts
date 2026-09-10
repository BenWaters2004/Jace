import {
  loadPixelAgentsAssetIndex,
  pixelAssetUrl,
} from "./assets";
import {
  UPSTREAM_CARPET,
  UPSTREAM_CHARACTER,
  UPSTREAM_PET,
  UPSTREAM_WALL,
} from "./spriteManifest";
import type {
  CharacterMode,
  FurniturePlacement,
  OfficeDirection,
  PetMode,
  PixelAgentsAssetIndex,
  ResolvedFurnitureAsset,
  UpstreamFurnitureGroupNode,
  UpstreamFurnitureManifest,
  UpstreamFurnitureManifestNode,
  UpstreamFurnitureOrientation,
} from "./types";

interface LoadedFurnitureAsset
  extends ResolvedFurnitureAsset {
  image: HTMLImageElement;
}

interface ResolveFurnitureOptions {
  orientation?:
    UpstreamFurnitureOrientation;
  state?: string;
  mirrorX?: boolean;
  animationFrame?: number;
}

interface InheritedManifestState {
  orientation?:
    UpstreamFurnitureOrientation;
  state?: string;
  mirrorSide?: boolean;
}

export interface PixelAssetDiagnostics {
  charactersLoaded: number;
  charactersExpected: number;
  floorsLoaded: number;
  floorsExpected: number;
  wallsLoaded: number;
  wallsExpected: number;
  carpetsLoaded: number;
  carpetsExpected: number;
  petsLoaded: number;
  petsExpected: number;
  furnitureGroupsLoaded: number;
  furnitureGroupsExpected: number;
  warnings: string[];
}

function loadImage(
  url: string,
): Promise<HTMLImageElement> {
  return new Promise(
    (resolve, reject) => {
      const image =
        new Image();

      image.onload =
        () =>
          resolve(
            image,
          );

      image.onerror =
        () =>
          reject(
            new Error(
              `Image failed: ${url}`,
            ),
          );

      image.src =
        url;
    },
  );
}

async function loadJson<T>(
  url: string,
): Promise<T> {
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
    throw new Error(
      `HTTP ${response.status}: ${url}`,
    );
  }

  return await response.json() as T;
}

function isGroup(
  node:
    UpstreamFurnitureManifestNode,
): node is UpstreamFurnitureGroupNode {
  return (
    node.type ===
    "group"
  );
}

function flattenFurnitureManifest(
  manifest:
    UpstreamFurnitureManifest,
  folder: string,
): ResolvedFurnitureAsset[] {
  const output:
    ResolvedFurnitureAsset[] = [];

  function pushAsset(
    node:
      Extract<
        UpstreamFurnitureManifestNode,
        {
          type: "asset";
        }
      >,
    inherited:
      InheritedManifestState,
  ) {
    output.push({
      rootId:
        manifest.id,
      name:
        manifest.name,
      category:
        manifest.category,
      folder,
      assetId:
        node.id,
      file:
        node.file ??
        `${node.id}.png`,
      width:
        node.width,
      height:
        node.height,
      footprintW:
        node.footprintW,
      footprintH:
        node.footprintH,
      backgroundTiles:
        manifest.backgroundTiles ??
        0,
      orientation:
        node.orientation ??
        inherited.orientation,
      state:
        node.state ??
        inherited.state,
      frame:
        node.frame,
      mirrorSide:
        node.mirrorSide ??
        inherited.mirrorSide ??
        false,
      canPlaceOnWalls:
        Boolean(
          manifest.canPlaceOnWalls,
        ),
      canPlaceOnSurfaces:
        Boolean(
          manifest.canPlaceOnSurfaces,
        ),
    });
  }

  function visit(
    node:
      UpstreamFurnitureManifestNode,
    inherited:
      InheritedManifestState,
  ) {
    const next:
      InheritedManifestState = {
        orientation:
          node.orientation ??
          inherited.orientation,
        state:
          node.state ??
          inherited.state,
        mirrorSide:
          node.mirrorSide ??
          inherited.mirrorSide,
      };

    if (
      isGroup(
        node,
      )
    ) {
      for (
        const member
        of node.members
      ) {
        visit(
          member,
          next,
        );
      }

      return;
    }

    pushAsset(
      node,
      next,
    );
  }

  if (
    manifest.type ===
    "group"
  ) {
    for (
      const member
      of manifest.members
    ) {
      visit(
        member,
        {},
      );
    }
  } else {
    pushAsset(
      manifest,
      {},
    );
  }

  return output;
}

function parseHex(
  hex: string,
): [
  number,
  number,
  number,
] {
  const clean =
    hex.replace(
      "#",
      "",
    );

  if (
    clean.length !==
    6
  ) {
    return [
      80,
      100,
      95,
    ];
  }

  return [
    Number.parseInt(
      clean.slice(
        0,
        2,
      ),
      16,
    ),
    Number.parseInt(
      clean.slice(
        2,
        4,
      ),
      16,
    ),
    Number.parseInt(
      clean.slice(
        4,
        6,
      ),
      16,
    ),
  ];
}

function positiveModulo(
  value: number,
  length: number,
): number {
  if (
    length <=
    0
  ) {
    return 0;
  }

  return (
    (
      value %
      length
    ) +
    length
  ) %
    length;
}

async function loadImageList(
  paths:
    string[],
): Promise<
  Array<
    HTMLImageElement |
    null
  >
> {
  return await Promise.all(
    paths.map(
      async (
        path,
      ) => {
        try {
          return await loadImage(
            pixelAssetUrl(
              path,
            ),
          );
        } catch {
          return null;
        }
      },
    ),
  );
}

export class PixelSpriteLibrary {
  private index:
    PixelAgentsAssetIndex | null =
      null;

  private characters:
    Array<
      HTMLImageElement |
      null
    > = [];

  private floors:
    Array<
      HTMLImageElement |
      null
    > = [];

  private walls:
    Array<
      HTMLImageElement |
      null
    > = [];

  private carpets:
    Array<
      HTMLImageElement |
      null
    > = [];

  private pets =
    new Map<
      string,
      HTMLImageElement
    >();

  private furniture =
    new Map<
      string,
      LoadedFurnitureAsset[]
    >();

  private floorTintCache =
    new Map<
      string,
      HTMLCanvasElement
    >();

  private loading:
    Promise<void> | null =
      null;

  private warnings:
    string[] = [];

  ready =
    false;

  error:
    string | null =
      null;

  sourceRef:
    string | null =
      null;

  load():
    Promise<void> {
  if (
      this.loading
    ) {
      return this.loading;
    }

    this.loading =
      this.loadInternal();

    return this.loading;
  }

  private async loadInternal() {
    try {
      const index =
        await loadPixelAgentsAssetIndex();

      this.index =
        index;

      this.sourceRef =
        index.source.ref;

      this.characters =
        await loadImageList(
          index.characters.map(
            (file) =>
              `characters/${file}`,
          ),
        );

      this.floors =
        await loadImageList(
          index.floors.map(
            (file) =>
              `floors/${file}`,
          ),
        );

      this.walls =
        await loadImageList(
          index.walls.map(
            (file) =>
              `walls/${file}`,
          ),
        );

      this.carpets =
        await loadImageList(
          index.carpets.map(
            (file) =>
              `carpets/${file}`,
          ),
        );

      for (
        const pet
        of index.pets
      ) {
        try {
          const image =
            await loadImage(
              pixelAssetUrl(
                pet.image,
              ),
            );

          this.pets.set(
            pet.id,
            image,
          );
        } catch (error) {
          this.warnings.push(
            `Pet ${pet.id}: ${
              error instanceof Error
                ? error.message
                : "load failed"
            }`,
          );
        }
      }

      const furnitureResults =
        await Promise.allSettled(
          index.furniture.map(
            async (
              entry,
            ) => {
              const manifest =
                await loadJson<
                  UpstreamFurnitureManifest
                >(
                  pixelAssetUrl(
                    entry.manifest,
                  ),
                );

              const flattened =
                flattenFurnitureManifest(
                  manifest,
                  entry.folder,
                );

              const assets:
                LoadedFurnitureAsset[] =
                  [];

              for (
                const asset
                of flattened
              ) {
                try {
                  const image =
                    await loadImage(
                      pixelAssetUrl(
                        `furniture/${entry.folder}/${asset.file}`,
                      ),
                    );

                  assets.push({
                    ...asset,
                    image,
                  });
                } catch (error) {
                  this.warnings.push(
                    `${manifest.id}/${asset.file}: ${
                      error instanceof Error
                        ? error.message
                        : "image load failed"
                    }`,
                  );
                }
              }

              if (
                assets.length >
                0
              ) {
                this.furniture.set(
                  manifest.id,
                  assets,
                );
              } else {
                throw new Error(
                  `${manifest.id} has no usable sprites.`,
                );
              }

              return manifest.id;
            },
          ),
        );

      furnitureResults.forEach(
        (
          result,
          indexPosition,
        ) => {
          if (
            result.status ===
            "rejected"
          ) {
            const source =
              index.furniture[
                indexPosition
              ];

            this.warnings.push(
              `Furniture ${source?.folder ?? indexPosition}: ${
                result.reason instanceof Error
                  ? result.reason.message
                  : String(
                      result.reason,
                    )
              }`,
            );
          }
        },
      );

      const characterCount =
        this.characters.filter(
          Boolean,
        ).length;

      const floorCount =
        this.floors.filter(
          Boolean,
        ).length;

      if (
        characterCount ===
          0 ||
        floorCount ===
          0
      ) {
        throw new Error(
          "The asset index loaded, but no usable character/floor sprites could be decoded.",
        );
      }

      this.ready =
        true;

      this.error =
        null;
    } catch (error) {
      this.ready =
        false;

      this.error =
        error instanceof Error
          ? error.message
          : "Pixel Agents assets failed to load.";
    }
  }

  getDiagnostics():
    PixelAssetDiagnostics {
    const index =
      this.index;

    return {
      charactersLoaded:
        this.characters.filter(
          Boolean,
        ).length,
      charactersExpected:
        index?.characters.length ??
        0,
      floorsLoaded:
        this.floors.filter(
          Boolean,
        ).length,
      floorsExpected:
        index?.floors.length ??
        0,
      wallsLoaded:
        this.walls.filter(
          Boolean,
        ).length,
      wallsExpected:
        index?.walls.length ??
        0,
      carpetsLoaded:
        this.carpets.filter(
          Boolean,
        ).length,
      carpetsExpected:
        index?.carpets.length ??
        0,
      petsLoaded:
        this.pets.size,
      petsExpected:
        index?.pets.length ??
        0,
      furnitureGroupsLoaded:
        this.furniture.size,
      furnitureGroupsExpected:
        index?.furniture.length ??
        0,
      warnings:
        [...this.warnings],
    };
  }

  private resolveFurniture(
    groupId: string,
    options:
      ResolveFurnitureOptions,
  ): {
    asset:
      LoadedFurnitureAsset;
    mirrorX:
      boolean;
  } | null {
    const available =
      this.furniture.get(
        groupId,
      );

    if (
      !available ||
      available.length ===
        0
    ) {
      return null;
    }

    let candidates =
      [...available];

    if (
      options.orientation
    ) {
      const exact =
        candidates.filter(
          (item) =>
            item.orientation ===
            options.orientation,
        );

      if (
        exact.length >
        0
      ) {
        candidates =
          exact;
      } else if (
        options.orientation ===
          "left" ||
        options.orientation ===
          "right"
      ) {
        const side =
          candidates.filter(
            (item) =>
              item.orientation ===
              "side",
          );

        if (
          side.length >
          0
        ) {
          candidates =
            side;
        }
      }
    }

    if (
      options.state
    ) {
      const exactState =
        candidates.filter(
          (item) =>
            item.state ===
            options.state,
        );

      if (
        exactState.length >
        0
      ) {
        candidates =
          exactState;
      }
    } else {
      const neutral =
        candidates.filter(
          (item) =>
            item.state ===
            undefined,
        );

      if (
        neutral.length >
        0
      ) {
        candidates =
          neutral;
      }
    }

    const animated =
      candidates
        .filter(
          (item) =>
            typeof item.frame ===
            "number",
        )
        .sort(
          (a, b) =>
            (
              a.frame ??
              0
            ) -
            (
              b.frame ??
              0
            ),
        );

    const selected =
      animated.length >
      0
        ? animated[
            positiveModulo(
              options.animationFrame ??
                0,
              animated.length,
            )
          ]
        : (
            candidates[0] ??
            available[0]
          );

    return {
      asset:
        selected,
      mirrorX:
        Boolean(
          options.mirrorX,
        ) ||
        (
          options.orientation ===
            "right" &&
          selected.orientation ===
            "side" &&
          selected.mirrorSide
        ),
    };
  }

  drawCharacter(
    ctx:
      CanvasRenderingContext2D,
    spriteIndex:
      number,
    mode:
      CharacterMode,
    direction:
      OfficeDirection,
    frame:
      number,
    x:
      number,
    baselineY:
      number,
    scale =
      1,
  ): boolean {
    if (
      this.characters.length ===
      0
    ) {
      return false;
    }

    const image =
      this.characters[
        positiveModulo(
          spriteIndex,
          this.characters.length,
        )
      ];

    if (!image) {
      return false;
    }

    let row =
      UPSTREAM_CHARACTER
        .rows.down;

    let mirror =
      false;

    if (
      direction ===
      "up"
    ) {
      row =
        UPSTREAM_CHARACTER
          .rows.up;
    } else if (
      direction ===
      "left"
    ) {
      row =
        UPSTREAM_CHARACTER
          .rows.right;

      mirror =
        true;
    } else if (
      direction ===
      "right"
    ) {
      row =
        UPSTREAM_CHARACTER
          .rows.right;
    }

    let frameIndex =
      UPSTREAM_CHARACTER
        .idle;

    if (
      mode ===
      "walk"
    ) {
      frameIndex =
        UPSTREAM_CHARACTER
          .walk[
            positiveModulo(
              frame,
              UPSTREAM_CHARACTER
                .walk.length,
            )
          ];
    } else if (
      mode ===
      "type"
    ) {
      frameIndex =
        UPSTREAM_CHARACTER
          .type[
            positiveModulo(
              frame,
              UPSTREAM_CHARACTER
                .type.length,
            )
          ];
    } else if (
      mode ===
      "read"
    ) {
      frameIndex =
        UPSTREAM_CHARACTER
          .read[
            positiveModulo(
              frame,
              UPSTREAM_CHARACTER
                .read.length,
            )
          ];
    }

    const width =
      UPSTREAM_CHARACTER
        .frameWidth;

    const height =
      UPSTREAM_CHARACTER
        .frameHeight;

    const drawWidth =
      width *
      scale;

    const drawHeight =
      height *
      scale;

    ctx.imageSmoothingEnabled =
      false;

    ctx.save();

    if (mirror) {
      ctx.translate(
        Math.round(
          x,
        ),
        0,
      );

      ctx.scale(
        -1,
        1,
      );

      ctx.drawImage(
        image,
        frameIndex *
          width,
        row *
          height,
        width,
        height,
        Math.round(
          -drawWidth /
            2,
        ),
        Math.round(
          baselineY -
            drawHeight,
        ),
        drawWidth,
        drawHeight,
      );
    } else {
      ctx.drawImage(
        image,
        frameIndex *
          width,
        row *
          height,
        width,
        height,
        Math.round(
          x -
            drawWidth /
              2,
        ),
        Math.round(
          baselineY -
            drawHeight,
        ),
        drawWidth,
        drawHeight,
      );
    }

    ctx.restore();

    return true;
  }

  drawFurniture(
    ctx:
      CanvasRenderingContext2D,
    placement:
      FurniturePlacement,
    active:
      boolean,
    animationFrame:
      number,
  ): {
    drawn:
      boolean;
    depthY:
      number;
  } {
    const resolved =
      this.resolveFurniture(
        placement.assetGroup,
        {
          orientation:
            placement.orientation,
          state:
            active
              ? "on"
              : placement.state,
          mirrorX:
            placement.mirrorX,
          animationFrame,
        },
      );

    const footprintBottom =
      (
        placement.row +
        placement.footprintH
      ) *
      16;

    if (!resolved) {
      return {
        drawn:
          false,
        depthY:
          footprintBottom,
      };
    }

    const {
      asset,
      mirrorX,
    } =
      resolved;

    const x =
      placement.col *
        16 +
      (
        placement.offsetX ??
        0
      );

    const y =
      footprintBottom -
      asset.height +
      (
        placement.offsetY ??
        0
      );

    ctx.imageSmoothingEnabled =
      false;

    ctx.save();

    if (mirrorX) {
      ctx.translate(
        x +
          asset.width,
        0,
      );

      ctx.scale(
        -1,
        1,
      );

      ctx.drawImage(
        asset.image,
        0,
        0,
        asset.width,
        asset.height,
        0,
        Math.round(
          y,
        ),
        asset.width,
        asset.height,
      );
    } else {
      ctx.drawImage(
        asset.image,
        Math.round(
          x,
        ),
        Math.round(
          y,
        ),
        asset.width,
        asset.height,
      );
    }

    ctx.restore();

    return {
      drawn:
        true,
      depthY:
        footprintBottom -
        asset.backgroundTiles *
          16,
    };
  }

  drawFloorTile(
    ctx:
      CanvasRenderingContext2D,
    patternIndex:
      number,
    tint:
      string,
    x:
      number,
    y:
      number,
  ): boolean {
    if (
      this.floors.length ===
      0
    ) {
      return false;
    }

    const source =
      this.floors[
        positiveModulo(
          patternIndex,
          this.floors.length,
        )
      ];

    if (!source) {
      return false;
    }

    const cacheKey =
      `${patternIndex}:${tint}`;

    let tinted =
      this.floorTintCache.get(
        cacheKey,
      );

    if (!tinted) {
      tinted =
        document.createElement(
          "canvas",
        );

      tinted.width =
        16;

      tinted.height =
        16;

      const tintCtx =
        tinted.getContext(
          "2d",
        );

      if (!tintCtx) {
        return false;
      }

      tintCtx.imageSmoothingEnabled =
        false;

      tintCtx.drawImage(
        source,
        0,
        0,
        16,
        16,
      );

      const image =
        tintCtx.getImageData(
          0,
          0,
          16,
          16,
        );

      const [
        baseR,
        baseG,
        baseB,
      ] =
        parseHex(
          tint,
        );

      for (
        let offset = 0;
        offset <
          image.data.length;
        offset +=
          4
      ) {
        if (
          image.data[
            offset +
              3
          ] ===
          0
        ) {
          continue;
        }

        const luminance =
          (
            image.data[
              offset
            ] +
            image.data[
              offset +
                1
            ] +
            image.data[
              offset +
                2
            ]
          ) /
          (
            255 *
            3
          );

        const amount =
          0.52 +
          luminance *
            0.72;

        image.data[
          offset
        ] =
          Math.min(
            255,
            Math.round(
              baseR *
                amount,
            ),
          );

        image.data[
          offset +
            1
        ] =
          Math.min(
            255,
            Math.round(
              baseG *
                amount,
            ),
          );

        image.data[
          offset +
            2
        ] =
          Math.min(
            255,
            Math.round(
              baseB *
                amount,
            ),
          );
      }

      tintCtx.putImageData(
        image,
        0,
        0,
      );

      this.floorTintCache.set(
        cacheKey,
        tinted,
      );
    }

    ctx.imageSmoothingEnabled =
      false;

    ctx.drawImage(
      tinted,
      Math.round(
        x,
      ),
      Math.round(
        y,
      ),
      16,
      16,
    );

    return true;
  }

  drawWallTile(
    ctx:
      CanvasRenderingContext2D,
    wallSet:
      number,
    bitmask:
      number,
    x:
      number,
    tileBottomY:
      number,
  ): boolean {
    if (
      this.walls.length ===
      0
    ) {
      return false;
    }

    const image =
      this.walls[
        positiveModulo(
          wallSet,
          this.walls.length,
        )
      ];

    if (!image) {
      return false;
    }

    const mask =
      Math.max(
        0,
        Math.min(
          UPSTREAM_WALL
            .masks -
            1,
          bitmask,
        ),
      );

    const sx =
      (
        mask %
        UPSTREAM_WALL
          .columns
      ) *
      UPSTREAM_WALL
        .pieceWidth;

    const sy =
      Math.floor(
        mask /
          UPSTREAM_WALL
            .columns,
      ) *
      UPSTREAM_WALL
        .pieceHeight;

    ctx.imageSmoothingEnabled =
      false;

    ctx.drawImage(
      image,
      sx,
      sy,
      UPSTREAM_WALL
        .pieceWidth,
      UPSTREAM_WALL
        .pieceHeight,
      Math.round(
        x,
      ),
      Math.round(
        tileBottomY -
          UPSTREAM_WALL
            .pieceHeight,
      ),
      UPSTREAM_WALL
        .pieceWidth,
      UPSTREAM_WALL
        .pieceHeight,
    );

    return true;
  }

  drawCarpetTile(
    ctx:
      CanvasRenderingContext2D,
    carpetIndex:
      number,
    marchingCase:
      number,
    x:
      number,
    y:
      number,
  ): boolean {
    if (
      this.carpets.length ===
      0
    ) {
      return false;
    }

    const image =
      this.carpets[
        positiveModulo(
          carpetIndex,
          this.carpets.length,
        )
      ];

    if (!image) {
      return false;
    }

    const value =
      Math.max(
        0,
        Math.min(
          UPSTREAM_CARPET
            .cases -
            1,
          marchingCase,
        ),
      );

    const sx =
      (
        value %
        UPSTREAM_CARPET
          .columns
      ) *
      UPSTREAM_CARPET
        .pieceWidth;

    const sy =
      Math.floor(
        value /
          UPSTREAM_CARPET
            .columns,
      ) *
      UPSTREAM_CARPET
        .pieceHeight;

    ctx.imageSmoothingEnabled =
      false;

    ctx.drawImage(
      image,
      sx,
      sy,
      UPSTREAM_CARPET
        .pieceWidth,
      UPSTREAM_CARPET
        .pieceHeight,
      Math.round(
        x,
      ),
      Math.round(
        y,
      ),
      16,
      16,
    );

    return true;
  }

  drawPet(
    ctx:
      CanvasRenderingContext2D,
    assetId:
      string,
    mode:
      PetMode,
    direction:
      OfficeDirection,
    frame:
      number,
    x:
      number,
    baselineY:
      number,
  ): boolean {
    const preferred =
      this.pets.get(
        assetId,
      );

    const fallback =
      this.pets.values()
        .next()
        .value as
        HTMLImageElement |
        undefined;

    const image =
      preferred ??
      fallback;

    if (!image) {
      return false;
    }

    const frameIndex =
      positiveModulo(
        frame,
        3,
      );

    let sx =
      0;

    let sy =
      0;

    let width =
      UPSTREAM_PET
        .smallFrameWidth;

    let mirror =
      false;

    if (
      mode ===
        "walk" &&
      (
        direction ===
          "left" ||
        direction ===
          "right"
      )
    ) {
      width =
        UPSTREAM_PET
          .largeFrameWidth;

      sy =
        UPSTREAM_PET
          .frameHeight *
        2;

      sx =
        frameIndex *
        width;

      mirror =
        direction ===
        "left";
    } else if (
      mode ===
      "walk"
    ) {
      sy =
        direction ===
        "up"
          ? UPSTREAM_PET
              .frameHeight
          : 0;

      sx =
        frameIndex *
        UPSTREAM_PET
          .smallFrameWidth;
    } else {
      const faceUp =
        direction ===
        "up";

      sy =
        faceUp
          ? UPSTREAM_PET
              .frameHeight
          : 0;

      sx =
        (
          UPSTREAM_PET
            .verticalWalkFrames +
          frameIndex
        ) *
        UPSTREAM_PET
          .smallFrameWidth;
    }

    const height =
      UPSTREAM_PET
        .frameHeight;

    ctx.imageSmoothingEnabled =
      false;

    ctx.save();

    if (mirror) {
      ctx.translate(
        Math.round(
          x,
        ),
        0,
      );

      ctx.scale(
        -1,
        1,
      );

      ctx.drawImage(
        image,
        sx,
        sy,
        width,
        height,
        Math.round(
          -width /
            2,
        ),
        Math.round(
          baselineY -
            height,
        ),
        width,
        height,
      );
    } else {
      ctx.drawImage(
        image,
        sx,
        sy,
        width,
        height,
        Math.round(
          x -
            width /
              2,
        ),
        Math.round(
          baselineY -
            height,
        ),
        width,
        height,
      );
    }

    ctx.restore();

    return true;
  }

  hasFurniture(
    groupId:
      string,
  ): boolean {
    return Boolean(
      this.furniture
        .get(
          groupId,
        )
        ?.length,
    );
  }

  getIndex():
    PixelAgentsAssetIndex |
    null {
    return this.index;
  }
}
