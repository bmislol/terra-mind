import { useState } from "react";

import { loadTheme, saveTheme, type Theme } from "../theme";

/** Light/dark segmented switch (config area). Persists + applies immediately. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(loadTheme);

  function choose(next: Theme) {
    setTheme(next);
    saveTheme(next);
  }

  return (
    <div className="row between theme-row">
      <span className="field-label">Theme</span>
      <div className="segmented" role="group" aria-label="Theme">
        <button
          type="button"
          className={theme === "light" ? "seg active" : "seg"}
          aria-pressed={theme === "light"}
          onClick={() => choose("light")}
        >
          Light
        </button>
        <button
          type="button"
          className={theme === "dark" ? "seg active" : "seg"}
          aria-pressed={theme === "dark"}
          onClick={() => choose("dark")}
        >
          Dark
        </button>
      </div>
    </div>
  );
}
