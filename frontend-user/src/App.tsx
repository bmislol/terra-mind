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
        <h1>TerraMind</h1>
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
