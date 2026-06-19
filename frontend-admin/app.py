"""TerraMind operator / test bench (Phase 5.2).

Operator-gated Streamlit bench. The **test chat** is the centerpiece: it drives
the full `/bot/ask` pipeline (router → agent/RAG → answer) with a preset
StatePayload, so the live demo has a fallback if the game won't launch (RUNBOOK
§7.1). Plus operator views: corpus versions, tenants, audit log.

Gating: a player token can log in but is blocked from the bench — the real
enforcement is the backend (`require_operator` → 403 on `/admin/*`); this just
hides the UI.
"""

from __future__ import annotations

from typing import Any

import admin_api as api
import streamlit as st
from presets import PRESETS

st.set_page_config(page_title="TerraMind — Operator/Test Bench", layout="wide")

st.session_state.setdefault("token", None)
st.session_state.setdefault("role", None)
st.session_state.setdefault("session_id", None)
st.session_state.setdefault("last_answer", None)
st.session_state.setdefault("preset", None)
st.session_state.setdefault("rerag_job_id", None)


def _logout() -> None:
    for key in ("token", "role", "session_id", "last_answer", "preset", "rerag_job_id"):
        st.session_state[key] = None


def _item_label(item: dict[str, Any] | None) -> str:
    """One item → a readable label, prefix included (display only)."""
    if not item:
        return "—"
    prefix = f"{item['prefix']} " if item.get("prefix") else ""
    return f"{prefix}{item.get('name', '?')}"


def _item_list(items: list[dict[str, Any]]) -> str:
    return ", ".join(_item_label(i) for i in items) if items else "—"


def _preset_summary(state: dict[str, Any]) -> list[dict[str, str]]:
    """A clean Field/Value view of a preset's StatePayload — display only, no
    schema change. The raw payload stays one click away in its expander."""
    gear = state["gear"]
    world = state["world"]
    stats = state["stats"]
    bosses = world["downed_bosses"]
    return [
        {"Field": "Version", "Value": state["game_version"]},
        {"Field": "Weapon", "Value": _item_label(gear.get("weapon"))},
        {"Field": "Armor", "Value": _item_list(gear.get("armor", []))},
        {"Field": "Accessories", "Value": _item_list(gear.get("accessories", []))},
        {"Field": "Inventory", "Value": _item_list(state.get("inventory", []))},
        {
            "Field": "Stats",
            "Value": (
                f"{stats['life']}/{stats['max_life']} HP · "
                f"{stats['mana']}/{stats['max_mana']} mana · {stats['defense']} def"
            ),
        },
        {"Field": "Hardmode", "Value": "Yes" if world["hardmode"] else "No"},
        {"Field": "Bosses downed", "Value": ", ".join(bosses) if bosses else "—"},
        {"Field": "Biome", "Value": world["biome"]},
    ]


@st.fragment(run_every=2)
def _rerag_status_panel() -> None:
    """Poll the active re-rag job every 2s and render its progress/terminal state.

    Rendered only while a job_id is set (the worker writes the durable row + a
    Redis live-progress hash; this reads them via GET /admin/rerag/status/{id}).
    """
    job_id = st.session_state.get("rerag_job_id")
    if not job_id:
        return
    try:
        status = api.rerag_status(st.session_state.token, job_id)
    except api.ApiError as exc:
        st.error(f"Status check failed: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not reach the API: {exc}")
        return

    state = status.get("status", "?")
    done = status.get("done") or 0
    total = status.get("total") or 0
    frac = (done / total) if total else 0.0
    st.caption(f"job `{job_id}`")
    if state == "queued":
        st.progress(0.0, text="queued — waiting for the worker…")
    elif state == "running":
        st.progress(frac, text=f"running — {status.get('stage') or '…'} {done}/{total}")
    elif state == "succeeded":
        st.success(
            f"Re-rag succeeded — {status.get('version')} ({done} pages embedded)."
        )
    elif state == "failed":
        st.error(f"Re-rag failed: {status.get('error') or 'unknown error'}")
    else:
        st.json(status)


# ── Sidebar: login ────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("TerraMind")
    st.caption("Operator / test bench")
    if st.session_state.token is None:
        with st.form("login_form"):
            email = st.text_input("Email", value="operator@terra-mind.dev")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
        if submitted:
            try:
                token = api.login(email, password)
                st.session_state.token = token
                st.session_state.role = api.token_role(token)
                st.rerun()
            except api.ApiError as exc:
                st.error(f"Login failed: {exc}")
            except Exception as exc:  # noqa: BLE001 — surface any connection error
                st.error(f"Could not reach the API: {exc}")
    else:
        st.success(f"Logged in — role: **{st.session_state.role or 'unknown'}**")
        st.button("Log out", on_click=_logout)

# ── Gates ─────────────────────────────────────────────────────────────────────
if st.session_state.token is None:
    st.info(
        "Log in to use the bench. You need an **operator** account — bootstrap "
        "one first (see the README / RUNBOOK §3)."
    )
    st.stop()

if st.session_state.role != "operator":
    st.error(
        "This is the **operator** bench, but you're logged in as a **player**. "
        "Bootstrap an operator (RUNBOOK §3) and log in with that account."
    )
    st.stop()

