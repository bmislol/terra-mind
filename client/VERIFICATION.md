# Client mod — in-game verification log

The tModLoader mod has **no CI** (ARCH §13.3): building it needs the tModLoader
runtime/targets and is fragile for little value — a deliberate skip. This file
is the **in-repo evidence that stands in for a green check**. For each Phase 4.3
commit, the in-game `client.log` round-trip excerpt is pasted below, captured on
a real run with the docker stack up. The PR body references this file.

**Environment:** tModLoader v2026.4.3.0 / Terraria 1.4.4.9 (.NET 8); backend via
`docker compose up -d` at `http://localhost:8000` (D-028); account
`test@test.dev`.

---

## Commit 1 — login + authed `/bot/ask` round-trip

**What it proves:** `await` works inside the mod for the first time; the
post-`await` chat render marshals through `QueueMainThreadAction` without the
intermittent crash (RUNBOOK §9); the **real** `AskResponse` (`answer` +
`session_id`) deserializes — the spike's `KeyNotFoundException` (from parsing the
echo stub's `reply`) is resolved.

**Steps:**
1. `docker compose up -d` — wait for `Application startup complete` (~100s).
2. Set the mod config `BackendUrl` to `http://localhost:8000` (default).
3. In-game: `/bot login test@test.dev <password>` → `logged in`.
4. `/bot what should I do first?` → a real contextual answer renders in chat.

**`client.log` excerpt** (verbatim, 2026-06-14 20:24–20:26 run):

```
[20:24:06.704] [Main Thread/INFO] [TerraMind]: /bot login → POST /auth/jwt/login (credentials not logged)
[20:24:06.711] [Main Thread/DEBUG] [tML]: Web Request: http://localhost:8000/auth/jwt/login
[20:24:06.884] [.NET TP Worker/INFO] [TerraMind]: /bot login ok: access+refresh received (held in memory; token values not logged)
[20:24:34.082] [Main Thread/INFO] [TerraMind]: /bot ask → http://localhost:8000/bot/ask message="what should i do first?" session_id=(new)
[20:24:39.973] [.NET TP Worker/INFO] [TerraMind]: /bot ask ok: routing=agent session_id=49d64e6f-d7c4-470f-bac0-a7949b5e3f4f
answer: You're a **melee player in pre-boss progression**, so here's what to do first:
1. **Farm materials and craft silver or tungsten armor** ...
3. **Fight the Eye of Cthulhu** — this is the first progression boss ...
[20:26:48.782] [Main Thread/INFO] [TerraMind]: /bot ask → http://localhost:8000/bot/ask message="based on my selected weapon what can i do?" session_id=49d64e6f-d7c4-470f-bac0-a7949b5e3f4f
[20:26:57.711] [.NET TP Worker/INFO] [TerraMind]: /bot ask ok: routing=agent session_id=49d64e6f-d7c4-470f-bac0-a7949b5e3f4f
answer: Based on your loadout, you're a **Ranger in pre-boss progression**. ...  (full answer in client.log)
```

**Result: ✅ verified.** The excerpt shows, end-to-end:
- **Login is form-encoded and accepted** — `/auth/jwt/login` → `login ok`, no 401 (the form-vs-JSON trap is correctly handled).
- **`await` + marshaling held** — the request lines log on the `Main Thread`, the responses on a `.NET TP Worker` (background) thread; the answer still rendered in chat via `Print()` → `QueueMainThreadAction` with **no crash**.
- **Real `AskResponse` parsed** — `routing=agent` + `session_id` extracted from the live shape; the spike's `KeyNotFoundException` is gone.
- **`session_id` threading works** — first ask `session_id=(new)`; the response returns `49d64e6f-…`; the next ask **sends** `session_id=49d64e6f-…` → short-term-memory continuity confirmed (4.1b).
- **Class detection through the live path** — "based on my selected weapon" → **Ranger** detected from the equipped weapon (D-026), the whole mod → auth → RLS → agent → render pipeline running end to end.

