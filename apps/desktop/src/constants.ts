import type { MemoryType } from "./types";

export const API_BASE_URL = "http://127.0.0.1:8000";

export const MEMORY_TYPES: Array<{ value: MemoryType; label: string }> = [
  { value: "fact", label: "Fact" },
  { value: "preference", label: "Preference" },
  { value: "project", label: "Project" },
  { value: "decision", label: "Decision" },
  { value: "goal", label: "Goal" },
  { value: "temporary", label: "Temporary" },
  { value: "other", label: "Other" },
];