# ── Operator bench ────────────────────────────────────────────────────────────
st.title("Operator / Test Bench")
tab_chat, tab_versions, tab_tenants, tab_audit = st.tabs(
    ["🤖 Test chat", "📚 Versions", "👥 Tenants", "📜 Audit log"]
)

with tab_chat:
    st.subheader("Test chat — the full pipeline, no Terraria")
    st.caption(
        "Preset character state + question → POST /bot/ask → router → agent/RAG → "
        "answer. This is the demo fallback if the live game breaks (RUNBOOK §7.1)."
    )
    left, right = st.columns(2)

    with left:
        preset_name = st.selectbox("Preset character state", list(PRESETS.keys()))
        # Switching presets starts a fresh conversation (no cross-character memory).
        if st.session_state.preset != preset_name:
            st.session_state.preset = preset_name
            st.session_state.session_id = None
            st.session_state.last_answer = None
        state = PRESETS[preset_name]

        st.dataframe(
            _preset_summary(state),
            hide_index=True,
            use_container_width=True,
        )

        message = st.text_input("Question", value="What should I do next?")
        ask_clicked = st.button("Ask", type="primary")
        # Resets the test-chat session (new session_id → no memory threading).
        # st.toast survives the rerun (an inline st.success would be wiped).
        if st.button("Reset chat"):
            st.session_state.session_id = None
            st.session_state.last_answer = None
            st.toast("Chat reset")
            st.rerun()

        with st.expander("Raw payload sent"):
            st.json(state)

    with right:
        if ask_clicked:
            try:
                with st.spinner("Routing → agent/RAG…"):
                    result = api.ask(
                        st.session_state.token,
                        message=message,
                        state=state,
                        session_id=st.session_state.session_id,
                    )
                st.session_state.session_id = result.get("session_id")
                st.session_state.last_answer = result
            except api.ApiError as exc:
                st.error(f"/bot/ask failed: {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not reach the API: {exc}")

        answer = st.session_state.last_answer
        if answer:
            with st.container(border=True):
                st.metric("routing", answer.get("routing", "?"))
                st.markdown(answer.get("answer", ""))
                st.caption(f"session_id: `{answer.get('session_id')}`")
                chunks = answer.get("source_chunks") or []
                if chunks:
                    with st.expander(f"source_chunks ({len(chunks)})"):
                        st.dataframe(
                            [
                                {
                                    "page_title": c.get("page_title"),
                                    "section": c.get("section"),
                                    "score": c.get("score"),
                                }
                                for c in chunks
                            ],
                            hide_index=True,
                            use_container_width=True,
                        )
        else:
            st.info("Pick a preset and press **Ask**.")

with tab_versions:
    # Fetched once — feeds both the re-rag selector and the table below.
    try:
        versions = api.versions()
    except Exception as exc:  # noqa: BLE001
        versions = []
        st.error(f"Could not load versions: {exc}")

    st.subheader("Re-rag — re-embed the cached corpus")
    st.caption(
        "Operator-triggered background job (D-033): re-embeds the cached corpus "
        "for a version on the worker. One at a time — a 2nd while one runs → 409. "
        "`scripts/build_corpus.py` stays the CLI fallback (ARCH §10)."
    )
    options = versions or ["1.4.4.9"]
    with st.container(border=True):
        rerag_version = st.selectbox(
            "Version to re-rag", options, key="rerag_version"
        )
        if st.button("Re-rag", type="primary"):
            try:
                result = api.rerag_start(
                    st.session_state.token, version=rerag_version
                )
                st.session_state.rerag_job_id = result.get("job_id")
                st.toast(f"Re-rag started — job {result.get('job_id')}")
            except api.ApiError as exc:
                if exc.status == 409:
                    st.warning(
                        "A re-rag is already running — only one at a time (409)."
                    )
                else:
                    st.error(f"Re-rag failed to start: {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not reach the API: {exc}")

        if st.session_state.get("rerag_job_id"):
            _rerag_status_panel()

    st.divider()
    st.subheader("Corpus versions")
    if versions:
        st.dataframe(
            [{"Version": v} for v in versions],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("No corpus versions available.")

with tab_tenants:
    st.subheader("Tenants — operator view")
    try:
        rows = api.tenants(st.session_state.token)
        st.dataframe(rows, use_container_width=True)
        st.caption(
            f"{len(rows)} tenants — cross-tenant operator read "
            "(`require_operator`, not RLS-scoped — `tenants` has no RLS, D-017)."
        )
    except api.ApiError as exc:
        st.error(f"/admin/tenants failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not reach the API: {exc}")

with tab_audit:
    st.subheader("Audit log — operator view")
    try:
        rows = api.audit_log(st.session_state.token)
        st.dataframe(rows, use_container_width=True)
        st.caption(
            f"{len(rows)} recent events — tenant.erased / auth.login / "
            "session.revoked (SECURITY §6)."
        )
    except api.ApiError as exc:
        st.error(f"/admin/audit-log failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not reach the API: {exc}")
