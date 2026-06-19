// Theme picker (Phase 7.1) — two Everforest palettes (light-hard / dark-hard),
// toggled in the config area, persisted across reloads. Defaults to DARK on a
// fresh visit (matches the dark operator bench; light is opt-in). The active
// palette is selected by the `data-theme` attribute on <html> (see styles.css).

export type Theme = "light" | "dark";

const KEY = "terramind.theme";

export function loadTheme(): Theme {
  const stored = localStorage.getItem(KEY);
  return stored === "light" || stored === "dark" ? stored : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

export function saveTheme(theme: Theme): void {
  localStorage.setItem(KEY, theme);
  applyTheme(theme);
}