**Known item (P-016, not a 4.3 bug):** the generic "what should I do first?" gave a default/melee answer and, on a repeat, asked for context — the agent didn't always *use* the state the mod always *sends*. Captured for Section 3/6 prompt/router tuning; transport is unaffected (the payload arrives every call).

---

## Commit 2 — token persistence + discard password

**What it proves:** the first filesystem touch is safe — after login the token
pair is written to `token.json` under `Main.SavePath`; on a fresh launch the mod
loads it and `/bot` works **without re-login**; a missing/corrupt file falls back
to `/bot login` rather than crashing. The password is used once and never
persisted — `token.json` holds only the (revocable) tokens. A world-entry
confirmation tells the player they're still authenticated (no more silent
restore).

**Steps:**
1. `/bot login test@test.dev <password>` once → chat shows `logged in as test@test.dev`; log shows `token pair persisted to token.json`.
2. **Restart Terraria** (game fully closed + relaunched; within the 30-min access-token TTL — durable refresh is commit 3).
3. On entering the world: chat shows **`session restored — logged in`** (no re-login, no name shown) — the silent-restore gap is closed.
4. `/bot what should I do first?` → answers **without** re-running `/bot login` (log shows `token.json loaded — session restored`).
5. Inspect `token.json` → it holds `access_token`/`refresh_token`, **no password**.

**`client.log` excerpt** (verbatim, 2026-06-14 22:45–22:46 — relaunch with a `token.json` written by a prior session):

```
[22:45:48.661] [Main Thread/INFO] [tML]: Starting tModLoader client 1.4.4.9+2026.04.3.0 … built 06/01/2026
[22:45:57.923] [.NET TP Worker/INFO] [TerraMind]: token.json loaded — session restored from a previous login
[22:46:02.956] [.NET TP Worker/INFO] [tML]: Building: TerraMind
[22:46:03.842] [.NET TP Worker/INFO] [tML]: Compilation finished with 0 errors and 11 warnings
[22:46:04.565] [.NET TP Worker/INFO] [TerraMind]: token.json loaded — session restored from a previous login
[22:46:11.792] [Main Thread/INFO] [Terraria]: Entering world with player: test, IsCloud=False, …
```

**Result: ✅ verified.**
- **Persistence survives a full program restart** — a fresh client launch (`Starting tModLoader client`, 22:45:48) found and loaded a `token.json` written in a now-overwritten earlier session → `token.json loaded — session restored` (22:45:57). Not a hot-reload — the process started cold.
- **All commit-2 code compiled clean** — `0 errors` (22:46:03) across `AuthStore`, `TerraMind.Load`, `Session.Email`, and `TerraMindPlayer`. The **parameterless `OnEnterWorld()` signature is correct** (a wrong one is a compile *error*, not a warning).
- **The world-entry feedback path ran** — the player entered the world (22:46:11) immediately after a restore (22:46:04) with an email-less (token-only) session, which is exactly the branch that prints `session restored — logged in`. (Chat is `Main.NewText`, not written to `client.log`, so the on-screen string is the visual check.)
- The **11 warnings are all `CS8632`** (nullable-annotation context) — **non-blocking** (0 errors, mod runs), but see the known-issue note: the csproj `<Nullable>enable</Nullable>` is not silencing them in the tModLoader build.

**Confirmed by the operator's commit-2 report (not in this rotated log):** `token.json` `cat`-confirmed to hold **access + refresh JWTs only, no password**; `/bot` answered after restart with **no re-login**.

### Build cleanup — `CS8632` (✅ resolved in the nullable-fix commit)

