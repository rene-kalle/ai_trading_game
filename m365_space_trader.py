#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Weltraum-Handelssimulation (Terminal, rundenbasiert)
- Mehrere Spieler, mehrere Orte, mehrere Güter
- Kaufen/Verkaufen an aktuellen Marktpreisen
- Jede Runde: Preise pro Ort & Gut neu (innerhalb Min/Max je Ort & Gut)
- Reisen dauert exakt 1 Runde (Ankunft zu Beginn der nächsten Runde)
- Spielstand speichern/laden (JSON) inkl. RNG-State
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pickle
import random
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional


# ============================================================
# 1) SPIEL-KONFIGURATION (hier schnell anpassbar)
# ============================================================

GOODS: List[str] = ["Wasser", "Erz", "Nahrung", "Medizin", "Elektronik"]

# Preisgrenzen pro Ort und Gut: (min, max)
# Du kannst Orte/Güter beliebig erweitern – solange jedes Gut Preisgrenzen hat.
PRICE_BOUNDS: Dict[str, Dict[str, Tuple[int, int]]] = {
    "Terra": {
        "Wasser": (8, 18),
        "Erz": (30, 70),
        "Nahrung": (12, 26),
        "Medizin": (35, 90),
        "Elektronik": (60, 140),
    },
    "Luna": {
        "Wasser": (15, 40),
        "Erz": (22, 55),
        "Nahrung": (20, 45),
        "Medizin": (28, 75),
        "Elektronik": (55, 120),
    },
    "Mars": {
        "Wasser": (25, 65),
        "Erz": (18, 45),
        "Nahrung": (22, 55),
        "Medizin": (40, 110),
        "Elektronik": (70, 180),
    },
    "Jovian Station": {
        "Wasser": (10, 28),
        "Erz": (40, 95),
        "Nahrung": (18, 40),
        "Medizin": (30, 85),
        "Elektronik": (45, 115),
    },
}

START_CASH: int = 1_000
CARGO_CAPACITY: int = 30  # maximale Einheiten im Frachtraum (Summe aller Güter)
TRAVEL_TIME_ROUNDS: int = 1  # fest 1 Runde gemäß Anforderung


# ============================================================
# 2) DATENMODELLE
# ============================================================


def _b64_pickle(obj) -> str:
    blob = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    return base64.b64encode(blob).decode("ascii")


def _unb64_pickle(s: str):
    blob = base64.b64decode(s.encode("ascii"))
    return pickle.loads(blob)


@dataclass
class Ship:
    location: str
    in_transit: bool = False
    destination: Optional[str] = None
    eta_rounds: int = 0  # verbleibende Runden bis Ankunft

    def start_travel(self, destination: str):
        self.in_transit = True
        self.destination = destination
        self.eta_rounds = TRAVEL_TIME_ROUNDS

    def tick(self):
        """Runden-Tick: reduziert ETA, setzt bei 0 auf angekommen."""
        if not self.in_transit:
            return
        self.eta_rounds -= 1
        if self.eta_rounds <= 0:
            self.location = self.destination if self.destination else self.location
            self.in_transit = False
            self.destination = None
            self.eta_rounds = 0


@dataclass
class Player:
    name: str
    cash: int
    cargo: Dict[str, int]
    ship: Ship

    def cargo_used(self) -> int:
        return sum(self.cargo.values())

    def cargo_free(self) -> int:
        return CARGO_CAPACITY - self.cargo_used()


@dataclass
class GameState:
    round_no: int
    current_player_idx: int
    players: List[Player]
    prices: Dict[str, Dict[str, int]]  # ort -> gut -> preis
    rng_state_b64: str  # random.getstate() als base64-pickle

    def rng_restore(self) -> random.Random:
        rng = random.Random()
        rng.setstate(_unb64_pickle(self.rng_state_b64))
        return rng

    def rng_store(self, rng: random.Random):
        self.rng_state_b64 = _b64_pickle(rng.getstate())


# ============================================================
# 3) PREIS-ENGINE
# ============================================================


def generate_prices(rng: random.Random) -> Dict[str, Dict[str, int]]:
    """Erzeugt neue Preise je Ort/Gut innerhalb Min/Max."""
    prices: Dict[str, Dict[str, int]] = {}
    for loc, bounds_for_loc in PRICE_BOUNDS.items():
        prices[loc] = {}
        for good in GOODS:
            mn, mx = bounds_for_loc[good]
            prices[loc][good] = rng.randint(mn, mx)
    return prices


# ============================================================
# 4) SAVE / LOAD
# ============================================================


