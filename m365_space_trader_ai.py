#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Weltraum-Handelssimulation (Terminal, rundenbasiert)
- Mehrere menschliche Spieler + AI-Spieler
- Mehrere Orte, mehrere Güter
- Kaufen/Verkaufen an aktuellen Marktpreisen
- Jede Runde: Preise pro Ort & Gut neu (innerhalb Min/Max je Ort & Gut)
- Reisen dauert exakt 1 Runde (Ankunft zu Beginn der nächsten Runde)
- Spielstand speichern/laden (JSON) inkl. RNG-State
- AI-Spieler: einfache Handelsstrategie (History-basierte Erwartung)
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
CARGO_CAPACITY: int = 30  # max. Einheiten im Frachtraum (Summe aller Güter)
TRAVEL_TIME_ROUNDS: int = 1  # fest 1 Runde gemäß Anforderung

# AI-Strategie (einfach, aber solide)
AI_SELL_MARGIN: float = 0.05  # Verkauf nur, wenn Preis >= Einstand * (1+Margin)
AI_MIN_EXPECTED_PROFIT: int = 1  # erwarteter Gewinn pro Einheit muss >= sein
AI_RANDOMNESS: float = 0.10  # kleine Zufallskomponente zur Tie-Break/Varianz

AI_NAME_POOL = [
    "Nova",
    "Orion",
    "Vega",
    "Lyra",
    "Astra",
    "Kepler",
    "Sagan",
    "Pulsar",
    "Quasar",
    "Nebula",
    "Andromeda",
    "Altair",
    "Sirius",
    "Rigel",
    "Polaris",
    "Cosmo",
    "Stellar",
    "Zenith",
    "Eclipse",
    "Helios",
    "Lumen",
    "Draco",
]


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
    is_ai: bool = False
    # Kostenbasis pro Gut: Summe der ausgegebenen Credits für aktuell gehaltene Menge
    cost_basis: Dict[str, int] = None  # type: ignore
    # gesamter Reichtum = cash + (Summe aller Güter * aktuelle Preise) -> für AI-Entscheidungen relevant
    total_wealth: int = 0

    def __post_init__(self):
        self.total_wealth = (
            self.cash
        )  # initial nur Cash, wird in AI-Entscheidungen aktualisiert
        if self.cost_basis is None:
            self.cost_basis = {g: 0 for g in GOODS}
        else:
            for g in GOODS:
                self.cost_basis.setdefault(g, 0)

    def cargo_used(self) -> int:
        return sum(self.cargo.values())

    def cargo_free(self) -> int:
        return CARGO_CAPACITY - self.cargo_used()

    def avg_cost(self, good: str) -> float:
        qty = self.cargo.get(good, 0)
        if qty <= 0:
            return 0.0
        return self.cost_basis.get(good, 0) / float(qty)

    def update_total_wealth(self, prices: Dict[str, Dict[str, int]]):
        loc = self.ship.location
        self.total_wealth = self.cash + sum(
            self.cargo[g] * prices[loc][g] for g in GOODS
        )


@dataclass
class GameState:
    round_no: int
    current_player_idx: int
    players: List[Player]
    prices: Dict[str, Dict[str, int]]  # ort -> gut -> preis
    rng_state_b64: str  # random.getstate() als base64-pickle
    # Preis-Statistik pro Ort/Gut: sum, count -> Erwartungswert für AI
    price_stats: Dict[
        str, Dict[str, Dict[str, int]]
    ]  # loc -> good -> {"sum":..,"count":..}

    def rng_restore(self) -> random.Random:
        rng = random.Random()
        rng.setstate(_unb64_pickle(self.rng_state_b64))
        return rng

    def rng_store(self, rng: random.Random):
        self.rng_state_b64 = _b64_pickle(rng.getstate())


# ============================================================
# 3) PREIS-ENGINE + HISTORY
# ============================================================


def ensure_config_valid():
    for loc, bounds in PRICE_BOUNDS.items():
        for g in GOODS:
            if g not in bounds:
                raise ValueError(f"Ort '{loc}' hat keine Preisgrenze für Gut '{g}'.")
            mn, mx = bounds[g]
            if mn > mx:
                raise ValueError(f"Ungültige Grenzen in '{loc}' für '{g}': min>max.")


