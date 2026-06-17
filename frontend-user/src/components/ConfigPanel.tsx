import { useEffect, useState } from "react";

import {
  ApiError,
  eraseMe,
  getPreferences,
  getVersions,
  SessionExpiredError,
  updatePreferences,
} from "../api";
import { isGuestSession } from "../auth";

export function ConfigPanel({ onLogout }: { onLogout: () => void }) {
  const [isGuest] = useState(isGuestSession);
  const [versions, setVersions] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [confirmErase, setConfirmErase] = useState(false);
  const [erased, setErased] = useState(false);

  /** Map an error to a message, bouncing to login if the session is dead. */
  function handle(err: unknown): string {
    if (err instanceof SessionExpiredError) {
      onLogout();
      return "Session expired — please log in again.";
    }
    return err instanceof ApiError ? err.message : "Something went wrong.";
  }

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [vs, prefs] = await Promise.all([getVersions(), getPreferences()]);
        if (!active) return;
        setVersions(vs);
        setSelected(prefs.selected_version ?? "");
      } catch (err) {
        if (active) setError(handle(err));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
    // Load once on mount; not re-run on prop changes (intentional empty deps).
  }, []);

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(null);
    try {
      const prefs = await updatePreferences({ selected_version: selected || null });
      setSelected(prefs.selected_version ?? "");
      setSaved(new Date().toLocaleTimeString());
    } catch (err) {
      setError(handle(err));
    } finally {
      setSaving(false);
    }
  }

  async function erase() {
    setErasing(true);
    setError(null);
    try {
      await eraseMe();
      setErased(true);
    } catch (err) {
      setError(handle(err));
    } finally {
      setErasing(false);
    }
  }

  if (erased) {
    return (
      <section className="card">
        <h2>Data erased</h2>
        <p>
          Your conversation data (sessions, messages, memory) has been deleted.
          Your preferences are kept.
        </p>
        <button className="secondary" type="button" onClick={onLogout}>
          Log out
        </button>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="card">
        <p className="loading">Loading your settings…</p>
      </section>
    );
  }

  return (
    <section className="card">
      <div className="row between">
        <h2>Preferences</h2>
        <button className="link" type="button" onClick={onLogout}>
          Log out
        </button>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <label>
        Wiki version
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={versions.length === 0}
        >
          <option value="">(none)</option>
          {versions.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
      {versions.length === 0 && (
        <p className="hint">No corpus versions are available yet.</p>
      )}

      <button className="primary" type="button" onClick={save} disabled={saving}>
        {saving ? "Saving…" : "Save preferences"}
      </button>
      {saved && (
        <p className="notice">Saved at {saved}. Reload the page to confirm it persists.</p>
      )}

      {isGuest ? (
        <>
          <hr />
          <p className="hint">
            Guest session — nothing is saved server-side, so there&apos;s nothing
            to delete.
          </p>
        </>
      ) : (
        <>
          <hr />
          <h3>Delete my data</h3>
          <p className="hint">
            Permanently deletes all your conversation data (sessions, messages,
            memory). Your preferences are kept. This can&apos;t be undone.
          </p>
          {!confirmErase ? (
            <button
              className="danger"
              type="button"
              onClick={() => setConfirmErase(true)}
            >
              Delete my data…
            </button>
          ) : (
            <div className="confirm">
              <p>Are you sure? This permanently deletes your conversation data.</p>
              <div className="row">
                <button
                  className="danger"
                  type="button"
                  onClick={erase}
                  disabled={erasing}
                >
                  {erasing ? "Deleting…" : "Yes, delete everything"}
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => setConfirmErase(false)}
                  disabled={erasing}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