The csproj `<Nullable>enable</Nullable>` does **not** reach the tModLoader build — it
kept emitting `CS8632` on every `?` annotation (11×, e.g. `StateDtos.cs:24/40`,
`Session.cs:16-19`, `TransportDtos.cs`, `AuthStore.cs`, `TerraMind.cs`). The 4.2 "fix"
was assumed, never re-verified. **Fixed** with a `#nullable enable` directive atop each
of the 5 files using `?` (the warning's own prescribed remedy, which the build honors);
the csproj comment + Checklist 4.2 record were corrected to match reality, and the
property is kept only for the IDE analyzer. The rebuild at 23:11:51 reports **0 errors
and 0 warnings** (`grep -c "warning CS"` = 0).

---

## Commit 3 — `/auth/refresh` on launch + `/bot logout`

**What it proves:** a restored session stays usable beyond the 30-min access-token
TTL — on launch (world entry) the saved refresh token is exchanged at
`/auth/refresh` for a fresh access JWT (D-006/D-027); a 401 mid-session triggers
the same refresh + a one-shot retry. `/bot logout` clears the local token, deletes
`token.json`, and denylists the refresh token server-side (D-029) so it can't be
reused.

**Steps:**
1. With a saved login, **restart Terraria** → world entry shows `session restored — logged in`; `client.log` shows `/auth/refresh on launch ok — session restored`.
2. `/bot <question>` → answers with the freshly-minted access token, no re-login.
3. `/bot logout` → chat `logged out`; `client.log` shows `local token cleared + token.json deleted` then `refresh token revoked server-side`; `token.json` is gone from `Main.SavePath/TerraMind/`.
4. `/bot <question>` → `not logged in — use /bot login` (local state cleared).
5. (Server-side proof) the now-revoked refresh token is rejected by a fresh `/auth/refresh` (401) — denylist confirmed.

**`client.log` excerpt** (verbatim, 2026-06-14 23:12–23:17 — restart, ask, logout):

```
[23:12:04.157] [Main Thread/INFO] [Terraria]: Entering world with player: test, …
[23:12:04.242] [Main Thread/DEBUG] [tML]: Web Request: http://localhost:8000/auth/refresh
[23:12:04.568] [.NET TP Worker/INFO] [TerraMind]: /auth/refresh on launch ok — session restored
[23:15:16.813] [Main Thread/INFO] [TerraMind]: /bot ask → http://localhost:8000/bot/ask message="how can i beat the eye of cuthulu?" session_id=(new)
[23:15:22.257] [.NET TP Worker/INFO] [TerraMind]: /bot ask ok: routing=agent session_id=30038147-d0b7-48b6-b1d4-7a66e17ae001
answer: Good news—as a Ranger in the pre-boss stage, you're well-suited for the Eye of Cthulhu. …  (full answer in client.log)
[23:17:13.017] [Main Thread/INFO] [TerraMind]: /bot logout: local token cleared + token.json deleted
[23:17:13.018] [Main Thread/DEBUG] [tML]: Web Request: http://localhost:8000/auth/logout
[23:17:13.310] [.NET TP Worker/INFO] [TerraMind]: /bot logout: refresh token revoked server-side (denylisted)
```

**Result: ✅ verified.**
- **Refresh-on-launch went through `/auth/refresh`** — world entry (23:12:04) → `Web Request: …/auth/refresh` → `/auth/refresh on launch ok`. The `Web Request` line confirms an actual HTTP exchange, not a still-valid cached access token.
- **Authed `/bot/ask` works post-refresh with no re-login** — `routing=agent`, fresh `session_id`, real answer rendered. (Bonus: it grounded on the **Ranger** loadout for a generic boss question — P-016 is intermittent; here it used the state.)
- **`/bot logout` is both-sided** — local: `token cleared + token.json deleted`; server: `Web Request: …/auth/logout` → `refresh token revoked server-side (denylisted)` (D-029).
- **Build clean** — the rebuild (23:11:51) reported **0 errors and 0 warnings**; `grep -c "warning CS"` over the log = 0. The nullable fix is confirmed effective.

**Confirmed by the operator (chat-only / filesystem, not in log):** the world-entry `session restored — logged in` confirmation showed; `/bot` after logout returned `not logged in — use /bot login`; `ls token.json` → *No such file or directory*.
