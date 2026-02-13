import math
from typing import List, Tuple, Optional
from db import insert_matches, list_matches, get_conn, update_match_players

def next_power_of_two(n: int) -> int:
    return 1 if n <= 1 else 2 ** math.ceil(math.log2(n))

def generate_single_elim(players_ids):
    n = len(players_ids)
    if n < 2:
        raise ValueError("Servono almeno 2 partecipanti.")

    size = next_power_of_two(n)
    rounds = int(math.log2(size))

    # Qui NON padding con None a tappeto
    padded = players_ids[:] + [None] * (size - n)

    match_rows = []

    # ROUND 1: crea SOLO match che hanno almeno 1 giocatore reale
    slot = 1
    for i in range(0, size, 2):
        p1 = padded[i]
        p2 = padded[i + 1]

        # skip match vuoti (BYE vs BYE)
        if p1 is None and p2 is None:
            continue

        match_rows.append((1, slot, p1, p2))
        slot += 1

    # Round successivi: crea tutti gli slot necessari
    for r in range(2, rounds + 1):
        slots = size // (2 ** r)
        for s in range(1, slots + 1):
            match_rows.append((r, s, None, None))

    insert_matches(match_rows)
    auto_advance_byes()


def auto_advance_byes():
    """
    Se in round 1 ci sono match con un giocatore None (BYE),
    avanza automaticamente il player presente al round successivo.
    """
    conn = get_conn()
    cur = conn.cursor()

    # prendi tutti i match del round 1
    r1 = cur.execute("""
        SELECT id, slot, p1_id, p2_id, status
        FROM matches
        WHERE round=1
        ORDER BY slot;
    """).fetchall()

    for match_id, slot, p1_id, p2_id, status in r1:
        if status == "DONE":
            continue
        if p1_id is None and p2_id is None:
            continue
        if (p1_id is None) ^ (p2_id is None):
            winner_id = p1_id if p1_id is not None else p2_id
            # segna match come DONE con 0-0 (bye)
            cur.execute("""
                UPDATE matches
                SET p1_score=0, p2_score=0, winner_id=?, status='DONE'
                WHERE id=?;
            """, (winner_id, match_id))

            # Avanza al round 2: slot_adv = ceil(slot/2), posizione p1/p2 in base a slot dispari/pari
            adv_round = 2
            adv_slot = (slot + 1) // 2
            place_as_p1 = (slot % 2 == 1)

            # leggi match del round successivo
            m2 = cur.execute("SELECT p1_id, p2_id FROM matches WHERE round=? AND slot=?;", (adv_round, adv_slot)).fetchone()
            if m2:
                new_p1, new_p2 = m2
                if place_as_p1:
                    new_p1 = winner_id
                else:
                    new_p2 = winner_id
                cur.execute("UPDATE matches SET p1_id=?, p2_id=? WHERE round=? AND slot=?;", (new_p1, new_p2, adv_round, adv_slot))

    conn.commit()
    conn.close()

def advance_winners():
    """
    Dopo che alcuni match sono stati chiusi, porta i winner al round successivo.
    Si può chiamare ogni volta: è idempotente (riscrive gli slot con stessi valori).
    """
    matches = list_matches()
    # m: (id, round, slot, p1_id, p2_id, p1_score, p2_score, winner_id, status)

    # indicizza per round/slot
    by_round = {}
    for m in matches:
        by_round.setdefault(m[1], []).append(m)

    max_round = max(by_round.keys()) if by_round else 1

    for r in range(1, max_round):
        current = sorted(by_round.get(r, []), key=lambda x: x[2])
        # winners in slot order
        winners = []
        for m in current:
            if m[8] == "DONE" and m[7] is not None:
                winners.append(m[7])
            else:
                winners.append(None)

        # feed into next round matches
        next_round = r + 1
        slots = len(by_round.get(next_round, []))
        for s in range(1, slots + 1):
            w1 = winners[2 * (s - 1)] if 2 * (s - 1) < len(winners) else None
            w2 = winners[2 * (s - 1) + 1] if 2 * (s - 1) + 1 < len(winners) else None
            update_match_players(next_round, s, w1, w2)

import random
from db import get_conn

def fill_round2_with_random_losers(seed: int | None = None):
    """
    Ripescaggio casuale: se nel Round 2 ci sono match con un solo giocatore (l'altro None),
    pesca casualmente tra i perdenti del Round 1 e riempie gli slot mancanti.

    - Non riusa lo stesso perdente due volte
    - Se i perdenti non bastano, lascia i rimanenti slot vuoti
    """
    rng = random.Random(seed)

    conn = get_conn()
    cur = conn.cursor()

    # 1) perdenti Round 1 (match DONE, entrambi presenti)
    # loser = (p1 se winner è p2) o (p2 se winner è p1)
    losers = cur.execute("""
        SELECT
            CASE
                WHEN winner_id = p1_id THEN p2_id
                WHEN winner_id = p2_id THEN p1_id
                ELSE NULL
            END AS loser_id
        FROM matches
        WHERE round = 1
          AND status = 'DONE'
          AND p1_id IS NOT NULL
          AND p2_id IS NOT NULL
          AND winner_id IS NOT NULL;
    """).fetchall()

    loser_ids = [r[0] for r in losers if r[0] is not None]

    # rimuovi duplicati mantenendo ordine "casuale" dopo shuffle
    rng.shuffle(loser_ids)

    # 2) match Round 2 con un buco (uno NULL e l'altro no) e ancora PENDING
    open_r2 = cur.execute("""
        SELECT id, slot, p1_id, p2_id
        FROM matches
        WHERE round = 2
          AND status = 'PENDING'
          AND (
              (p1_id IS NULL AND p2_id IS NOT NULL)
              OR
              (p2_id IS NULL AND p1_id IS NOT NULL)
          )
        ORDER BY slot;
    """).fetchall()

    if not open_r2 or not loser_ids:
        conn.close()
        return 0

    filled = 0
    used = set()

    for match_id, slot, p1_id, p2_id in open_r2:
        # pesca un perdente non usato
        pick = None
        while loser_ids:
            candidate = loser_ids.pop()
            if candidate not in used:
                pick = candidate
                used.add(candidate)
                break

        if pick is None:
            break  # finiti i perdenti disponibili

        if p1_id is None:
            cur.execute("UPDATE matches SET p1_id=? WHERE id=?;", (pick, match_id))
        else:
            cur.execute("UPDATE matches SET p2_id=? WHERE id=?;", (pick, match_id))

        filled += 1

    conn.commit()
    conn.close()
    return filled
