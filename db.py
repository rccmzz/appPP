import sqlite3
from pathlib import Path

DB_PATH = Path("tournament.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        total_points INTEGER NOT NULL DEFAULT 0,
        matches_won INTEGER NOT NULL DEFAULT 0,
        matches_played INTEGER NOT NULL DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round INTEGER NOT NULL,
        slot INTEGER NOT NULL,
        p1_id INTEGER,
        p2_id INTEGER,
        p1_score INTEGER,
        p2_score INTEGER,
        winner_id INTEGER,
        status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | DONE
        UNIQUE(round, slot),
        FOREIGN KEY(p1_id) REFERENCES players(id),
        FOREIGN KEY(p2_id) REFERENCES players(id),
        FOREIGN KEY(winner_id) REFERENCES players(id)
    );
    """)

    conn.commit()
    conn.close()

def reset_tournament(keep_players: bool = True):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM matches;")
    if not keep_players:
        cur.execute("DELETE FROM players;")
    else:
        cur.execute("UPDATE players SET total_points=0, matches_won=0, matches_played=0;")
    conn.commit()
    conn.close()

def add_players(names):
    names = [n.strip() for n in names if n and n.strip()]
    conn = get_conn()
    cur = conn.cursor()
    for n in names:
        try:
            cur.execute("INSERT INTO players(name) VALUES (?);", (n,))
        except sqlite3.IntegrityError:
            # già presente
            pass
    conn.commit()
    conn.close()

def list_players():
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("SELECT id, name, total_points, matches_won, matches_played FROM players ORDER BY name;").fetchall()
    conn.close()
    return rows

def get_player(player_id):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("SELECT id, name, total_points, matches_won, matches_played FROM players WHERE id=?;", (player_id,)).fetchone()
    conn.close()
    return row

def insert_matches(match_rows):
    """
    match_rows: list di tuple (round, slot, p1_id, p2_id)
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO matches(round, slot, p1_id, p2_id, status) VALUES (?, ?, ?, ?, 'PENDING');",
        match_rows
    )
    conn.commit()
    conn.close()

def list_matches():
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT m.id, m.round, m.slot, m.p1_id, m.p2_id, m.p1_score, m.p2_score, m.winner_id, m.status
        FROM matches m
        ORDER BY m.round, m.slot;
    """).fetchall()
    conn.close()
    return rows

def list_pending_matches():
    conn = get_conn()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT m.id, m.round, m.slot, m.p1_id, m.p2_id
        FROM matches m
        WHERE m.status='PENDING' AND m.p1_id IS NOT NULL AND m.p2_id IS NOT NULL
        ORDER BY m.round, m.slot;
    """).fetchall()
    conn.close()
    return rows

def set_match_result(match_id: int, p1_score: int, p2_score: int):
    conn = get_conn()
    cur = conn.cursor()

    m = cur.execute("""
        SELECT id, round, slot, p1_id, p2_id, status
        FROM matches WHERE id=?;
    """, (match_id,)).fetchone()

    if not m:
        conn.close()
        raise ValueError("Match non trovato.")
    if m[5] == "DONE":
        conn.close()
        raise ValueError("Match già chiuso.")
    p1_id, p2_id = m[3], m[4]
    if p1_id is None or p2_id is None:
        conn.close()
        raise ValueError("Match incompleto (bye o non assegnato).")

    if p1_score == p2_score:
        conn.close()
        raise ValueError("Nel ping pong non si pareggia: inserisci punteggi diversi.")

    winner_id = p1_id if p1_score > p2_score else p2_id

    # aggiorna match
    cur.execute("""
        UPDATE matches
        SET p1_score=?, p2_score=?, winner_id=?, status='DONE'
        WHERE id=?;
    """, (p1_score, p2_score, winner_id, match_id))

    # aggiorna player stats (punti segnati restano al giocatore)
    # -> entrambi accumulano i punti segnati nel match
    cur.execute("UPDATE players SET total_points = total_points + ?, matches_played = matches_played + 1 WHERE id=?;", (p1_score, p1_id))
    cur.execute("UPDATE players SET total_points = total_points + ?, matches_played = matches_played + 1 WHERE id=?;", (p2_score, p2_id))
    cur.execute("UPDATE players SET matches_won = matches_won + 1 WHERE id=?;", (winner_id,))

    conn.commit()
    conn.close()

def get_match(match_id: int):
    conn = get_conn()
    cur = conn.cursor()
    row = cur.execute("""
        SELECT id, round, slot, p1_id, p2_id, p1_score, p2_score, winner_id, status
        FROM matches WHERE id=?;
    """, (match_id,)).fetchone()
    conn.close()
    return row

def update_match_players(round_: int, slot: int, p1_id, p2_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE matches SET p1_id=?, p2_id=?
        WHERE round=? AND slot=?;
    """, (p1_id, p2_id, round_, slot))
    conn.commit()
    conn.close()
