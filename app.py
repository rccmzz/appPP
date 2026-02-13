import streamlit as st
import pandas as pd
import os

from db import (
    init_db,
    add_players,
    list_players,
    list_matches,
    list_pending_matches,
    set_match_result,
    get_player,
    reset_tournament,
    get_match,
)

from bracket import (
    generate_single_elim,
    advance_winners,
    fill_round2_with_random_losers,
)

st.set_page_config(page_title="Ping Pong Tournament", layout="wide")

# --- init ---
init_db()

# --- helpers ---
def players_df():
    rows = list_players()
    df = pd.DataFrame(
        rows, columns=["id", "name", "total_points", "matches_won", "matches_played"]
    )
    df["win_rate"] = df.apply(
        lambda r: (r["matches_won"] / r["matches_played"]) if r["matches_played"] else 0.0,
        axis=1,
    )
    return df


def name_of(pid):
    if pid is None:
        return "BYE"
    p = get_player(pid)
    return p[1] if p else "?"


def bracket_dot(matches):
    """
    Restituisce una stringa DOT per st.graphviz_chart(dot).
    matches: list tuples (id, round, slot, p1_id, p2_id, p1_score, p2_score, winner_id, status)
    """
    # ✅ Filtro: non mostrare match vuoti (None vs None) che appaiono come BYE vs BYE
    matches = [m for m in matches if not (m[3] is None and m[4] is None)]

    lines = []
    lines.append("digraph G {")
    lines.append('rankdir="LR";')
    lines.append("node [shape=box];")

    # nodes
    for m in matches:
        mid, rnd, slot, p1, p2, s1, s2, win, status = m
        p1n, p2n = name_of(p1), name_of(p2)

        score_txt = ""
        if status == "DONE":
            score_txt = f"\\n{s1} - {s2}"

        label = f"R{rnd} · M{slot}\\n{p1n} vs {p2n}{score_txt}"
        label = label.replace('"', '\\"')  # sicurezza su doppi apici
        node_id = f"r{rnd}s{slot}"

        lines.append(f'{node_id} [label="{label}"];')

    # edges: from round r slot s -> round r+1 slot ceil(s/2)
    for m in matches:
        _, rnd, slot, *_ = m
        node_id = f"r{rnd}s{slot}"
        next_r = rnd + 1
        next_s = (slot + 1) // 2
        if any(mm[1] == next_r and mm[2] == next_s for mm in matches):
            lines.append(f"{node_id} -> r{next_r}s{next_s};")

    lines.append("}")
    return "\n".join(lines)


def is_admin():
    if "admin_ok" not in st.session_state:
        st.session_state.admin_ok = False

    if st.session_state.admin_ok:
        return True

    with st.sidebar:
        st.markdown("### 🔒 Admin")
        pwd = st.text_input("Password admin", type="password")
        if st.button("Login"):
            if pwd and pwd == os.getenv("ADMIN_PASSWORD", ""):
                st.session_state.admin_ok = True
                st.success("Login OK")
            else:
                st.error("Password errata")

    return st.session_state.admin_ok