def gamestate_to_jsonable(gs: GameState) -> dict:
    return {
        "round_no": gs.round_no,
        "current_player_idx": gs.current_player_idx,
        "prices": gs.prices,
        "rng_state_b64": gs.rng_state_b64,
        "players": [
            {
                "name": p.name,
                "cash": p.cash,
                "cargo": p.cargo,
                "ship": asdict(p.ship),
            }
            for p in gs.players
        ],
        "meta": {
            "START_CASH": START_CASH,
            "CARGO_CAPACITY": CARGO_CAPACITY,
            "TRAVEL_TIME_ROUNDS": TRAVEL_TIME_ROUNDS,
            "GOODS": GOODS,
            "LOCATIONS": list(PRICE_BOUNDS.keys()),
        },
    }


def jsonable_to_gamestate(d: dict) -> GameState:
    players: List[Player] = []
    for pd in d["players"]:
        shipd = pd["ship"]
        ship = Ship(
            location=shipd["location"],
            in_transit=shipd.get("in_transit", False),
            destination=shipd.get("destination"),
            eta_rounds=shipd.get("eta_rounds", 0),
        )
        cargo = {g: int(pd["cargo"].get(g, 0)) for g in GOODS}
        players.append(
            Player(name=pd["name"], cash=int(pd["cash"]), cargo=cargo, ship=ship)
        )

    return GameState(
        round_no=int(d["round_no"]),
        current_player_idx=int(d["current_player_idx"]),
        players=players,
        prices=d["prices"],
        rng_state_b64=d["rng_state_b64"],
    )


