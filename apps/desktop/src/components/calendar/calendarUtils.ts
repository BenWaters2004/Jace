import type { CalendarEvent, CalendarViewMode } from "../../types";

export const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const HOUR_START = 7;
export const HOUR_END = 22;
export const HOUR_HEIGHT = 64;

export function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function dateKey(value: Date): string {
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

export function parseDateKey(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day, 12, 0, 0, 0);
}

export function addDays(value: Date, days: number): Date {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

export function daysBetween(left: Date, right: Date): number {
  const start = Date.UTC(left.getFullYear(), left.getMonth(), left.getDate());
  const end = Date.UTC(right.getFullYear(), right.getMonth(), right.getDate());
  return Math.round((end - start) / 86_400_000);
}

export function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

export function startOfWeek(value: Date): Date {
  const date = startOfDay(value);
  const weekday = date.getDay();
  return addDays(date, weekday === 0 ? -6 : 1 - weekday);
}

export function startOfMonth(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

export function startOfMonthGrid(value: Date): Date {
  return startOfWeek(startOfMonth(value));
}

export function isoLocal(date: string, time: string): string {
  return `${date}T${time}:00`;
}

export function partsForInstant(value: string, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value));

  const map = new Map(parts.map((part) => [part.type, part.value]));

  return {
    year: map.get("year") ?? "0000",
    month: map.get("month") ?? "00",
    day: map.get("day") ?? "00",
    hour: Number(map.get("hour") ?? "0"),
    minute: Number(map.get("minute") ?? "0"),
  };
}

export function formatTime(value: string | null, timeZone = "Europe/London"): string {
  if (!value) return "";

  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
}

export function formatDate(
  value: Date,
  options?: Intl.DateTimeFormatOptions,
  timeZone?: string,
): string {
  return value.toLocaleDateString(
    "en-GB",
    {
      ...(options ?? { day: "numeric", month: "short", year: "numeric" }),
      ...(timeZone ? { timeZone } : {}),
    },
  );
}

export function formatInstantDate(
  value: string | null,
  timeZone = "Europe/London",
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!value) return "";

  return new Intl.DateTimeFormat(
    "en-GB",
    {
      timeZone,
      ...(options ?? { day: "numeric", month: "short", year: "numeric" }),
    },
  ).format(new Date(value));
}

export function eventDateKey(
  event: CalendarEvent,
  timeZone = "Europe/London",
): string {
  if (event.all_day && event.start_date) return event.start_date;
  if (!event.start_at) return "";

  const parts = partsForInstant(event.start_at, timeZone);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function eventMinutes(
  value: string | null,
  timeZone = "Europe/London",
): number {
  if (!value) return 0;
  const parts = partsForInstant(value, timeZone);
  return parts.hour * 60 + parts.minute;
}

export function eventTimeLabel(
  event: CalendarEvent,
  timeZone = "Europe/London",
): string {
  return event.all_day ? "All day" : formatTime(event.start_at, timeZone);
}

export function providerName(providerId: string): string {
  if (providerId === "google") return "Google";
  if (providerId === "microsoft") return "Outlook";
  if (providerId === "jace") return "Jace";
  return providerId;
}

export function viewRange(
  cursor: Date,
  view: CalendarViewMode,
): { start: Date; end: Date } {
  if (view === "month") {
    const start = startOfMonthGrid(cursor);
    return { start, end: addDays(start, 42) };
  }
  if (view === "week") {
    const start = startOfWeek(cursor);
    return { start, end: addDays(start, 7) };
  }
  if (view === "day") {
    const start = startOfDay(cursor);
    return { start, end: addDays(start, 1) };
  }
  const start = startOfDay(cursor);
  return { start, end: addDays(start, 30) };
}

export function calendarRangeParameter(value: Date): string {
  return `${dateKey(value)}T00:00:00`;
}

export function allDayEventCoversDate(
  event: CalendarEvent,
  day: Date,
): boolean {
  if (!event.all_day || !event.start_date || !event.end_date_exclusive) {
    return false;
  }

  const key = dateKey(day);
  return key >= event.start_date && key < event.end_date_exclusive;
}

export function isMultiDayAllDay(event: CalendarEvent): boolean {
  if (!event.all_day || !event.start_date || !event.end_date_exclusive) {
    return false;
  }

  return event.end_date_exclusive > dateKey(addDays(parseDateKey(event.start_date), 1));
}
