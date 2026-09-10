/*
 * Jace board visualizer — adapted from Jared Rhodenizer's ai-visualizer
 * Circuit Board face (faces/board/index.html).
 *
 * Original work Copyright (C) 2026 Jared Rhodenizer
 * Adaptation Copyright (C) 2026 Jace contributors
 *
 * This file is a derivative work licensed under the GNU Affero General
 * Public License, version 3 or (at your option) any later version.
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * Upstream: https://github.com/jaredrhod/ai-visualizer
 */

export type BoardVisualState = "idle" | "listening" | "thinking" | "speaking";

export interface JaceBoardSnapshot {
  state: BoardVisualState;
  displayState: string;
  level: number;
  alert: boolean;
  connected: boolean;
  label: string;
}

export interface JaceBoardEngineOptions {
  canvas: HTMLCanvasElement;
  getSnapshot: () => JaceBoardSnapshot;
  seed?: number;
}

type Point = [number, number];

type Trace = {
  pts: Point[];
  cum: number[];
  len: number;
  start: [number, number];
  end: [number, number];
  chip?: boolean;
  amber?: boolean;
  endComp?: number;
  revg?: TraceGeometry;
  bb?: [number, number, number, number];
};

type TraceGeometry = {
  pts: Point[];
  cum: number[];
  len: number;
  amber?: boolean;
  chip?: boolean;
};

type Component = {
  type: "ic" | "res" | "cap";
  gx: number;
  gy: number;
  wc: number;
  hc: number;
  x: number;
  y: number;
  w: number;
  h: number;
  glow: number;
  amber: boolean;
  out: number[];
  flashCol?: string | null;
};

type Pulse = {
  t: Trace;
  geo: TraceGeometry | null;
  inward: boolean;
  d: number;
  sp: number;
  col: string | null;
};

type Chip = {
  x: number;
  y: number;
  w: number;
  h: number;
  glowIn: number;
  glyphs?: Array<{ c: string; x: number }>;
  glyphFs?: number;
  glyphLbl?: string;
};

type Deco = {
  zones: Array<{ x: number; y: number; w: number; h: number }>;
  labels: Array<{ t: string; x: number; y: number; rot: boolean }>;
  crosses: Array<{ x: number; y: number }>;
};

type Ring = { t: number; col: string; inw?: boolean };

type Camera = { x: number; y: number; z: number };
type CineSegment = { d: number; f: Camera; t: Camera; out?: boolean; chipShot?: boolean };
type Cine = { t: number; segs: CineSegment[] };