def save_game(gs: GameState, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(gamestate_to_jsonable(gs), f, ensure_ascii=False, indent=2)
    print(f"✅ Spiel gespeichert: {path}")


def load_game(path: str) -> GameState:
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    gs = jsonable_to_gamestate(d)
    print(f"✅ Spiel geladen: {path}")
    return gs


# ============================================================
# 5) UI / HILFSFUNKTIONEN
# ============================================================


def print_header(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_market(prices_for_loc: Dict[str, int], loc: str):
    print(f"\n📍 Marktpreise in {loc}:")
    for g in GOODS:
        print(f"  - {g:<12} {prices_for_loc[g]:>6} Credits")


def print_player_status(p: Player):
    ship = p.ship
    if ship.in_transit:
        ship_str = f"🚀 Unterwegs nach {ship.destination} (Ankunft in {ship.eta_rounds} Runde(n))"
    else:
        ship_str = f"🚀 Standort: {ship.location}"
    print(f"\n👤 Spieler: {p.name}")
    print(f"💰 Cash: {p.cash} Credits")
    print(ship_str)
    print(f"📦 Frachtraum: {p.cargo_used()}/{CARGO_CAPACITY} (frei: {p.cargo_free()})")
    if p.cargo_used() == 0:
        print("   (leer)")
    else:
        for g in GOODS:
            qty = p.cargo.get(g, 0)
            if qty:
                print(f"   - {g:<12} {qty} Einheit(en)")


def choose_int(prompt: str, min_v: int, max_v: int) -> int:
    while True:
        s = input(prompt).strip()
        try:
            v = int(s)
            if min_v <= v <= max_v:
                return v
        except ValueError:
            pass
        print(f"Bitte eine Zahl zwischen {min_v} und {max_v} eingeben.")


def choose_from_list(prompt: str, options: List[str]) -> str:
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    idx = choose_int(prompt, 1, len(options))
    return options[idx - 1]


def buy_goods(gs: GameState, p: Player):
    if p.ship.in_transit:
        print("⛔ Kaufen nicht möglich: Dein Schiff ist gerade unterwegs.")
        return

    loc = p.ship.location
    prices = gs.prices[loc]
    print_market(prices, loc)

    good = choose_from_list("\nWelches Gut kaufen? Nummer: ", GOODS)
    max_affordable = p.cash // prices[good]
    max_by_cargo = p.cargo_free()
    max_buy = min(max_affordable, max_by_cargo)

    if max_buy <= 0:
        print("⛔ Du kannst nichts kaufen (zu wenig Geld oder Frachtraum voll).")
        return

    qty = choose_int(f"Wieviel {good} kaufen? (0..{max_buy}): ", 0, max_buy)
    if qty == 0:
        print("Abgebrochen.")
        return

    cost = qty * prices[good]
    p.cash -= cost
    p.cargo[good] = p.cargo.get(good, 0) + qty
    print(f"✅ Gekauft: {qty} x {good} für {cost} Credits.")


def sell_goods(gs: GameState, p: Player):
    if p.ship.in_transit:
        print("⛔ Verkaufen nicht möglich: Dein Schiff ist gerade unterwegs.")
        return

    loc = p.ship.location
    prices = gs.prices[loc]
    print_market(prices, loc)

    sellable = [g for g in GOODS if p.cargo.get(g, 0) > 0]
    if not sellable:
        print("⛔ Du hast keine Güter an Bord.")
        return

    good = choose_from_list("\nWelches Gut verkaufen? Nummer: ", sellable)
    max_sell = p.cargo.get(good, 0)
    qty = choose_int(f"Wieviel {good} verkaufen? (0..{max_sell}): ", 0, max_sell)
    if qty == 0:
        print("Abgebrochen.")
        return

    revenue = qty * prices[good]
    p.cash += revenue
    p.cargo[good] -= qty
    if p.cargo[good] <= 0:
        p.cargo[good] = 0
    print(f"✅ Verkauft: {qty} x {good} für {revenue} Credits.")


def set_course(p: Player):
    ship = p.ship
    if ship.in_transit:
        print(
            f"⛔ Kurs setzen nicht möglich: Du bist bereits unterwegs nach {ship.destination}."
        )
        return

    locations = list(PRICE_BOUNDS.keys())
    # Ziel darf auch current location sein? meistens nicht sinnvoll -> ausschließen
    locations = [l for l in locations if l != ship.location]
    if not locations:
        print("⛔ Keine Ziele verfügbar.")
        return

    print("\n🌌 Zielort wählen:")
    dest = choose_from_list("Nummer: ", locations)
    ship.start_travel(dest)
    print(f"✅ Kurs gesetzt: Flug nach {dest}. Ankunft nächste Runde.")


def end_turn(gs: GameState):
    gs.current_player_idx = (gs.current_player_idx + 1) % len(gs.players)


def start_new_round(gs: GameState, rng: random.Random):
    """Wird aufgerufen, wenn alle Spieler ihre Züge gemacht haben."""
    gs.round_no += 1

    # Schiffe ticken (Ankünfte zu Beginn der Runde)
    for p in gs.players:
        p.ship.tick()

    # Preise neu berechnen
    gs.prices = generate_prices(rng)

    # RNG-State sichern
    gs.rng_store(rng)


def ranking(gs: GameState):
    print_header("🏁 Zwischenstand (nach Cash sortiert)")
    rows = sorted(gs.players, key=lambda p: p.cash, reverse=True)
    for i, p in enumerate(rows, start=1):
        cargo_value = 0
        if not p.ship.in_transit:
            loc = p.ship.location
            for g in GOODS:
                cargo_value += p.cargo.get(g, 0) * gs.prices[loc][g]
        print(
            f"{i:>2}. {p.name:<18} Cash: {p.cash:>6} | Cargo: {p.cargo_used():>2}/{CARGO_CAPACITY}"
        )


def ensure_config_valid():
    # Check goods
    for loc, bounds in PRICE_BOUNDS.items():
        for g in GOODS:
            if g not in bounds:
                raise ValueError(f"Ort '{loc}' hat keine Preisgrenze für Gut '{g}'.")
            mn, mx = bounds[g]
            if mn > mx:
                raise ValueError(f"Ungültige Grenzen in '{loc}' für '{g}': min>max.")


# ============================================================
# 6) GAME LOOP
# ============================================================

HELP_TEXT = """
Befehle:
  status        - zeigt deinen Status (Cash, Cargo, Schiff)
  markt         - zeigt Marktpreise am aktuellen Ort
  buy           - Güter kaufen
  sell          - Güter verkaufen
  kurs          - Kurs setzen / losfliegen (Ankunft nächste Runde)
  ende          - Zug beenden
  save <datei>  - Spiel speichern (z.B. save savegame.json)
  load <datei>  - Spiel laden
  rang          - Zwischenstand / Ranking
  clear / cls   - Bildschirm löschen
  help          - Hilfe anzeigen
  quit          - Spiel beenden (ohne automatisch zu speichern)
"""


def run_game(gs: GameState):
    rng = gs.rng_restore()

    ensure_config_valid()

    # Falls Preise fehlen (z.B. neue Runde), initial erzeugen
    if not gs.prices:
        gs.prices = generate_prices(rng)
        gs.rng_store(rng)

    print_header("🪐 Weltraum-Handelssimulation gestartet")

    # Hauptschleife
    while True:
        p = gs.players[gs.current_player_idx]

        # Rundenlogik: Wenn wir wieder beim ersten Spieler sind, beginnt neue Runde.
        # Aber nur dann, wenn der Index gerade 0 ist UND wir nicht am Spielstart "neu" sind.
        # Wir triggern neue Runde, wenn nach "ende" der letzte Spieler fertig war.
        # -> dafür merken wir uns einen Marker: am Beginn der Schleife ist es "aktueller Spieler".
        # Wir erkennen neue Runde, indem wir prüfen: current_player_idx == 0 und nicht round_start_done
        # Einfacher: Wir starten neue Runde unmittelbar nachdem der letzte Spieler seinen Zug beendet.
        # Das passiert in end_turn() nicht. Also prüfen wir nach einem Zug-Ende:
        # Wenn current_player_idx == 0, war es vorher der letzte Spieler -> neue Runde.
        #
        # Darum: Neue Runde wird direkt im "ende" Kommando ausgelöst.

        print_header(f"Runde {gs.round_no} – Spielerzug: {p.name}")
        print_player_status(p)

        while True:
            cmdline = input("\n> ").strip()
            if not cmdline:
                continue
            parts = cmdline.split()
            cmd = parts[0].lower()

            if cmd in ("help", "?"):
                print(HELP_TEXT)

            elif cmd in ("clear", "cls"):
                clear()

            elif cmd == "status":
                print_player_status(p)

            elif cmd == "markt":
                if p.ship.in_transit:
                    print(
                        "ℹ️ Du bist unterwegs. Marktpreise siehst du erst am Ziel (oder per Ranking nur grob)."
                    )
                else:
                    loc = p.ship.location
                    print_market(gs.prices[loc], loc)

            elif cmd == "buy":
                buy_goods(gs, p)

            elif cmd == "sell":
                sell_goods(gs, p)

            elif cmd == "kurs":
                set_course(p)

            elif cmd == "rang":
                ranking(gs)

            elif cmd == "save":
                if len(parts) < 2:
                    print("⛔ Nutzung: save <datei>")
                else:
                    path = parts[1]
                    # RNG-State aktualisieren, damit Save wirklich konsistent ist
                    gs.rng_store(rng)
                    save_game(gs, path)

            elif cmd == "load":
                if len(parts) < 2:
                    print("⛔ Nutzung: load <datei>")
                else:
                    path = parts[1]
                    if not os.path.exists(path):
                        print("⛔ Datei nicht gefunden.")
                    else:
                        gs = load_game(path)
                        rng = gs.rng_restore()
                        break  # zurück zum outer loop (Spieler/Anzeige neu)

            elif cmd == "quit":
                print("👋 Spiel beendet.")
                return

            elif cmd == "ende":
                # Zug beenden -> nächster Spieler
                end_turn(gs)

                # Wenn wir wieder beim Spieler 0 sind, beginnt eine neue Runde:
                if gs.current_player_idx == 0:
                    clear()
                    print_header(
                        "⏭️ Rundenwechsel: Neue Runde beginnt (Preise neu, Reisen ticken)"
                    )
                    start_new_round(gs, rng)
                    # optional: Zwischenstand nach jeder Runde
                    ranking(gs)

                break  # raus aus innerer Schleife -> nächster Spieler

            else:
                print("Unbekannter Befehl. Tipp: 'help' eingeben.")


# ============================================================
# 7) START / CLI
# ============================================================


def create_new_game_interactive(seed: Optional[int] = None) -> GameState:
    if seed is None:
        seed = random.randint(1, 10_000_000)
    rng = random.Random(seed)

    print_header("🧩 Neues Spiel erstellen")
    n = choose_int("Wie viele Spieler? (2..8): ", 2, 8)
    players: List[Player] = []
    start_loc = list(PRICE_BOUNDS.keys())[0]

    for i in range(n):
        name = (
            input(f"Name Spieler {i+1} (leer = Spieler{i+1}): ").strip()
            or f"Spieler{i+1}"
        )
        cargo = {g: 0 for g in GOODS}
        ship = Ship(location=start_loc)
        players.append(Player(name=name, cash=START_CASH, cargo=cargo, ship=ship))

    prices = generate_prices(rng)
    gs = GameState(
        round_no=1,
        current_player_idx=0,
        players=players,
        prices=prices,
        rng_state_b64=_b64_pickle(rng.getstate()),
    )
    return gs


def main():
    parser = argparse.ArgumentParser(
        description="Weltraum-Handelssimulation (Terminal)"
    )
    parser.add_argument("--load", help="Spielstand laden (JSON-Datei)")
    parser.add_argument("--seed", type=int, help="Seed für neues Spiel (optional)")
    args = parser.parse_args()

    ensure_config_valid()

    if args.load:
        gs = load_game(args.load)
    else:
        gs = create_new_game_interactive(seed=args.seed)

    print("\nTipp: 'help' zeigt alle Befehle.\n")
    run_game(gs)


def clear():
    os.system("cls" if os.name == "nt" else "clear")


if __name__ == "__main__":
    main()
