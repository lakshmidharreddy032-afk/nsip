import { create } from "zustand";

export type Theme = "light" | "dark" | "system";

function read(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function applyTheme(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

type UiState = {
  theme: Theme;
  paletteOpen: boolean;
  online: boolean;
  setTheme: (t: Theme) => void;
  setPalette: (open: boolean) => void;
  setOnline: (o: boolean) => void;
};

export const useUi = create<UiState>((set) => ({
  theme: read("nsip.theme", "system") as Theme,
  paletteOpen: false,
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  setTheme: (theme) => {
    try {
      localStorage.setItem("nsip.theme", theme);
    } catch {
      /* per-viewer convenience only */
    }
    applyTheme(theme);
    set({ theme });
  },
  setPalette: (paletteOpen) => set({ paletteOpen }),
  setOnline: (online) => set({ online }),
}));
