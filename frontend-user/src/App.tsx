import { useState } from "react";

import { clearTokens, loadTokens } from "./auth";
import { AuthPanel } from "./components/AuthPanel";
import { ConfigPanel } from "./components/ConfigPanel";

export function App() {
  const [authed, setAuthed] = useState<boolean>(() => Boolean(loadTokens().access));

  function handleLogout() {
    clearTokens();
    setAuthed(false);
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 21v-9" />
              <path d="M12 12c0-3.3 2.2-5.5 6-5.5C18 9.8 15.8 12 12 12z" />
              <path d="M12 15c0-3.3-2.2-5.5-6-5.5C6 12.8 8.2 15 12 15z" />
            </svg>
          </span>
          <h1>TerraMind</h1>
        </div>
        <p className="subtitle">Config portal — manage your account &amp; preferences</p>
      </header>

      <main className="app-main">
        {authed ? (
          <ConfigPanel onLogout={handleLogout} />
        ) : (
          <AuthPanel onAuthed={() => setAuthed(true)} />
        )}
      </main>

      <footer className="app-footer">
        Not a chat surface — chat happens in-game via the TerraMind mod.
      </footer>
    </div>
  );
}
