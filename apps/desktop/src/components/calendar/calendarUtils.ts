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

export function formatTime(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function formatDate(value: Date, options?: Intl.DateTimeFormatOptions): string {
  return value.toLocaleDateString([], options ?? { day: "numeric", month: "short", year: "numeric" });
}

export function eventDateKey(event: CalendarEvent): string {
  if (event.all_day && event.start_date) return event.start_date;
  return event.start_at ? dateKey(new Date(event.start_at)) : "";
}

export function eventTimeLabel(event: CalendarEvent): string {
  return event.all_day ? "All day" : formatTime(event.start_at);
}

export function providerName(providerId: string): string {
  if (providerId === "google") return "Google";
  if (providerId === "microsoft") return "Outlook";
  if (providerId === "jace") return "Jace";
  return providerId;
}

export function viewRange(cursor: Date, view: CalendarViewMode): { start: Date; end: Date } {
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