# --- HEADER LOGOS (immagine unica, compatta e mobile-friendly) ---
st.markdown(
    """
    <style>
    .block-container { padding-top: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

col_img, col_space = st.columns([6, 1])
with col_img:
    st.image("assets/loghi.png", use_column_width=True)

st.markdown("---")

# --- UI ---
st.title("🏓 Torneo Ping Pong")

tab_dashboard, tab_admin = st.tabs(["📊 Dashboard", "⚙️ Admin"])

# -------------------- DASHBOARD --------------------
with tab_dashboard:
    col1, col2 = st.columns([2, 1], gap="large")

    with col1:
        st.subheader("Tabellone (albero)")
        matches = list_matches()
        if not matches:
            st.info("Nessun bracket ancora generato. Vai su Admin → Genera bracket.")
        else:
            dot = bracket_dot(matches)
            st.graphviz_chart(dot)

    with col2:
        st.subheader("Classifica")
        df = players_df().sort_values(["matches_won", "total_points"], ascending=[False, False])
        st.dataframe(
            df[["name", "matches_won", "matches_played", "win_rate", "total_points"]],
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Match in attesa")
        pending = list_pending_matches()
        if not pending:
            st.success("Nessun match in attesa (o bracket non creato).")
        else:
            pend_rows = []
            for mid, rnd, slot, p1, p2 in pending:
                pend_rows.append(
                    {
                        "match_id": mid,
                        "round": rnd,
                        "slot": slot,
                        "p1": name_of(p1),
                        "p2": name_of(p2),
                    }
                )
            st.dataframe(pd.DataFrame(pend_rows), use_container_width=True, hide_index=True)

# -------------------- ADMIN --------------------
with tab_admin:
    if not is_admin():
        st.warning("Accedi come admin dalla sidebar per gestire il torneo.")
    else:
        st.subheader("Gestione partecipanti")

        c1, c2 = st.columns(2, gap="large")

        with c1:
            st.markdown("**Aggiungi a mano** (uno per riga)")
            names_text = st.text_area(
                "Nomi", placeholder="Mario Rossi\nLuigi Bianchi\n...", height=140
            )
            if st.button("➕ Aggiungi nomi"):
                add_players(names_text.splitlines())
                st.success("Partecipanti aggiornati.")

        with c2:
            st.markdown("**Import da CSV/TXT**")
            up = st.file_uploader("Carica un file", type=["csv", "txt"])
            st.caption("CSV: una colonna 'name' (oppure prima colonna). TXT: un nome per riga.")
            if up is not None:
                content = up.getvalue().decode("utf-8", errors="replace")
                names = []
                if up.name.lower().endswith(".txt"):
                    names = [ln.strip() for ln in content.splitlines() if ln.strip()]
                else:
                    dfu = pd.read_csv(pd.io.common.StringIO(content))
                    if "name" in dfu.columns:
                        names = dfu["name"].astype(str).tolist()
                    else:
                        names = dfu.iloc[:, 0].astype(str).tolist()

                if st.button("📥 Importa partecipanti"):
                    add_players(names)
                    st.success(f"Importati/aggiornati: {len(names)}")

        st.divider()

        # ---- BRACKET SECTION ----
        st.subheader("Bracket")
        players = list_players()
        st.write(f"Partecipanti totali: **{len(players)}**")

        if st.button("🧩 Genera bracket (single-elimination)"):
            reset_tournament(keep_players=True)
            ids = [p[0] for p in players]
            generate_single_elim(ids)
            advance_winners()
            st.success("Bracket generato. (BYE avanzati automaticamente se necessario)")

        # ✅ Pulsante ripescaggio Round 2 nel punto giusto
        if st.button("🎲 Ripescaggio casuale Round 2 (riempi buchi)"):
            filled = fill_round2_with_random_losers()
            if filled > 0:
                advance_winners()
                st.success(f"Ripescaggi inseriti: {filled}")
            else:
                st.info("Nessun buco da riempire in Round 2 o nessun perdente disponibile.")

        st.divider()

        # ---- SCORE INPUT SECTION ----
        st.subheader("Inserisci risultato match")
        pending = list_pending_matches()

        if not pending:
            st.info("Nessun match disponibile per inserire punteggi.")
        else:
            options = []
            for mid, rnd, slot, p1, p2 in pending:
                options.append(
                    (mid, f"Match {mid} — R{rnd} M{slot}: {name_of(p1)} vs {name_of(p2)}")
                )

            selected = st.selectbox("Seleziona match", options, format_func=lambda x: x[1])
            match_id = selected[0]
            m = get_match(match_id)

            st.markdown(f"**{name_of(m[3])} vs {name_of(m[4])}**")

            s1 = st.number_input(
                f"Punti {name_of(m[3])}", min_value=0, max_value=99, value=11, step=1
            )
            s2 = st.number_input(
                f"Punti {name_of(m[4])}", min_value=0, max_value=99, value=7, step=1
            )

            if st.button("✅ Salva risultato"):
                try:
                    set_match_result(match_id, int(s1), int(s2))

                    # 1) Avanza i winner
                    advance_winners()

                    # 2) Ripescaggio casuale Round 2 (se serve)
                    filled = fill_round2_with_random_losers()

                    # 3) Ricalcola avanzamenti dopo ripescaggio
                    if filled > 0:
                        advance_winners()

                    st.success(f"Risultato salvato. Ripescaggi inseriti: {filled}")
                except Exception as e:
                    st.error(str(e))

        st.divider()

        # ---- DANGEROUS ACTIONS ----
        st.subheader("Azioni pericolose")
        colA, colB = st.columns(2)

        with colA:
            if st.button("♻️ Reset match (mantieni partecipanti)"):
                reset_tournament(keep_players=True)
                st.warning("Match resettati. Partecipanti mantenuti.")

        with colB:
            if st.button("🧨 Reset totale (cancella anche partecipanti)"):
                reset_tournament(keep_players=False)
                st.error("Reset totale completato.")
