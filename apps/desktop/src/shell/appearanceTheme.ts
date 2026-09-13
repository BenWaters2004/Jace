import {
  useCallback,
  useEffect,
  useState,
} from "react";

export type JaceAppearanceTheme =
  | "jace"
  | "deep-black"
  | "graphite"
  | "cyber-green"
  | "ice-blue";

export type JaceThemeDefinition = {
  id: JaceAppearanceTheme;
  name: string;
  description: string;
  preview: {
    background: string;
    panel: string;
    accent: string;
    secondary: string;
    text: string;
  };
};

export const JACE_THEME_STORAGE_KEY =
  "jace.desktop.appearance-theme.v1";

export const JACE_APPEARANCE_EVENT =
  "jace:appearance-theme";

const CHANNEL_NAME =
  "jace-desktop-appearance-theme";

export const JACE_THEME_DEFINITIONS:
  JaceThemeDefinition[] = [
    {
      id: "jace",
      name: "Jace",
      description:
        "The current teal-and-cyan Command Center palette.",
      preview: {
        background: "#04100f",
        panel: "#081822",
        accent: "#1fd0a6",
        secondary: "#59d2f1",
        text: "#ecf9ff",
      },
    },
    {
      id: "deep-black",
      name: "Deep Black",
      description:
        "Near-black surfaces with restrained teal signal lighting.",
      preview: {
        background: "#020304",
        panel: "#07090b",
        accent: "#6edbc2",
        secondary: "#7bb8c7",
        text: "#f1f5f4",
      },
    },
    {
      id: "graphite",
      name: "Graphite",
      description:
        "Neutral charcoal and slate for a calmer workstation.",
      preview: {
        background: "#0b0d11",
        panel: "#151920",
        accent: "#8fa5bd",
        secondary: "#6f879d",
        text: "#eef1f5",
      },
    },
    {
      id: "cyber-green",
      name: "Cyber Green",
      description:
        "High-energy terminal green with deep emerald panels.",
      preview: {
        background: "#020b06",
        panel: "#07170d",
        accent: "#49ef8a",
        secondary: "#a0ffbd",
        text: "#eafff0",
      },
    },
    {
      id: "ice-blue",
      name: "Ice Blue",
      description:
        "Cold blue and cyan lighting with clean navy surfaces.",
      preview: {
        background: "#03101a",
        panel: "#081b29",
        accent: "#51c9ff",
        secondary: "#a7e8ff",
        text: "#eefaff",
      },
    },
  ];

function isTheme(
  value: unknown,
): value is JaceAppearanceTheme {
  return (
    value === "jace" ||
    value === "deep-black" ||
    value === "graphite" ||
    value === "cyber-green" ||
    value === "ice-blue"
  );
}

export function readAppearanceTheme():
  JaceAppearanceTheme {
  if (typeof window === "undefined") {
    return "jace";
  }

  try {
    const stored = window.localStorage.getItem(
      JACE_THEME_STORAGE_KEY,
    );
    return isTheme(stored) ? stored : "jace";
  } catch {
    return "jace";
  }
}

export function applyAppearanceTheme(
  theme: JaceAppearanceTheme,
): void {
  if (typeof document !== "undefined") {
    document.documentElement.dataset.jaceTheme =
      theme;
    document.documentElement.style.colorScheme =
      "dark";
  }
}

export function applyStoredAppearanceTheme():
  JaceAppearanceTheme {
  const theme = readAppearanceTheme();
  applyAppearanceTheme(theme);
  return theme;
}

function broadcastTheme(
  theme: JaceAppearanceTheme,
): void {
  try {
    window.localStorage.setItem(
      JACE_THEME_STORAGE_KEY,
      theme,
    );
  } catch {
    // Local UI preference only.
  }

  applyAppearanceTheme(theme);

  window.dispatchEvent(
    new CustomEvent(JACE_APPEARANCE_EVENT, {
      detail: { theme },
    }),
  );

  try {
    const channel = new BroadcastChannel(
      CHANNEL_NAME,
    );
    channel.postMessage({ theme });
    channel.close();
  } catch {
    // BroadcastChannel is optional.
  }
}

export function setAppearanceTheme(
  theme: JaceAppearanceTheme,
): void {
  broadcastTheme(theme);
}

export function useAppearanceTheme() {
  const [theme, setThemeState] =
    useState<JaceAppearanceTheme>(
      () => readAppearanceTheme(),
    );

  useEffect(() => {
    let channel: BroadcastChannel | null = null;

    const accept = (value: unknown) => {
      if (!isTheme(value)) return;
      setThemeState(value);
      applyAppearanceTheme(value);
    };

    const onCustom = (event: Event) => {
      accept(
        (
          event as CustomEvent<{
            theme?: unknown;
          }>
        ).detail?.theme,
      );
    };

    const onStorage = (event: StorageEvent) => {
      if (
        event.key !== JACE_THEME_STORAGE_KEY
      ) {
        return;
      }

      accept(event.newValue);
    };

    window.addEventListener(
      JACE_APPEARANCE_EVENT,
      onCustom,
    );
    window.addEventListener(
      "storage",
      onStorage,
    );

    try {
      channel = new BroadcastChannel(
        CHANNEL_NAME,
      );
      channel.onmessage = (event) => {
        accept(event.data?.theme);
      };
    } catch {
      channel = null;
    }

    return () => {
      window.removeEventListener(
        JACE_APPEARANCE_EVENT,
        onCustom,
      );
      window.removeEventListener(
        "storage",
        onStorage,
      );
      channel?.close();
    };
  }, []);

  useEffect(() => {
    applyAppearanceTheme(theme);
  }, [theme]);

  const setTheme = useCallback(
    (next: JaceAppearanceTheme) => {
      setThemeState(next);
      broadcastTheme(next);
    },
    [],
  );

  const definition =
    JACE_THEME_DEFINITIONS.find(
      (item) => item.id === theme,
    ) ?? JACE_THEME_DEFINITIONS[0];

  return {
    theme,
    definition,
    definitions: JACE_THEME_DEFINITIONS,
    setTheme,
  };
}