const GREEN = "#3ddc84";
const GREEN_HOT = "#a6ffd0";
const AMBER = "#e7c368";
const AMBER_HOT = "#ffe9ae";
const RED = "#ff4d5e";
const LISTEN_COOL = "#35e0ff";
const SPEAK_COLS = ["#35e0ff", "#9d7bff", "#ff4d9d", "#5fa8ff", "#46e28a", "#e7c368"];
const LISTEN_COLS = ["#35e0ff", "#5fa8ff"];
const SCRAM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&@<>/*+=?";
const DIRS: Point[] = [[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1],[0,-1],[1,-1]];

function mulberry32(a: number) {
  return function rnd() {
    a |= 0;
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hex2rgb(h: string): [number, number, number] {
  const n = Number.parseInt(h.slice(1), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

function rgba(h: string, a: number) {
  const [r, g, b] = hex2rgb(h);
  return `rgba(${r},${g},${b},${a})`;
}

function clamp01(n: number) {
  return Math.max(0, Math.min(1, n));
}

export class JaceBoardEngine {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly getSnapshot: () => JaceBoardSnapshot;
  private readonly seed: number;
  private rnd: () => number;

  private W = 0;
  private H = 0;
  private DPR = 1;
  private cell = 24;
  private cols = 0;
  private rows = 0;
  private occ = new Set<string>();

  private traces: Trace[] = [];
  private comps: Component[] = [];
  private pulses: Pulse[] = [];
  private chip: Chip = { x: 0, y: 0, w: 0, h: 0, glowIn: 0 };
  private deco: Deco = { zones: [], labels: [], crosses: [] };

  private bgLayer: HTMLCanvasElement | null = null;
  private glowSprites = new Map<string, HTMLCanvasElement>();
  private grainTile: HTMLCanvasElement | null = null;
  private grainPat: CanvasPattern | null = null;

  private now = 0;
  private Ecur = 0.25;
  private lvlS = 0;
  private talkS = 0;
  private listenS = 0;
  private thinkS = 0;
  private speakingNow = false;
  private rings: Ring[] = [];
  private lastRing = 0;

  private camera: Camera = { x: 0, y: 0, z: 1 };
  private cine: Cine | null = null;
  private cineFade = 0;
  private camZ = 1;

  private raf = 0;
  private lastFrame = 0;
  private resizeObserver: ResizeObserver | null = null;

  constructor(options: JaceBoardEngineOptions) {
    this.canvas = options.canvas;
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("Jace visualizer could not create a 2D canvas context.");
    this.ctx = ctx;
    this.getSnapshot = options.getSnapshot;
    this.seed = options.seed ?? 7;
    this.rnd = mulberry32(this.seed);
  }

  start() {
    this.resizeObserver = new ResizeObserver(() => this.resize());
    if (this.canvas.parentElement) this.resizeObserver.observe(this.canvas.parentElement);
    this.resize();
    this.lastFrame = performance.now();
    this.raf = requestAnimationFrame(this.loop);
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
  }

  toggleCinematic() {
    if (this.cine) this.endCine();
    else this.startCine();
  }

  private loop = (ts: number) => {
    const dt = Math.min(50, Math.max(0, ts - this.lastFrame));
    this.lastFrame = ts;
    this.frame(dt);
    this.raf = requestAnimationFrame(this.loop);
  };

  private R(a: number, b: number) {
    return a + this.rnd() * (b - a);
  }

  private key(x: number, y: number) {
    return `${x}_${y}`;
  }

  private makeGlow(col: string, size: number) {
    const c = document.createElement("canvas");
    c.width = c.height = size;
    const g = c.getContext("2d")!;
    const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    const rgb = col.startsWith("#") ? hex2rgb(col) : null;
    const base = rgb ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` : col;
    const soft = rgb ? `rgba(${rgb[0]},${rgb[1]},${rgb[2]},.55)` : col;
    grd.addColorStop(0, base);
    grd.addColorStop(0.25, soft);
    grd.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grd;
    g.fillRect(0, 0, size, size);
    return c;
  }

  private route(sx: number, sy: number, dir: number, maxLen?: number): Trace | null {
    let x = sx;
    let y = sy;
    let d = dir;
    const pts: Array<[number, number]> = [[x, y]];
    let run = 2 + ((this.rnd() * 5) | 0);
    let blocked = 0;
    const total = maxLen ?? (14 + ((this.rnd() * 30) | 0));

    for (let s = 0; s < total; s++) {
      const [dx, dy] = DIRS[d];
      const nx = x + dx;
      const ny = y + dy;
      if (nx < 1 || ny < 1 || nx >= this.cols - 1 || ny >= this.rows - 1 || this.occ.has(this.key(nx, ny))) {
        d = (d + (this.rnd() < 0.5 ? 1 : 7)) % 8;
        if (++blocked > 2) break;
        continue;
      }
      blocked = 0;
      x = nx;
      y = ny;
      this.occ.add(this.key(x, y));
      pts.push([x, y]);
      if (--run <= 0) {
        if (this.rnd() < 0.7) d = (d + (this.rnd() < 0.5 ? 1 : 7)) % 8;
        run = 2 + ((this.rnd() * 6) | 0);
      }
    }

    if (pts.length < 5) return null;
    const keep: Array<[number, number]> = [pts[0]];
    for (let i = 1; i < pts.length - 1; i++) {
      const a = keep[keep.length - 1];
      const b = pts[i];
      const c = pts[i + 1];
      if ((b[0] - a[0]) * (c[1] - b[1]) !== (b[1] - a[1]) * (c[0] - b[0])) keep.push(b);
    }
    keep.push(pts[pts.length - 1]);

    const px: Point[] = keep.map((p) => [p[0] * this.cell + this.cell / 2, p[1] * this.cell + this.cell / 2]);
    const cum = [0];
    for (let i = 1; i < px.length; i++) {
      cum.push(cum[i - 1] + Math.hypot(px[i][0] - px[i - 1][0], px[i][1] - px[i - 1][1]));
    }

    return {
      pts: px,
      cum,
      len: cum[cum.length - 1],
      end: pts[pts.length - 1],
      start: pts[0],
    };
  }

  private resize() {
    if (this.cine) this.endCine();
    const rect = this.canvas.parentElement?.getBoundingClientRect() ?? this.canvas.getBoundingClientRect();
    const cssW = Math.max(1, Math.floor(rect.width));
    const cssH = Math.max(1, Math.floor(rect.height));
    this.DPR = Math.min(window.devicePixelRatio || 1, 1.25);
    this.W = this.canvas.width = Math.max(1, Math.floor(cssW * this.DPR));
    this.H = this.canvas.height = Math.max(1, Math.floor(cssH * this.DPR));
    this.canvas.style.width = `${cssW}px`;
    this.canvas.style.height = `${cssH}px`;
    this.rnd = mulberry32(this.seed);
    this.buildBoard();
    this.camera = { x: this.W / 2, y: this.H / 2, z: 1 };
  }

  private buildBoard() {
    this.cell = Math.max(16, Math.round(Math.min(this.W, this.H) / 56));
    this.cols = Math.ceil(this.W / this.cell);
    this.rows = Math.ceil(this.H / this.cell);
    this.occ = new Set();
    this.traces = [];
    this.comps = [];
    this.pulses = [];
    this.rings = [];

    const chW = Math.round(Math.min(this.W * 0.235, 620 * this.DPR));
    const chH = Math.round(chW * 0.30);
    this.chip = { x: this.W * 0.5 - chW / 2, y: this.H * 0.5 - chH / 2, w: chW, h: chH, glowIn: 0 };

    const cx0 = Math.floor(this.chip.x / this.cell) - 1;
    const cy0 = Math.floor(this.chip.y / this.cell) - 1;
    const cx1 = Math.ceil((this.chip.x + chW) / this.cell) + 1;
    const cy1 = Math.ceil((this.chip.y + chH) / this.cell) + 1;
    for (let gx = cx0; gx <= cx1; gx++) {
      for (let gy = cy0; gy <= cy1; gy++) this.occ.add(this.key(gx, gy));
    }

    const place = (wc: number, hc: number) => {
      for (let tr = 0; tr < 60; tr++) {
        const gx = 1 + ((this.rnd() * Math.max(1, this.cols - wc - 2)) | 0);
        const gy = 1 + ((this.rnd() * Math.max(1, this.rows - hc - 2)) | 0);
        let free = true;
        for (let a = gx - 1; a <= gx + wc && free; a++) {
          for (let b = gy - 1; b <= gy + hc && free; b++) {
            if (this.occ.has(this.key(a, b))) free = false;
          }
        }
        if (!free) continue;
        for (let a = gx; a < gx + wc; a++) {
          for (let b = gy; b < gy + hc; b++) this.occ.add(this.key(a, b));
        }
        return { gx, gy };
      }
      return null;
    };

    for (let i = 0; i < 34; i++) {
      const roll = this.rnd();
      const type: Component["type"] = roll < 0.42 ? "ic" : roll < 0.78 ? "res" : "cap";
      const wc = type === "ic" ? 4 + ((this.rnd() * 3) | 0) : type === "res" ? 1 : 2;
      const hc = type === "ic" ? 3 + ((this.rnd() * 2) | 0) : type === "res" ? 3 + ((this.rnd() * 3) | 0) : 2;
      const spot = place(wc, hc);
      if (!spot) continue;
      this.comps.push({
        type,
        gx: spot.gx,
        gy: spot.gy,
        wc,
        hc,
        x: spot.gx * this.cell,
        y: spot.gy * this.cell,
        w: wc * this.cell,
        h: hc * this.cell,
        glow: 0,
        amber: this.rnd() < 0.18,
        out: [],
      });
    }

    const pinsPerSide = Math.max(6, Math.round(chH / this.cell) + 2);
    const addPinTraces = (side: number) => {
      const n = side < 2 ? pinsPerSide : 6;
      for (let i = 0; i < n; i++) {
        let gx = 0;
        let gy = 0;
        let dir = 0;
        if (side === 0) { gx = cx0; gy = cy0 + 2 + ((this.rnd() * Math.max(1, cy1 - cy0 - 3)) | 0); dir = 4; }
        else if (side === 1) { gx = cx1; gy = cy0 + 2 + ((this.rnd() * Math.max(1, cy1 - cy0 - 3)) | 0); dir = 0; }
        else if (side === 2) { gx = cx0 + 2 + ((this.rnd() * Math.max(1, cx1 - cx0 - 3)) | 0); gy = cy0; dir = 6; }
        else { gx = cx0 + 2 + ((this.rnd() * Math.max(1, cx1 - cx0 - 3)) | 0); gy = cy1; dir = 2; }
        const t = this.route(gx, gy, dir);
        if (t) {
          t.chip = true;
          t.amber = this.rnd() < 0.15;
          this.traces.push(t);
        }
      }
    };
    addPinTraces(0); addPinTraces(1); addPinTraces(2); addPinTraces(3);

    for (let i = 0; i < 130; i++) {
      const gx = 1 + ((this.rnd() * Math.max(1, this.cols - 2)) | 0);
      const gy = 1 + ((this.rnd() * Math.max(1, this.rows - 2)) | 0);
      if (this.occ.has(this.key(gx, gy))) continue;
      this.occ.add(this.key(gx, gy));
      const t = this.route(gx, gy, [0, 2, 4, 6][(this.rnd() * 4) | 0]);
      if (t) {
        t.chip = false;
        t.amber = this.rnd() < 0.18;
        this.traces.push(t);
      }
    }

    this.traces.forEach((t, ti) => {
      let best = -1;
      let bd = 1e9;
      this.comps.forEach((c, ci) => {
        const dx = Math.max(c.gx - t.end[0], 0, t.end[0] - (c.gx + c.wc - 1));
        const dy = Math.max(c.gy - t.end[1], 0, t.end[1] - (c.gy + c.hc - 1));
        const d = dx * dx + dy * dy;
        if (d < bd) { bd = d; best = ci; }
      });
      t.endComp = bd <= 9 ? best : -1;
      this.comps.forEach((c) => {
        const dx = Math.max(c.gx - t.start[0], 0, t.start[0] - (c.gx + c.wc - 1));
        const dy = Math.max(c.gy - t.start[1], 0, t.start[1] - (c.gy + c.hc - 1));
        if (dx * dx + dy * dy <= 9) c.out.push(ti);
      });
    });

    this.deco = { zones: [], labels: [], crosses: [] };
    const rz = mulberry32(this.seed + 55);
    for (let i = 0; i < 6; i++) {
      const zw = this.W * (0.12 + rz() * 0.2);
      const zh = this.H * (0.12 + rz() * 0.22);
      this.deco.zones.push({ x: rz() * (this.W - zw), y: rz() * (this.H - zh), w: zw, h: zh });
    }
    const rl = mulberry32(this.seed + 77);
    for (let i = 0; i < 46; i++) {
      const lt = ["R", "C", "U", "Q", "L", "JP"][(rl() * 6) | 0] + (1 + ((rl() * 98) | 0));
      this.deco.labels.push({ t: lt, x: rl() * this.W, y: rl() * this.H, rot: rl() < 0.4 });
    }
    for (let i = 0; i < 14; i++) this.deco.crosses.push({ x: rl() * this.W, y: rl() * this.H });

    this.traces.forEach((t) => {
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      t.pts.forEach((p) => { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); });
      t.bb = [x0 - 8, y0 - 8, x1 + 8, y1 + 8];
    });

    this.glowSprites.clear();
    [GREEN, AMBER, RED, ...SPEAK_COLS].forEach((hx) => this.glowSprites.set(hx, this.makeGlow(hx, 64)));
    this.glowSprites.set("white", this.makeGlow("rgb(220,255,235)", 64));
    this.renderBG();
  }

  private renderBG() {
    this.bgLayer = document.createElement("canvas");
    this.bgLayer.width = this.W;
    this.bgLayer.height = this.H;
    const g = this.bgLayer.getContext("2d")!;
    this.drawWorld(g, [0, 0, this.W, this.H], 1);
  }

  private drawWorld(g: CanvasRenderingContext2D, view: [number, number, number, number], sf: number) {
    const [vx0, vy0, vx1, vy1] = view;
    const hit = (x0: number, y0: number, x1: number, y1: number) => x1 >= vx0 && x0 <= vx1 && y1 >= vy0 && y0 <= vy1;

    const grd = g.createRadialGradient(this.W / 2, this.H / 2, 0, this.W / 2, this.H / 2, Math.max(this.W, this.H) * 0.72);
    grd.addColorStop(0, "#07160e");
    grd.addColorStop(0.55, "#04100a");
    grd.addColorStop(1, "#020705");
    g.fillStyle = grd;
    g.fillRect(vx0, vy0, vx1 - vx0, vy1 - vy0);

    g.save();
    g.globalCompositeOperation = "soft-light";
    const weave = Math.max(5, Math.round(this.cell * 0.3));
    g.strokeStyle = "rgba(190,255,220,.10)";
    g.lineWidth = 1;
    g.beginPath();
    for (let x = Math.floor(vx0 / weave) * weave; x <= vx1; x += weave) { g.moveTo(x, vy0); g.lineTo(x, vy1); }
    for (let y = Math.floor(vy0 / weave) * weave; y <= vy1; y += weave) { g.moveTo(vx0, y); g.lineTo(vx1, y); }
    g.stroke();
    g.restore();

    g.fillStyle = "rgba(61,220,132,.045)";
    const d0 = this.cell * 2;
    const ds = this.cell * 4;
    for (let xi = Math.max(0, Math.ceil((vx0 - d0) / ds)); d0 + xi * ds < Math.min(this.W, vx1 + 2); xi++) {
      for (let yi = Math.max(0, Math.ceil((vy0 - d0) / ds)); d0 + yi * ds < Math.min(this.H, vy1 + 2); yi++) {
        g.fillRect(d0 + xi * ds - 1, d0 + yi * ds - 1, 2, 2);
      }
    }

    this.deco.zones.forEach((z) => {
      if (!hit(z.x, z.y, z.x + z.w, z.y + z.h)) return;
      g.fillStyle = "rgba(61,220,132,.03)";
      g.strokeStyle = "rgba(61,220,132,.06)";
      g.lineWidth = 1;
      g.beginPath(); g.roundRect(z.x, z.y, z.w, z.h, 12); g.fill(); g.stroke();
    });

    g.font = `${Math.round(this.cell * 0.5)}px "SF Mono", Menlo, Consolas, monospace`;
    this.deco.labels.forEach((label) => {
      if (!hit(label.x - 80, label.y - 80, label.x + 80, label.y + 80)) return;
      g.save(); g.translate(label.x, label.y); if (label.rot) g.rotate(-Math.PI / 2);
      g.fillStyle = "rgba(120,220,170,.10)";
      g.fillText(label.t, 0, 0); g.restore();
    });

    g.strokeStyle = "rgba(120,220,170,.08)";
    g.lineWidth = 1;
    this.deco.crosses.forEach((cross) => {
      const s = this.cell * 0.6;
      if (!hit(cross.x - s, cross.y - s, cross.x + s, cross.y + s)) return;
      g.beginPath(); g.moveTo(cross.x - s, cross.y); g.lineTo(cross.x + s, cross.y); g.moveTo(cross.x, cross.y - s); g.lineTo(cross.x, cross.y + s); g.stroke();
      g.beginPath(); g.arc(cross.x, cross.y, s * 0.45, 0, Math.PI * 2); g.stroke();
    });

    g.lineCap = "round";
    g.lineJoin = "round";
    const traceW = Math.max(1.4, this.cell * 0.09);
    this.traces.forEach((t) => {
      if (t.bb && !hit(...t.bb)) return;
      const path = () => {
        g.beginPath();
        g.moveTo(t.pts[0][0], t.pts[0][1]);
        for (let i = 1; i < t.pts.length; i++) g.lineTo(t.pts[i][0], t.pts[i][1]);
      };
      g.save(); g.translate(1.1, 1.4); path(); g.strokeStyle = "rgba(0,0,0,.30)"; g.lineWidth = traceW + 0.6; g.stroke(); g.restore();
      path(); g.strokeStyle = t.amber ? "rgba(231,195,104,.15)" : "rgba(61,220,132,.17)"; g.lineWidth = traceW; g.stroke();
      g.save(); g.translate(-0.7, -0.9); path(); g.strokeStyle = t.amber ? "rgba(255,236,180,.05)" : "rgba(190,255,220,.055)"; g.lineWidth = Math.max(1, traceW * 0.45); g.stroke(); g.restore();

      [t.pts[0], t.pts[t.pts.length - 1]].forEach((p) => {
        const vr = Math.max(2.6, this.cell * 0.14);
        g.beginPath(); g.arc(p[0] + 0.8, p[1] + 1, vr, 0, Math.PI * 2); g.strokeStyle = "rgba(0,0,0,.32)"; g.lineWidth = 1.6; g.stroke();
        g.beginPath(); g.arc(p[0], p[1], vr, 0, Math.PI * 2); g.strokeStyle = "rgba(120,220,170,.22)"; g.lineWidth = 1.4; g.stroke();
        g.beginPath(); g.arc(p[0], p[1], vr, Math.PI * 0.75, Math.PI * 1.45); g.strokeStyle = "rgba(210,255,230,.30)"; g.lineWidth = 1.1; g.stroke();
        g.fillStyle = "rgba(1,4,3,.95)"; g.beginPath(); g.arc(p[0], p[1], Math.max(1.2, this.cell * 0.06), 0, Math.PI * 2); g.fill();
      });
    });

    this.comps.forEach((c) => this.drawComponent(g, c, sf, hit));
  }

  private drawComponent(g: CanvasRenderingContext2D, c: Component, sf: number, hit: (x0: number, y0: number, x1: number, y1: number) => boolean) {
    const col = c.amber ? AMBER : GREEN;
    const hgt = c.type === "ic" ? 1 : c.type === "cap" ? 0.75 : 0.5;
    const shx = 4.5 * hgt + 1;
    const shy = 6.5 * hgt + 1.5;
    const shb = 9 * hgt + 4;
    if (!hit(c.x - 8, c.y - 8, c.x + c.w + shx + shb + 8, c.y + c.h + shy + shb + 8)) return;

    if (c.type === "ic") {
      const bx = c.x + this.cell * 0.3;
      const by = c.y + this.cell * 0.3;
      const bw = c.w - this.cell * 0.6;
      const bh = c.h - this.cell * 0.6;
      const np = Math.max(3, c.wc * 2 - 2);
      for (let i = 0; i < np; i++) {
        const px = c.x + this.cell * 0.5 + (c.w - this.cell) * (i / Math.max(1, np - 1));
        let pg = g.createLinearGradient(0, c.y, 0, c.y + this.cell * 0.3);
        pg.addColorStop(0, "rgba(200,235,215,.32)"); pg.addColorStop(1, "rgba(70,110,90,.20)");
        g.fillStyle = pg; g.fillRect(px - 1.5, c.y + this.cell * 0.02, 3, this.cell * 0.26);
        pg = g.createLinearGradient(0, c.y + c.h - this.cell * 0.28, 0, c.y + c.h);
        pg.addColorStop(0, "rgba(70,110,90,.20)"); pg.addColorStop(1, "rgba(150,200,175,.24)");
        g.fillStyle = pg; g.fillRect(px - 1.5, c.y + c.h - this.cell * 0.28, 3, this.cell * 0.26);
      }
      g.save(); g.shadowColor = "rgba(0,0,0,.55)"; g.shadowBlur = shb * sf; g.shadowOffsetX = shx * sf; g.shadowOffsetY = shy * sf;
      g.fillStyle = "#050c08"; g.beginPath(); g.roundRect(bx, by, bw, bh, 3); g.fill(); g.restore();
      const bg = g.createLinearGradient(bx, by, bx + bw, by + bh);
      bg.addColorStop(0, "rgba(14,26,19,.94)"); bg.addColorStop(0.45, "rgba(5,12,8,.94)"); bg.addColorStop(1, "rgba(2,6,4,.94)");
      g.fillStyle = bg; g.beginPath(); g.roundRect(bx, by, bw, bh, 3); g.fill();
      g.strokeStyle = "rgba(190,255,220,.18)"; g.lineWidth = 1.2; g.beginPath(); g.moveTo(bx + 2, by + bh - 2); g.lineTo(bx + 2, by + 2); g.lineTo(bx + bw - 2, by + 2); g.stroke();
      g.strokeStyle = rgba(col, 0.24); g.lineWidth = 1; g.beginPath(); g.roundRect(bx, by, bw, bh, 3); g.stroke();
      g.fillStyle = "rgba(120,220,170,.14)"; g.beginPath(); g.arc(c.x + this.cell * 0.62, c.y + this.cell * 0.62, this.cell * 0.09, 0, Math.PI * 2); g.fill();
      return;
    }

    if (c.type === "res") {
      for (let i = 0; i < c.hc; i++) {
        const rx = c.x + this.cell * 0.12;
        const ry = c.y + i * this.cell + this.cell * 0.22;
        const rw = c.w - this.cell * 0.24;
        const rh = this.cell * 0.56;
        g.save(); g.shadowColor = "rgba(0,0,0,.35)"; g.shadowBlur = 5 * sf; g.shadowOffsetX = 2 * sf; g.shadowOffsetY = 3 * sf;
        g.fillStyle = "#06100a"; g.beginPath(); g.roundRect(rx, ry, rw, rh, 2); g.fill(); g.restore();
        const rg = g.createLinearGradient(rx, ry, rx + rw, ry + rh);
        rg.addColorStop(0, "rgba(36,61,45,.95)"); rg.addColorStop(0.5, "rgba(8,17,11,.96)"); rg.addColorStop(1, "rgba(2,6,4,.97)");
        g.fillStyle = rg; g.beginPath(); g.roundRect(rx, ry, rw, rh, 2); g.fill();
        g.strokeStyle = rgba(col, 0.22); g.lineWidth = 1; g.beginPath(); g.roundRect(rx, ry, rw, rh, 2); g.stroke();
      }
      return;
    }

    const cx = c.x + c.w / 2;
    const cy = c.y + c.h / 2;
    const cr = c.w * 0.34;
    g.save(); g.shadowColor = "rgba(0,0,0,.5)"; g.shadowBlur = shb * sf; g.shadowOffsetX = shx * sf; g.shadowOffsetY = shy * sf;
    g.fillStyle = "#040a06"; g.beginPath(); g.arc(cx, cy, cr, 0, Math.PI * 2); g.fill(); g.restore();
    const dg = g.createRadialGradient(cx - cr * 0.4, cy - cr * 0.45, cr * 0.1, cx, cy, cr);
    dg.addColorStop(0, "rgba(58,96,73,.95)"); dg.addColorStop(0.45, "rgba(14,28,19,.95)"); dg.addColorStop(1, "rgba(2,6,4,.95)");
    g.fillStyle = dg; g.beginPath(); g.arc(cx, cy, cr, 0, Math.PI * 2); g.fill();
    g.strokeStyle = rgba(col, 0.26); g.lineWidth = 1.4; g.beginPath(); g.arc(cx, cy, cr, 0, Math.PI * 2); g.stroke();
    g.fillStyle = "rgba(220,255,235,.32)"; g.beginPath(); g.arc(cx - cr * 0.38, cy - cr * 0.42, Math.max(1, cr * 0.14), 0, Math.PI * 2); g.fill();
    g.strokeStyle = "rgba(190,255,220,.18)"; g.lineWidth = 1.2; g.beginPath(); g.moveTo(cx, cy - cr * 0.5); g.lineTo(cx, cy + cr * 0.5); g.stroke();
  }

  private drawChipBase(g: CanvasRenderingContext2D) {
    const { x, y, w, h } = this.chip;
    const npx = 12;
    for (let i = 0; i < npx; i++) {
      const px = x + w * 0.08 + w * 0.84 * (i / (npx - 1));
      let pg = g.createLinearGradient(0, y - this.cell * 0.34, 0, y);
      pg.addColorStop(0, "rgba(210,240,220,.40)"); pg.addColorStop(1, "rgba(90,130,108,.28)");
      g.fillStyle = pg; g.fillRect(px - 2, y - this.cell * 0.34, 4, this.cell * 0.30);
      pg = g.createLinearGradient(0, y + h, 0, y + h + this.cell * 0.34);
      pg.addColorStop(0, "rgba(90,130,108,.28)"); pg.addColorStop(1, "rgba(170,210,190,.34)");
      g.fillStyle = pg; g.fillRect(px - 2, y + h + this.cell * 0.04, 4, this.cell * 0.30);
    }
    const npy = 5;
    g.fillStyle = "rgba(185,220,200,.32)";
    for (let i = 0; i < npy; i++) {
      const py = y + h * 0.14 + h * 0.72 * (i / (npy - 1));
      g.fillRect(x - this.cell * 0.34, py - 2, this.cell * 0.30, 4);
      g.fillRect(x + w + this.cell * 0.04, py - 2, this.cell * 0.30, 4);
    }
    g.save(); g.shadowColor = "rgba(0,0,0,.65)"; g.shadowBlur = 30 * this.camZ; g.shadowOffsetX = 12 * this.camZ; g.shadowOffsetY = 16 * this.camZ;
    g.fillStyle = "#040a07"; g.beginPath(); g.roundRect(x, y, w, h, 6); g.fill(); g.restore();
    const tg = g.createLinearGradient(x, y, x + w, y + h);
    tg.addColorStop(0, "rgba(30,52,40,.5)"); tg.addColorStop(0.45, "rgba(6,13,9,0)"); tg.addColorStop(1, "rgba(0,0,0,.25)");
    g.fillStyle = tg; g.beginPath(); g.roundRect(x, y, w, h, 6); g.fill();
    g.strokeStyle = "rgba(150,235,185,.28)"; g.lineWidth = 1.6; g.beginPath(); g.moveTo(x + 3, y + h - 4); g.lineTo(x + 3, y + 3); g.lineTo(x + w - 4, y + 3); g.stroke();
    g.strokeStyle = "rgba(0,0,0,.6)"; g.lineWidth = 2.2; g.beginPath(); g.moveTo(x + w - 2, y + 4); g.lineTo(x + w - 2, y + h - 2); g.lineTo(x + 4, y + h - 2); g.stroke();
    g.strokeStyle = "#1e3a2b"; g.lineWidth = 2; g.beginPath(); g.roundRect(x, y, w, h, 6); g.stroke();
    g.strokeStyle = "rgba(61,220,132,.20)"; g.lineWidth = 1; g.beginPath(); g.roundRect(x + 5, y + 5, w - 10, h - 10, 4); g.stroke();
    g.fillStyle = "rgba(61,220,132,.4)"; g.beginPath(); g.arc(x + 14, y + 14, 4, 0, Math.PI * 2); g.fill();
  }

  private revGeo(t: Trace): TraceGeometry {
    if (!t.revg) {
      const pts = [...t.pts].reverse();
      const cum = [0];
      for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
      t.revg = { pts, cum, len: t.len, amber: t.amber, chip: t.chip };
    }
    return t.revg;
  }

  private spawnPulse(ti: number, inward: boolean) {
    const t = this.traces[ti];
    if (!t) return;
    const col = this.speakingNow
      ? SPEAK_COLS[(this.rnd() * SPEAK_COLS.length) | 0]
      : inward
        ? LISTEN_COLS[(this.rnd() * LISTEN_COLS.length) | 0]
        : null;
    this.pulses.push({
      t,
      geo: inward ? this.revGeo(t) : null,
      inward,
      d: 0,
      sp: this.R(0.14, 0.26) * Math.min(this.W, this.H) / 1000,
      col,
    });
  }

  private targetEnergy(snapshot: JaceBoardSnapshot) {
    if (snapshot.state === "thinking") return 1;
    if (snapshot.state === "speaking") return Math.min(0.97, 0.5 + 0.5 * Math.pow(snapshot.level, 0.7));
    if (snapshot.state === "listening") return 0.5;
    return 0.25;
  }

  private pointAt(t: TraceGeometry, d: number): Point | null {
    if (d < 0 || d > t.len) return null;
    let i = 1;
    while (i < t.cum.length && t.cum[i] < d) i++;
    if (i >= t.cum.length) return t.pts[t.pts.length - 1];
    const seg = t.cum[i] - t.cum[i - 1] || 1;
    const f = (d - t.cum[i - 1]) / seg;
    return [
      t.pts[i - 1][0] + (t.pts[i][0] - t.pts[i - 1][0]) * f,
      t.pts[i - 1][1] + (t.pts[i][1] - t.pts[i - 1][1]) * f,
    ];
  }

  private drawDynamicChip(dt: number, E: number, snapshot: JaceBoardSnapshot) {
    const ctx = this.ctx;
    const { x, y, w, h } = this.chip;
    const talk = snapshot.state === "speaking" ? this.lvlS : 0;
    this.chip.glowIn *= Math.exp(-dt / 420);
    const scale = 1 + 0.012 * Math.sin(this.now / 620) + 0.05 * talk + 0.018 * E + 0.02 * this.chip.glowIn;
    const ccx = x + w / 2;
    const ccy = y + h / 2;

    ctx.save();
    ctx.translate(ccx, ccy); ctx.scale(scale, scale); ctx.translate(-ccx, -ccy);
    const breathe = 0.5 + 0.5 * Math.sin(this.now / 1100);
    const cool = this.glowSprites.get(LISTEN_COOL)!;
    const amber = this.glowSprites.get(AMBER)!;
    const alertGlow = this.glowSprites.get(RED)!;

    const cg = Math.min(1, 0.22 + 0.55 * E + 0.14 * breathe + 0.3 * talk + 0.3 * this.chip.glowIn);
    const s = w * (1.7 + 0.6 * E + 0.45 * talk + 0.2 * this.chip.glowIn);
    if (snapshot.alert) {
      ctx.globalAlpha = 0.82;
      ctx.drawImage(alertGlow, ccx - s / 2, ccy - (s * 0.62) / 2, s, s * 0.62);
    } else {
      ctx.globalAlpha = cg * (1 - 0.85 * this.listenS);
      ctx.drawImage(amber, ccx - s / 2, ccy - (s * 0.62) / 2, s, s * 0.62);
      if (this.listenS > 0.02) {
        ctx.globalAlpha = cg * 0.9 * this.listenS;
        ctx.drawImage(cool, ccx - s / 2, ccy - (s * 0.62) / 2, s, s * 0.62);
      }
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    this.drawChipBase(ctx);

    const label = snapshot.label;
    const fs = Math.round(h * 0.26);
    ctx.font = `600 ${fs}px "SF Mono", Menlo, Consolas, monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const spacing = Math.round(fs * 0.38);

    if (!this.chip.glyphs || this.chip.glyphFs !== fs || this.chip.glyphLbl !== label) {
      const widths = [...label].map((c) => ctx.measureText(c).width);
      const total = widths.reduce((a, b) => a + b, 0) + spacing * (label.length - 1);
      let gx0 = -total / 2;
      this.chip.glyphs = [...label].map((c, i) => {
        const glyph = { c, x: gx0 + widths[i] / 2 };
        gx0 += widths[i] + spacing;
        return glyph;
      });
      this.chip.glyphFs = fs;
      this.chip.glyphLbl = label;
    }

    const inL = x + w * 0.06;
    const inR = x + w - w * 0.06;
    const wave = (px: number, t: number) => {
      const u = clamp01((px - inL) / (inR - inL));
      return Math.sin(Math.PI * u) * (Math.sin(u * 11.5 + t * 3.1) * 0.55 + Math.sin(u * 23 - t * 4.7) * 0.3 + Math.sin(u * 5.2 + t * 1.9) * 0.45);
    };
    const amp = h * 0.30 * this.listenS;
    const tw = this.now / 1000;
    const lum = Math.min(255, (140 + 80 * E + 70 * talk) | 0);
    const baseA = Math.min(1, 0.82 + 0.18 * E + 0.1 * talk);
    ctx.shadowColor = snapshot.alert ? rgba(RED, 0.75) : rgba(GREEN, Math.min(1, 0.55 + 0.4 * E + 0.3 * talk));
    ctx.shadowBlur = 14 + 26 * E + 30 * talk;

    const glyphs = this.chip.glyphs ?? [];
    const nG = Math.max(1, glyphs.length - 1);
    const scrTick = (this.now / 70) | 0;
    glyphs.forEach((glyph, i) => {
      const melt = clamp01(this.listenS * 1.35 - (i / nG) * 0.3);
      const alpha = baseA * (1 - clamp01((melt - 0.45) / 0.4));
      if (alpha <= 0.01) return;
      let ch = glyph.c;
      if (this.thinkS > 0.02) {
        let hash = (((i + 1) * 2654435761) ^ (scrTick * 2246822519)) >>> 0;
        hash = (hash ^ (hash >>> 13)) >>> 0;
        const scr = clamp01(this.thinkS * 1.35 - (i / nG) * 0.3);
        if ((hash % 1000) / 1000 < scr) ch = SCRAM[hash % SCRAM.length];
      }
      const gx = ccx + glyph.x;
      const gy = ccy + 1 + wave(gx, tw) * amp * melt;
      ctx.save(); ctx.translate(gx, gy); ctx.scale(1 - 0.25 * melt, 1 + 1.7 * melt);
      ctx.fillStyle = snapshot.alert
        ? `rgba(255,112,125,${alpha})`
        : `rgba(${lum},255,${Math.min(255, (190 + 30 * E + 40 * talk) | 0)},${alpha})`;
      ctx.fillText(ch, 0, 0); ctx.restore();
    });
    ctx.shadowBlur = 0;

    if (this.listenS > 0.03) {
      const waveAlpha = clamp01((this.listenS - 0.2) / 0.6);
      ctx.save(); ctx.beginPath(); ctx.roundRect(x + 5, y + 5, w - 10, h - 10, 4); ctx.clip();
      for (const [lineW, alpha] of [[Math.max(2, fs * 0.16), 0.28 * waveAlpha], [Math.max(1.2, fs * 0.07), 0.9 * waveAlpha]] as const) {
        ctx.strokeStyle = rgba(LISTEN_COOL, alpha); ctx.lineWidth = lineW; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.beginPath();
        for (let si = 0; si <= 64; si++) {
          const px = inL + (inR - inL) * si / 64;
          const py = ccy + 1 + wave(px, tw) * amp;
          if (si) ctx.lineTo(px, py); else ctx.moveTo(px, py);
        }
        ctx.stroke();
      }
      ctx.restore();
    }

    if (E > 0.45) {
      ctx.save(); ctx.beginPath(); ctx.roundRect(x + 5, y + 5, w - 10, h - 10, 4); ctx.clip();
      const bx = x + ((this.now / 900) % 2) * w - w * 0.5;
      const band = ctx.createLinearGradient(bx, 0, bx + w * 0.4, 0);
      band.addColorStop(0, "rgba(61,220,132,0)"); band.addColorStop(0.5, `rgba(61,220,132,${0.10 * (E - 0.45) / 0.55})`); band.addColorStop(1, "rgba(61,220,132,0)");
      ctx.fillStyle = band; ctx.fillRect(x, y, w, h); ctx.restore();
    }

    ctx.restore();
    ctx.globalCompositeOperation = "lighter";

    if (snapshot.state === "speaking" && this.now - this.lastRing > 300 && this.lvlS > 0.16) {
      this.rings.push({ t: 0, col: SPEAK_COLS[(this.rnd() * SPEAK_COLS.length) | 0] });
      this.lastRing = this.now;
    }
    if (snapshot.state === "listening" && this.now - this.lastRing > 480) {
      this.rings.push({ t: 0, col: LISTEN_COLS[(this.rnd() * LISTEN_COLS.length) | 0], inw: true });
      this.lastRing = this.now;
    }
    this.rings = this.rings.filter((ring) => {
      ring.t += dt;
      const ph = ring.t / (ring.inw ? 1100 : 950);
      if (ph >= 1) {
        if (ring.inw) this.chip.glowIn = Math.min(1, this.chip.glowIn + 0.25);
        return false;
      }
      const pad = ring.inw ? (1 - ph) * this.cell * 4.6 : ph * this.cell * 3.6;
      const a = ring.inw ? ph * ph * (0.20 + 0.22 * this.listenS) : (1 - ph) * (0.28 + 0.3 * this.lvlS);
      ctx.strokeStyle = rgba(ring.col || GREEN, a); ctx.lineWidth = ring.inw ? 1.6 : 2;
      ctx.beginPath(); ctx.roundRect(x - pad, y - pad, w + pad * 2, h + pad * 2, 8 + pad * 0.4); ctx.stroke();
      return true;
    });
  }

  private frame(dt: number) {
    const snapshot = this.getSnapshot();
    this.now += dt;
    const Et = this.targetEnergy(snapshot);
    const tauUp = snapshot.state === "speaking" ? 90 : 520;
    const tauDown = snapshot.state === "speaking" ? 230 : 950;
    this.Ecur += (Et - this.Ecur) * (1 - Math.exp(-dt / (Et > this.Ecur ? tauUp : tauDown)));
    const E = this.Ecur;

    this.speakingNow = snapshot.state === "speaking";
    this.lvlS += (clamp01(snapshot.level) - this.lvlS) * (1 - Math.exp(-dt / 90));
    this.talkS += ((this.speakingNow ? 1 : 0) - this.talkS) * (1 - Math.exp(-dt / 380));
    const listeningNow = snapshot.state === "listening";
    this.listenS += ((listeningNow ? 1 : 0) - this.listenS) * (1 - Math.exp(-dt / 380));
    const thinkingNow = snapshot.state === "thinking";
    this.thinkS += ((thinkingNow ? 1 : 0) - this.thinkS) * (1 - Math.exp(-dt / (thinkingNow ? 380 : 160)));

    const ME = this.speakingNow ? E * 0.38 : listeningNow ? E * 0.55 : snapshot.state === "idle" ? E * 0.2 : E;
    const cap = 6 + 80 * ME;
    const tries = ME > 0.6 ? 4 : 1;
    for (let i = 0; i < tries; i++) {
      if (this.pulses.length >= cap || this.rnd() >= 0.05 + 0.85 * ME) continue;
      const chipSide = this.rnd() < (listeningNow ? 0.72 : 0.62);
      const pool: number[] = [];
      this.traces.forEach((trace, index) => { if (!!trace.chip === chipSide) pool.push(index); });
      if (pool.length) this.spawnPulse(pool[(this.rnd() * pool.length) | 0], listeningNow);
    }

    if (this.rnd() < 0.005 + 0.05 * ME) {
      const c = this.comps[(this.rnd() * this.comps.length) | 0];
      if (c) c.glow = Math.max(c.glow, 0.3 + 0.3 * E);
    }

    if (this.cine) this.updateCine(dt);
    this.cineFade += ((this.cine ? 1 : 0) - this.cineFade) * (1 - Math.exp(-dt / 450));
    this.camZ = this.cine ? this.camera.z : 1;

    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);
    ctx.save();
    if (this.cine) {
      ctx.translate(this.W / 2, this.H / 2);
      ctx.scale(this.camera.z, this.camera.z);
      ctx.translate(-this.camera.x, -this.camera.y);
      const vw = this.W / this.camera.z / 2 + 60;
      const vh = this.H / this.camera.z / 2 + 60;
      this.drawWorld(ctx, [this.camera.x - vw, this.camera.y - vh, this.camera.x + vw, this.camera.y + vh], this.camera.z);
    } else if (this.bgLayer) {
      ctx.drawImage(this.bgLayer, 0, 0);
    }

    ctx.globalCompositeOperation = "lighter";
    if (this.talkS > 0.02) {
      const wa = (0.05 + 0.09 * this.lvlS) * this.talkS;
      let wash = ctx.createRadialGradient(this.W * 0.30, this.H * 0.34, 0, this.W * 0.30, this.H * 0.34, this.W * 0.42);
      wash.addColorStop(0, `rgba(53,224,255,${wa})`); wash.addColorStop(1, "rgba(0,0,0,0)"); ctx.fillStyle = wash; ctx.fillRect(0, 0, this.W, this.H);
      wash = ctx.createRadialGradient(this.W * 0.72, this.H * 0.68, 0, this.W * 0.72, this.H * 0.68, this.W * 0.44);
      wash.addColorStop(0, `rgba(157,123,255,${wa * 0.9})`); wash.addColorStop(1, "rgba(0,0,0,0)"); ctx.fillStyle = wash; ctx.fillRect(0, 0, this.W, this.H);
      wash = ctx.createRadialGradient(this.W * 0.52, this.H * 0.20, 0, this.W * 0.52, this.H * 0.20, this.W * 0.36);
      wash.addColorStop(0, `rgba(255,77,157,${wa * 0.6})`); wash.addColorStop(1, "rgba(0,0,0,0)"); ctx.fillStyle = wash; ctx.fillRect(0, 0, this.W, this.H);
    }

    const tailLen = Math.min(this.W, this.H) * (0.10 + 0.13 * ME);
    const speedK = 0.55 + 4.85 * ME;
    this.pulses = this.pulses.filter((pulse) => {
      pulse.d += pulse.sp * dt * speedK;
      const t = pulse.geo || pulse.t;
      const base = pulse.col || (t.amber ? AMBER : GREEN);
      if (pulse.d >= t.len + tailLen) {
        if (pulse.inward) {
          if (t.chip) this.chip.glowIn = Math.min(1, this.chip.glowIn + 0.45);
        } else if ((pulse.t.endComp ?? -1) >= 0) {
          const c = this.comps[pulse.t.endComp!];
          if (c) {
            c.glow = 1;
            c.flashCol = base;
            if (this.pulses.length < cap) c.out.forEach((oi) => { if (this.rnd() < 0.4) this.spawnPulse(oi, false); });
          }
        }
        return false;
      }

      const col = pulse.col || (t.amber ? AMBER_HOT : GREEN_HOT);
      const head = Math.min(pulse.d, t.len);
      let i = 1;
      while (i < t.cum.length && t.cum[i] < pulse.d - tailLen) i++;
      for (; i < t.cum.length && t.cum[i - 1] < head; i++) {
        const s0 = Math.max(t.cum[i - 1], pulse.d - tailLen);
        const s1 = Math.min(t.cum[i], head);
        if (s1 <= s0) continue;
        const seg = t.cum[i] - t.cum[i - 1] || 1;
        const f0 = (s0 - t.cum[i - 1]) / seg;
        const f1 = (s1 - t.cum[i - 1]) / seg;
        const ax = t.pts[i - 1][0] + (t.pts[i][0] - t.pts[i - 1][0]) * f0;
        const ay = t.pts[i - 1][1] + (t.pts[i][1] - t.pts[i - 1][1]) * f0;
        const bx = t.pts[i - 1][0] + (t.pts[i][0] - t.pts[i - 1][0]) * f1;
        const by = t.pts[i - 1][1] + (t.pts[i][1] - t.pts[i - 1][1]) * f1;
        const mid = (s0 + s1) / 2;
        const back = (pulse.d - mid) / tailLen;
        const a = Math.pow(Math.max(0, 1 - back), 1.6) * (0.45 + 0.5 * E);
        ctx.strokeStyle = rgba(base, a);
        ctx.lineWidth = Math.max(1.6, this.cell * 0.11) * (1 + 0.5 * (1 - back));
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      }

      if (pulse.d <= t.len) {
        const pos = this.pointAt(t, pulse.d);
        if (pos) {
          const [hx, hy] = pos;
          const hs = 9 + 9 * E;
          const glow = this.glowSprites.get(base) ?? this.glowSprites.get(GREEN)!;
          ctx.globalAlpha = 0.75 + 0.25 * E;
          ctx.drawImage(glow, hx - hs / 2, hy - hs / 2, hs, hs);
          ctx.globalAlpha = 1;
          ctx.fillStyle = col;
          ctx.beginPath(); ctx.arc(hx, hy, Math.max(1.2, this.cell * 0.06), 0, Math.PI * 2); ctx.fill();
        }
      }
      return true;
    });

    this.comps.forEach((c) => {
      if (c.glow <= 0.02) { c.glow = 0; c.flashCol = null; return; }
      const col = c.flashCol || (c.amber ? AMBER : GREEN);
      const glow = this.glowSprites.get(col) ?? this.glowSprites.get(GREEN)!;
      const cx = c.x + c.w / 2;
      const cy = c.y + c.h / 2;
      const size = Math.max(c.w, c.h) * (2.2 + 0.8 * E);
      ctx.globalAlpha = 0.45 * c.glow; ctx.drawImage(glow, cx - size / 2, cy - size / 2, size, size); ctx.globalAlpha = 1;
      ctx.strokeStyle = rgba(col, 0.25 + 0.65 * c.glow); ctx.lineWidth = 1.6;
      if (c.type === "cap") { ctx.beginPath(); ctx.arc(cx, cy, c.w * 0.34, 0, Math.PI * 2); ctx.stroke(); }
      else { ctx.beginPath(); ctx.roundRect(c.x + this.cell * 0.3, c.y + this.cell * 0.3, c.w - this.cell * 0.6, c.h - this.cell * 0.6, 3); ctx.stroke(); }
      c.glow *= Math.exp(-dt / 480);
    });

    this.drawDynamicChip(dt, E, snapshot);
    ctx.restore();

    const sweep = (this.now / 26000) % 1.3 - 0.15;
    const sheen = ctx.createLinearGradient(this.W * (sweep - 0.22), this.H * 0.1, this.W * (sweep + 0.22), this.H * 0.9);
    sheen.addColorStop(0, "rgba(180,255,215,0)"); sheen.addColorStop(0.5, "rgba(180,255,215,.045)"); sheen.addColorStop(1, "rgba(180,255,215,0)");
    ctx.fillStyle = sheen; ctx.fillRect(0, 0, this.W, this.H);

    this.drawGrain();
    if (this.cineFade < 0.4) {
      const chx = this.W * 0.80 + Math.sin(this.now / 5000) * 12;
      const chy = this.H * 0.30 + Math.cos(this.now / 4200) * 16;
      ctx.strokeStyle = `rgba(220,245,230,${0.5 * (1 - this.cineFade / 0.4)})`; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(chx - 7, chy); ctx.lineTo(chx + 7, chy); ctx.moveTo(chx, chy - 7); ctx.lineTo(chx, chy + 7); ctx.stroke();
    }
  }

  private drawGrain() {
    const ctx = this.ctx;
    if (!this.grainPat) {
      this.grainTile = document.createElement("canvas");
      this.grainTile.width = this.grainTile.height = 128;
      const ng = this.grainTile.getContext("2d")!;
      const image = ng.createImageData(128, 128);
      const rn = mulberry32(this.seed + 99);
      for (let i = 0; i < image.data.length; i += 4) {
        const v = (rn() * 255) | 0;
        image.data[i] = image.data[i + 1] = image.data[i + 2] = v;
        image.data[i + 3] = 46;
      }
      ng.putImageData(image, 0, 0);
      this.grainPat = ctx.createPattern(this.grainTile, "repeat");
    }
    if (!this.grainPat) return;
    ctx.save();
    ctx.globalCompositeOperation = "soft-light";
    ctx.translate(-(((this.now / 47) | 0) % 3) * 43, -(((this.now / 61) | 0) % 3) * 57);
    ctx.fillStyle = this.grainPat;
    ctx.fillRect(0, 0, this.W + 130, this.H + 130);
    ctx.restore();
  }

  private startCine() {
    if (!this.traces.length || this.cine) return;
    const pAt = (t: Trace, d: number) => this.pointAt(t, d) ?? [t.pts[0][0], t.pts[0][1]] as Point;
    const clampCam = (x: number, y: number, z: number): Camera => ({
      x: Math.max(this.W / z / 2 * 0.7, Math.min(this.W - this.W / z / 2 * 0.7, x)),
      y: Math.max(this.H / z / 2 * 0.7, Math.min(this.H - this.H / z / 2 * 0.7, y)),
      z,
    });
    const pick = <T,>(a: T[]) => a[(this.rnd() * a.length) | 0];
    const duration = () => 4800 + ((this.rnd() * 1800) | 0);
    const ccx = this.chip.x + this.chip.w / 2;
    const ccy = this.chip.y + this.chip.h / 2;
    const byLen = [...this.traces].sort((a, b) => b.len - a.len);
    const ics = this.comps.filter((c) => c.type === "ic").sort((a, b) => b.w * b.h - a.w * a.h);
    const caps = this.comps.filter((c) => c.type === "cap");

    const generators: Array<() => CineSegment | null> = [
      () => {
        const t = pick(byLen.slice(0, Math.min(5, byLen.length))); if (!t) return null;
        const rev = this.rnd() < 0.5; const [ax, ay] = pAt(t, t.len * (rev ? 0.8 : 0.15)); const [bx, by] = pAt(t, t.len * (rev ? 0.15 : 0.8));
        return { d: duration(), f: clampCam(ax, ay, 3.0), t: clampCam(bx, by, 2.7) };
      },
      () => {
        const rev = this.rnd() < 0.5;
        return { d: duration(), f: clampCam(this.chip.x + this.chip.w * (rev ? 0.95 : 0.05), ccy, 2.9), t: clampCam(this.chip.x + this.chip.w * (rev ? 0.05 : 0.95), ccy, 2.6), chipShot: true };
      },
      () => {
        const ic = pick(ics.slice(0, Math.min(3, ics.length))); if (!ic) return null;
        const sx = this.rnd() < 0.5 ? 1 : -1; const sy = this.rnd() < 0.5 ? 1 : -1; const x = ic.x + ic.w / 2; const y = ic.y + ic.h / 2;
        return { d: duration(), f: clampCam(x - sx * this.W * 0.16, y - sy * this.H * 0.10, 2.6), t: clampCam(x + sx * this.W * 0.16, y + sy * this.H * 0.10, 2.5) };
      },
      () => {
        const cp = pick(caps); if (!cp) return null;
        const sx = this.rnd() < 0.5 ? 1 : -1; const x = cp.x + cp.w / 2; const y = cp.y + cp.h / 2;
        return { d: duration(), f: clampCam(x - sx * this.W * 0.14, y + this.H * 0.06, 3.1), t: clampCam(x + sx * this.W * 0.14, y - this.H * 0.06, 2.9) };
      },
    ];

    const shots: CineSegment[] = [];
    for (const gen of [...generators].sort(() => this.rnd() - 0.5)) {
      if (shots.length >= 4) break;
      const s = gen(); if (s) shots.push(s);
    }
    shots.forEach((s) => {
      const zAvg = (s.f.z + s.t.z) / 2;
      const dist = Math.hypot(s.t.x - s.f.x, s.t.y - s.f.y) * zAvg;
      s.d = Math.max(4300, Math.min(7800, (dist / 0.33) * (0.92 + this.rnd() * 0.16)));
    });
    this.cine = { t: 0, segs: [...shots, { d: 6600, f: { x: ccx, y: ccy, z: 2.3 }, t: { x: this.W / 2, y: this.H / 2, z: 1 }, out: true }] };
    this.canvas.classList.add("jace-av-cinematic");
  }

  private endCine() {
    this.cine = null;
    this.camera = { x: this.W / 2, y: this.H / 2, z: 1 };
    this.canvas.classList.remove("jace-av-cinematic");
  }

  private updateCine(dt: number) {
    if (!this.cine) return;
    this.cine.t += dt;
    let t = this.cine.t;
    for (const segment of this.cine.segs) {
      if (t <= segment.d) {
        const p = t / segment.d;
        const e = segment.out ? 1 - Math.pow(1 - p, 3) : p;
        this.camera = {
          x: segment.f.x + (segment.t.x - segment.f.x) * e,
          y: segment.f.y + (segment.t.y - segment.f.y) * e,
          z: segment.f.z + (segment.t.z - segment.f.z) * e,
        };
        return;
      }
      t -= segment.d;
    }
    this.endCine();
  }
}