def init_price_stats() -> Dict[str, Dict[str, Dict[str, int]]]:
    stats: Dict[str, Dict[str, Dict[str, int]]] = {}
    for loc in PRICE_BOUNDS.keys():
        stats[loc] = {}
        for g in GOODS:
            stats[loc][g] = {"sum": 0, "count": 0}
    return stats


def update_price_stats(
    stats: Dict[str, Dict[str, Dict[str, int]]], prices: Dict[str, Dict[str, int]]
):
    for loc in prices:
        for g in prices[loc]:
            stats[loc][g]["sum"] += int(prices[loc][g])
            stats[loc][g]["count"] += 1


def expected_price(
    stats: Dict[str, Dict[str, Dict[str, int]]], loc: str, good: str, fallback: int
) -> float:
    c = stats[loc][good]["count"]
    if c <= 0:
        return float(fallback)
    return stats[loc][good]["sum"] / float(c)


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
        "price_stats": gs.price_stats,
        "players": [
            {
                "name": p.name,
                "cash": p.cash,
                "cargo": p.cargo,
                "ship": asdict(p.ship),
                "is_ai": p.is_ai,
                "cost_basis": p.cost_basis,
                "total_wealth": p.total_wealth,
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
        cost_basis = {g: int(pd.get("cost_basis", {}).get(g, 0)) for g in GOODS}
        players.append(
            Player(
                name=pd["name"],
                cash=int(pd["cash"]),
                cargo=cargo,
                ship=ship,
                is_ai=bool(pd.get("is_ai", False)),
                cost_basis=cost_basis,
                total_wealth=int(pd.get("total_wealth", 0)),
            )
        )

    stats = d.get("price_stats") or init_price_stats()

    return GameState(
        round_no=int(d["round_no"]),
        current_player_idx=int(d["current_player_idx"]),
        players=players,
        prices=d["prices"],
        rng_state_b64=d["rng_state_b64"],
        price_stats=stats,
    )


def save_game(gs: GameState, path: str):
    # Sicherstellen, dass Dateiendung .save hat (optional)
    if not path.lower().endswith(".save"):
        path += ".save"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(gamestate_to_jsonable(gs), f, ensure_ascii=False, indent=2)
    print(f"✅ Spiel gespeichert: {path}")


def load_game(path: str) -> GameState:
    # Sicherstellen, dass Dateiendung .save hat (optional)
    if not path.lower().endswith(".save"):
        path += ".save"
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    gs = jsonable_to_gamestate(d)
    print(f"✅ Spiel geladen: {path}")
    return gs


# ============================================================
# 5) UI / HILFSFUNKTIONEN (Mensch)
# ============================================================


def print_header(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_market(prices_for_loc: Dict[str, int], loc: str):
    print(f"\n📍 Marktpreise in {loc}:")
    for g in GOODS:
        print(f"  - {g:<12} {prices_for_loc[g]:>4} Credits")


def print_player_status(p: Player):
    ship = p.ship
    tag = "🤖 AI" if p.is_ai else "👤 Mensch"
    if ship.in_transit:
        ship_str = f"🚀 Unterwegs nach {ship.destination} (Ankunft in {ship.eta_rounds} Runde(n))"
    else:
        ship_str = f"🚀 Standort: {ship.location}"
    print(f"\n{tag} Spieler: {p.name}")
    print(f"💰 Cash: {p.cash:,} Credits")
    print(f"💰 Gesamter Reichtum: {p.total_wealth:,} Credits")
    print(ship_str)
    print(f"📦 Frachtraum: {p.cargo_used()}/{CARGO_CAPACITY} (frei: {p.cargo_free()})")
    if p.cargo_used() == 0:
        print("   (leer)")
    else:
        for g in GOODS:
            qty = p.cargo.get(g, 0)
            if qty:
                avg = p.avg_cost(g)
                print(f"   - {g:<12} {qty:>2} Einheit(en) | Ø Einstand: {avg:.2f}")


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
    # Kaufe: Cash reduzieren, Cargo erhöhen, Kostenbasis aktualisieren, Gesamtwert aktualisieren
    p.cash -= cost
    p.cargo[good] = p.cargo.get(good, 0) + qty
    p.cost_basis[good] = p.cost_basis.get(good, 0) + cost
    print(f"✅ Gekauft: {qty} x {good} für {cost} Credits.")
    p.total_wealth = p.cash + sum(p.cargo[g] * gs.prices[loc][g] for g in GOODS)


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
    # Kostenbasis proportional reduzieren (durchschnittlicher Einstand)
    avg = p.avg_cost(good)
    reduce_cost = int(round(avg * qty))

    # Verkaufen: Cash erhöhen, Cargo reduzieren, Kostenbasis aktualisieren, Gesamtwert aktualisieren
    p.cash += revenue
    p.cargo[good] -= qty
    p.cost_basis[good] = max(0, p.cost_basis.get(good, 0) - reduce_cost)
    p.total_wealth = p.cash + sum(p.cargo[g] * gs.prices[loc][g] for g in GOODS)

    if p.cargo[good] <= 0:
        p.cargo[good] = 0
        p.cost_basis[good] = 0

    print(f"✅ Verkauft: {qty} x {good} für {revenue} Credits.")


def set_course(p: Player):
    ship = p.ship
    if ship.in_transit:
        print(
            f"⛔ Kurs setzen nicht möglich: Du bist bereits unterwegs nach {ship.destination}."
        )
        return

    locations = list(PRICE_BOUNDS.keys())
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
    """Neue Runde: Ankünfte, neue Preise, History-Update."""
    gs.round_no += 1

    # Schiffe ticken (Ankünfte zu Beginn der Runde)
    for p in gs.players:
        p.ship.tick()

    # Preise neu berechnen
    gs.prices = generate_prices(rng)

    # Preis-Stats updaten (für AI-Erwartung)
    update_price_stats(gs.price_stats, gs.prices)

    # RNG-State sichern
    gs.rng_store(rng)


def ranking(gs: GameState):
    # Reichtum für alle Spieler aktualisieren (für AI-Entscheidungen und Anzeige)
    for p in gs.players:
        p.update_total_wealth(gs.prices)
    print_header("🏁 Zwischenstand (nach Reichtum sortiert)")
    rows = sorted(gs.players, key=lambda p: p.total_wealth, reverse=True)
    for i, p in enumerate(rows, start=1):
        tag = "🤖" if p.is_ai else "👤"
        print(
            f"{i:>2}. {tag} {p.name:<18} Reichtum: {p.total_wealth:>9,} | Cash: {p.cash:>9,} | Cargo: {p.cargo_used():>2}/{CARGO_CAPACITY}"
        )


# ============================================================
# 6) AI-LOGIK
# ============================================================


def ai_take_turn(gs: GameState, p: Player, rng: random.Random):
    """Einfacher AI-Zug:
    1) Wenn unterwegs: nichts tun
    2) Wenn angekommen: profitable Güter am Standort verkaufen
    3) Beste erwartete Arbitrage suchen (History-basierte Erwartung am Ziel), kaufen, fliegen
    """
    print_header(f"🤖 AI-Zug: {p.name}")

    # Unterwegs? -> Zug sofort beenden
    if p.ship.in_transit:
        print(
            f"{p.name} ist unterwegs nach {p.ship.destination} (ETA {p.ship.eta_rounds}). -> Ende."
        )
        return

    loc = p.ship.location
    prices_here = gs.prices[loc]
    print_player_status(p)
    print_market(prices_here, loc)

    # 1) Profitable Verkäufe am aktuellen Ort
    sold_any = False
    for g in GOODS:
        qty = p.cargo.get(g, 0)
        if qty <= 0:
            continue
        avg = p.avg_cost(g)
        cur = prices_here[g]
        # Verkauf, wenn Profitmarge erreicht
        if avg > 0 and cur >= avg * (1.0 + AI_SELL_MARGIN):
            revenue = qty * cur
            reduce_cost = int(round(avg * qty))
            p.cash += revenue
            p.cargo[g] = 0
            p.cost_basis[g] = 0
            sold_any = True
            print(
                f"🤖 {p.name} verkauft {qty} x {g} @ {cur} (Ø Einstand {avg:.2f}) -> +{revenue} Credits"
            )

    if sold_any:
        print(f"🤖 {p.name} hat verkauft. Cash jetzt: {p.cash}")

    # 2) Beste erwartete Trade-Option wählen
    best = None  # (score, dest, good, buy_price, expected_sell)
    for dest in PRICE_BOUNDS.keys():
        if dest == loc:
            continue
        for g in GOODS:
            buy_price = prices_here[g]
            exp_sell = expected_price(
                gs.price_stats, dest, g, fallback=gs.prices[dest][g]
            )
            profit = exp_sell - buy_price

            # kleine Zufallskomponente um Gleichstände zu lösen/Varianz zu geben
            profit = profit * (1.0 + rng.uniform(-AI_RANDOMNESS, AI_RANDOMNESS))

            if profit >= AI_MIN_EXPECTED_PROFIT:
                score = profit  # profit pro Einheit
                if best is None or score > best[0]:
                    best = (score, dest, g, buy_price, exp_sell)

    if best is None:
        # Wenn keine positive Erwartung: optional umziehen zu "interessantem" Ort (z.B. zufällig)
        # Hier: mit kleiner Chance reisen, sonst warten.
        if rng.random() < 0.40:
            choices = [l for l in PRICE_BOUNDS.keys() if l != loc]
            dest = rng.choice(choices)
            p.ship.start_travel(dest)
            print(
                f"🤖 {p.name} findet keinen klaren Deal und fliegt auf Verdacht nach {dest}."
            )
        else:
            print(f"🤖 {p.name} findet keinen klaren Deal und bleibt in {loc}.")
        return

    _, dest, good, buy_price, exp_sell = best
    max_affordable = p.cash // buy_price
    max_by_cargo = p.cargo_free()
    qty = min(max_affordable, max_by_cargo)

    if qty <= 0:
        # nichts kaufbar -> evtl. trotzdem reisen
        p.ship.start_travel(dest)
        print(
            f"🤖 {p.name} will {good} handeln, hat aber kein Budget/Frachtraum. Fliegt trotzdem nach {dest}."
        )
        return

    # Kaufen
    cost = qty * buy_price
    p.cash -= cost
    p.cargo[good] = p.cargo.get(good, 0) + qty
    p.cost_basis[good] = p.cost_basis.get(good, 0) + cost

    print(
        f"🤖 {p.name} kauft {qty} x {good} @ {buy_price} (Erwartung Ziel {dest}: ~{exp_sell:.1f}) -> -{cost} Credits"
    )

    # Reisen
    p.ship.start_travel(dest)
    print(f"🤖 {p.name} setzt Kurs nach {dest}. Ankunft nächste Runde.")


# ============================================================
# 7) GAME LOOP
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
  help          - Hilfe anzeigen
  quit          - Spiel beenden (ohne automatisch zu speichern)
"""


def run_game(gs: GameState):
    rng = gs.rng_restore()
    ensure_config_valid()

    # Falls Preise fehlen: initial erzeugen + stats initialisieren
    if not gs.prices:
        gs.prices = generate_prices(rng)
    if not gs.price_stats:
        gs.price_stats = init_price_stats()

    # History mit Startpreisen füttern
    update_price_stats(gs.price_stats, gs.prices)
    gs.rng_store(rng)

    print_header("🪐 Weltraum-Handelssimulation gestartet")
    print("\nTipp: 'help' zeigt alle Befehle.\n")

    while True:
        p = gs.players[gs.current_player_idx]

        # AI-Spieler spielen automatisch
        if p.is_ai:
            ai_take_turn(gs, p, rng)
            # abwarten
            input("Drücke Enter, um fortzufahren...")
            gs.rng_store(rng)
            end_turn(gs)

            # Rundenwechsel, wenn wir wieder bei Spieler 0 sind
            if gs.current_player_idx == 0:
                print_header(
                    "⏭️ Rundenwechsel: Neue Runde beginnt (Preise neu, Reisen ticken)"
                )
                start_new_round(gs, rng)
                ranking(gs)
            continue

        # Menschlicher Spieler
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

            elif cmd == "status":
                print_player_status(p)

            elif cmd == "markt":
                if p.ship.in_transit:
                    print("ℹ️ Du bist unterwegs. Marktpreise siehst du erst am Ziel.")
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
                    gs.rng_store(rng)
                    save_game(gs, path)

            elif cmd == "load":
                if len(parts) < 2:
                    print("⛔ Nutzung: load <datei>")
                else:
                    path = parts[1]
                    # Sicherstellen, dass Dateiendung .save hat (optional)
                    if not path.lower().endswith(".save"):
                        path += ".save"
                    if not os.path.exists(path):
                        print("⛔ Datei nicht gefunden.")
                    else:
                        gs = load_game(path)
                        rng = gs.rng_restore()
                        break  # zurück zum outer loop

            elif cmd in ("quit", "exit"):
                print("👋 Spiel beendet.")
                return

            elif cmd == "ende":
                gs.rng_store(rng)
                end_turn(gs)

                if gs.current_player_idx == 0:
                    print_header(
                        "⏭️ Rundenwechsel: Neue Runde beginnt (Preise neu, Reisen ticken)"
                    )
                    start_new_round(gs, rng)
                    ranking(gs)

                break

            else:
                print("Unbekannter Befehl. Tipp: 'help' eingeben.")


# ============================================================
# 8) START / CLI + NEUES SPIEL MIT HUMAN + AI
# ============================================================


def make_unique_ai_names(count: int, rng: random.Random) -> List[str]:
    pool = AI_NAME_POOL[:]
    rng.shuffle(pool)
    names: List[str] = []
    i = 0
    while len(names) < count:
        base = pool[i % len(pool)]
        # falls mehr AI als Pool: nummerieren
        suffix = (i // len(pool)) + 1
        name = base if suffix == 1 and base not in names else f"{base}-{suffix}"
        if name not in names:
            names.append(name)
        i += 1
    return names


def create_new_game_interactive(seed: Optional[int] = None) -> GameState:
    if seed is None:
        seed = random.randint(1, 10_000_000)
    rng = random.Random(seed)

    print_header("🧩 Neues Spiel erstellen")
    human_n = choose_int("Wie viele MENSCHLICHE Spieler? (1..8): ", 1, 8)
    ai_n = choose_int("Wie viele AI-Spieler? (0..8): ", 0, 8)

    # optionales Gesamtlimit (damit es im Terminal nicht ausufert)
    total = human_n + ai_n
    if total > 12:
        print("ℹ️ Hinweis: Sehr viele Spieler. Ich setze das Maximum auf 12.")
        ai_n = max(0, 12 - human_n)

    players: List[Player] = []
    start_loc = list(PRICE_BOUNDS.keys())[0]

    # Menschen
    for i in range(human_n):
        name = (
            input(f"Name Spieler {i+1} (leer = Spieler{i+1}): ").strip()
            or f"Spieler{i+1}"
        )
        cargo = {g: 0 for g in GOODS}
        ship = Ship(location=start_loc)
        players.append(
            Player(name=name, cash=START_CASH, cargo=cargo, ship=ship, is_ai=False)
        )

    # AI
    ai_names = make_unique_ai_names(ai_n, rng)
    for name in ai_names:
        cargo = {g: 0 for g in GOODS}
        ship = Ship(location=start_loc)
        players.append(
            Player(name=name, cash=START_CASH, cargo=cargo, ship=ship, is_ai=True)
        )

    prices = generate_prices(rng)
    stats = init_price_stats()
    update_price_stats(stats, prices)

    gs = GameState(
        round_no=1,
        current_player_idx=0,
        players=players,
        prices=prices,
        rng_state_b64=_b64_pickle(rng.getstate()),
        price_stats=stats,
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

    run_game(gs)


def clear():
    os.system("cls" if os.name == "nt" else "clear")


if __name__ == "__main__":
    clear()
    main()
