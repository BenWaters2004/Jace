import type { MemoryType } from "./types";

export {
  API_BASE_URL,
  WS_BASE_URL,
  JACE_DEPLOYMENT_MODE,
} from "./runtimeConfig";

export const MEMORY_TYPES: Array<{
  value: MemoryType;
  label: string;
}> = [
  {
    value: "fact",
    label: "Fact",
  },
  {
    value: "preference",
    label: "Preference",
  },
  {
    value: "project",
    label: "Project",
  },
  {
    value: "decision",
    label: "Decision",
  },
  {
    value: "goal",
    label: "Goal",
  },
];