#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Weltraum-Handelssimulation (Terminal, rundenbasiert)
- Mehrere menschliche Spieler + AI-Spieler
- Mehrere Orte, mehrere Güter
- Kaufen/Verkaufen an aktuellen Marktpreisen
- Jede Runde: Preise pro Ort & Gut neu (innerhalb Min/Max je Ort & Gut)
- Reisen dauert unterschiedlich lange (1-4 Runden) je nach Ziel
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
from typing import Any, Dict, List, Tuple, Optional


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
AI_CARGO_CAPACITY: int = 50  # AI-Spieler: größerer Frachtraum
# Travel durations (in rounds) between location pairs
TRAVEL_DURATIONS: Dict[Tuple[str, str], int] = {
    ("Terra", "Luna"): 1,
    ("Luna", "Terra"): 1,
    ("Terra", "Mars"): 3,
    ("Mars", "Terra"): 3,
    ("Terra", "Jovian Station"): 4,
    ("Jovian Station", "Terra"): 4,
    ("Luna", "Mars"): 2,
    ("Mars", "Luna"): 2,
    ("Luna", "Jovian Station"): 3,
    ("Jovian Station", "Luna"): 3,
    ("Mars", "Jovian Station"): 2,
    ("Jovian Station", "Mars"): 2,
}
# Cargo-Erweiterung
CARGO_EXTENSION_COST: int = 500  # Credits pro Erweiterung
CARGO_EXTENSION_AMOUNT: int = 10  # zusätzliche Einheiten pro Erweiterung
MAX_CARGO_EXTENSIONS: int = 5  # max. Anzahl Erweiterungen
# AI-Strategie (einfach, aber solide)
AI_SELL_MARGIN: float = 0.05  # Verkauf nur, wenn Preis >= Einstand * (1+Margin)
AI_MIN_EXPECTED_PROFIT: int = 1  # erwarteter Gewinn pro Einheit muss >= sein
AI_RANDOMNESS: float = 0.10  # kleine Zufallskomponente zur Tie-Break/Varianz

# Events
PIRATE_ATTACK_PROBABILITY: float = 0.10  # 10% Chance für Piratenüberfall bei Ankunft
PIRATE_CARGO_LOSS: float = 0.50  # Piraten stehlen 50% der Güter
SUN_FLARE_PROBABILITY: float = 0.05  # 5% Chance für Sonnensturm bei Ankunft

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
    """Serialize a Python object to a base64-encoded ASCII string.

    Converts any Python object into a compact, safe string representation suitable
    for JSON serialization. Uses pickle for serialization and base64 encoding to
    ensure the result is JSON-compatible.

    This is primarily used to preserve the random number generator state in save
    files. The RNG state is a complex Python object that cannot be directly
    serialized to JSON, so we pickle it and encode it as base64.

    Args:
        obj: Any Python object that can be pickled (most standard types are supported).
             Commonly used with: random.Random().getstate(), dict, list, etc.

    Returns:
        str: Base64-encoded ASCII string representation of the pickled object.
             Safe for inclusion in JSON files.

    Example:
        >>> import random
        >>> rng = random.Random(42)
        >>> encoded = _b64_pickle(rng.getstate())
        >>> isinstance(encoded, str)
        True
        >>> len(encoded) > 0
        True

    See Also:
        _unb64_pickle: Reverses this operation to recover the original object.
    """
    blob = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    return base64.b64encode(blob).decode("ascii")


def _unb64_pickle(s: str) -> Any:
    """Deserialize a Python object from a base64-encoded ASCII string.

    Reverses the operation performed by _b64_pickle(). Converts a base64-encoded
    string back into the original Python object using pickle deserialization.

    This function is used to restore the random number generator state from
    saved game files, ensuring that games can be replayed deterministically
    with the exact same price sequences.

    Args:
        s (str): A base64-encoded ASCII string produced by _b64_pickle().

    Returns:
        Any: The original Python object that was encoded.

    Raises:
        binascii.Error: If the input string is not valid base64.
        pickle.UnpicklingError: If the decoded bytes are not valid pickle data.

    Example:
        >>> import random
        >>> rng = random.Random(42)
        >>> state = rng.getstate()
        >>> encoded = _b64_pickle(state)
        >>> recovered_state = _unb64_pickle(encoded)
        >>> state == recovered_state
        True

    See Also:
        _b64_pickle: Encodes a Python object to base64 for storage.
    """
    blob = base64.b64decode(s.encode("ascii"))
    return pickle.loads(blob)


@dataclass
class Ship:
    """Represents a merchant vessel in space.

    Tracks the ship's current location, transit status, and estimated arrival time.
    Supports travel between locations with multi-round transit times.

    Attributes:
        location (str): Current location (e.g., 'Terra', 'Luna', 'Mars', 'Jovian Station').
        in_transit (bool): Whether the ship is currently traveling. Defaults to False.
        destination (Optional[str]): Target location when in transit. None if stationary.
        eta_rounds (int): Rounds remaining until arrival. 0 if not in transit.
    """

    location: str
    in_transit: bool = False
    destination: Optional[str] = None
    eta_rounds: int = 0  # verbleibende Runden bis Ankunft

    def start_travel(self, destination: str, current_location: str) -> None:
        """Initiate travel to a destination.

        Sets the ship to in-transit mode with variable travel time based on the
        distance between current location and destination. Travel time is determined
        by the TRAVEL_DURATIONS configuration.

        Args:
            destination (str): Name of the destination location.
            current_location (str): Current location (starting point for travel).

        Raises:
            ValueError: If travel route is not in TRAVEL_DURATIONS configuration.
        """
        route = (current_location, destination)
        if route not in TRAVEL_DURATIONS:
            raise ValueError(f"Unknown travel route: {route}")

        travel_time = TRAVEL_DURATIONS[route]
        self.in_transit = True
        self.destination = destination
        self.eta_rounds = travel_time

    def tick(self) -> None:
        """Advance ship travel by one round.

        Decrements the ETA counter. When ETA reaches 0, the ship arrives at its
        destination and transitions to stationary mode. Called at the start of
        each new game round.
        """
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
    # Personalisierte Frachtraumkapazität (kann erweitert werden)
    cargo_capacity: int = 0
    # Anzahl durchgeführter Erweiterungen
    cargo_extensions: int = 0

    def __post_init__(self) -> None:
        """Initialize player state after dataclass creation.

        Sets up cost basis tracking, cargo capacity based on player type (human/AI),
        and initial total wealth. Called automatically after dataclass instantiation.
        """
        self.total_wealth = (
            self.cash
        )  # initial nur Cash, wird in AI-Entscheidungen aktualisiert
        if self.cost_basis is None:
            self.cost_basis = {g: 0 for g in GOODS}
        else:
            for g in GOODS:
                self.cost_basis.setdefault(g, 0)
        # Setze initiale Kapazität basierend auf AI-Status
        if self.cargo_capacity == 0:
            self.cargo_capacity = AI_CARGO_CAPACITY if self.is_ai else CARGO_CAPACITY

    def cargo_used(self) -> int:
        """Calculate cargo units currently in use.

        Returns:
            int: Sum of all goods in cargo inventory.
        """
        return sum(self.cargo.values())

    def cargo_free(self) -> int:
        """Calculate available cargo space.

        Returns:
            int: Remaining capacity (cargo_capacity - cargo_used()).
        """
        return self.cargo_capacity - self.cargo_used()

    def avg_cost(self, good: str) -> float:
        """Calculate average purchase price per unit of a good.

        Computes the average cost basis for goods currently held. Useful for
        determining profit/loss on sales.

        Args:
            good (str): Name of the commodity.

        Returns:
            float: Average price paid per unit, or 0.0 if not held.
        """
        qty = self.cargo.get(good, 0)
        if qty <= 0:
            return 0.0
        return self.cost_basis.get(good, 0) / float(qty)

    def update_total_wealth(self, prices: Dict[str, Dict[str, int]]) -> None:
        """Recalculate total wealth based on current market prices.

        Updates total_wealth to reflect cash + (all cargo items at current location prices).
        Must be called after prices change or cargo is modified.

        Args:
            prices (Dict[str, Dict[str, int]]): Current market prices by location and good.
        """
        loc = self.ship.location
        self.total_wealth = self.cash + sum(
            self.cargo[g] * prices[loc][g] for g in GOODS
        )


@dataclass
class GameState:
    """Represents the complete state of a game session.

    Manages all game data including round number, player information, market prices,
    trading history, and random number generator state for deterministic replay.

    Attributes:
        round_no (int): Current game round number (1-indexed).
        current_player_idx (int): Index of the current player in the players list.
        players (List[Player]): All players in the game (human and AI).
        prices (Dict[str, Dict[str, int]]): Current market prices (location -> good -> price).
        rng_state_b64 (str): Serialized random state for reproducible games.
        price_stats (Dict): Historical price statistics for AI decision-making.
    """

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
        """Restore the random number generator to a previous state.

        Deserializes the encoded RNG state to enable deterministic replay of games.

        Returns:
            random.Random: A restored random.Random object with the saved state.
        """
        rng = random.Random()
        rng.setstate(_unb64_pickle(self.rng_state_b64))
        return rng

    def rng_store(self, rng: random.Random) -> None:
        """Save the current random number generator state.

        Serializes the RNG state for later restoration, ensuring game reproducibility.

        Args:
            rng (random.Random): The random number generator to save.
        """
        self.rng_state_b64 = _b64_pickle(rng.getstate())


# ============================================================
# 3) PREIS-ENGINE + HISTORY
# ============================================================


def ensure_config_valid() -> None:
    """Validate game configuration for consistency.

    Checks that all locations have price bounds defined for all goods, and that
    min prices are not greater than max prices. Raises ValueError if validation fails.

    Raises:
        ValueError: If price bounds are missing or invalid.
    """
    for loc, bounds in PRICE_BOUNDS.items():
        for g in GOODS:
            if g not in bounds:
                raise ValueError(f"Ort '{loc}' hat keine Preisgrenze für Gut '{g}'.")
            mn, mx = bounds[g]
            if mn > mx:
                raise ValueError(f"Ungültige Grenzen in '{loc}' für '{g}': min>max.")


def init_price_stats() -> Dict[str, Dict[str, Dict[str, int]]]:
    """Initialize empty price statistics tracking.

    Creates a data structure to track running sum and count of prices for each
    location and good, enabling AI players to estimate long-term price expectations.

    Returns:
        Dict: Nested dictionary with structure {location: {good: {sum: 0, count: 0}}}
    """
    stats: Dict[str, Dict[str, Dict[str, int]]] = {}
    for loc in PRICE_BOUNDS.keys():
        stats[loc] = {}
        for g in GOODS:
            stats[loc][g] = {"sum": 0, "count": 0}
    return stats


def update_price_stats(
    stats: Dict[str, Dict[str, Dict[str, int]]], prices: Dict[str, Dict[str, int]]
) -> None:
    """Record current prices into running statistics.

    Adds current prices to the cumulative sum and increments the sample count
    for each location and good. Used to compute historical price averages.

    Args:
        stats: Price statistics tracking structure.
        prices: Current market prices to record.
    """
    for loc in prices:
        for g in prices[loc]:
            stats[loc][g]["sum"] += int(prices[loc][g])
            stats[loc][g]["count"] += 1


def expected_price(
    stats: Dict[str, Dict[str, Dict[str, int]]], loc: str, good: str, fallback: int
) -> float:
    """Estimate expected price based on historical average.

    Computes the mean price for a good at a location across all previous rounds.
    Used by AI players to make trading decisions based on historical trends.

    Args:
        stats: Historical price statistics.
        loc (str): Location name.
        good (str): Good name.
        fallback (int): Default price if no history exists.

    Returns:
        float: Average historical price, or fallback if no data available.
    """
    c = stats[loc][good]["count"]
    if c <= 0:
        return float(fallback)
    return stats[loc][good]["sum"] / float(c)


def check_sun_flare(rng: random.Random) -> bool:
    """Determine if a solar flare event occurs."""
    result: bool = rng.random() < SUN_FLARE_PROBABILITY
    print(
        f"🔍 Sonnensturm Check: {'JA' if result else 'NEIN'} (Wahrscheinlichkeit: {SUN_FLARE_PROBABILITY*100:.1f}%)"
    )
    return result


def generate_prices(rng: random.Random) -> Dict[str, Dict[str, int]]:
    """Generate random prices for all goods at all locations.

    Creates new market prices within PRICE_BOUNDS. Called at the start of each
    round to simulate dynamic market conditions. Part of economic simulation.

    If SunFlare occurs, all prices at the affected location are doubled for that round.

    Args:
        rng (random.Random): Random number generator for reproducible results.

    Returns:
        Dict: Market prices with structure {location: {good: price}}.
    """
    prices: Dict[str, Dict[str, int]] = {}
    for loc, bounds_for_loc in PRICE_BOUNDS.items():
        prices[loc] = {}
        faktor: int = 1
        # check if sun flare occurs at this location
        if check_sun_flare(rng):
            faktor = 2  # Preise steigen bei Sonnensturm
            print(f"⚠️  Sonnensturm in {loc}! Preise verdoppeln sich diese Runde.")
        for good in GOODS:
            mn, mx = bounds_for_loc[good]
            prices[loc][good] = rng.randint(mn, mx) * faktor
    return prices


# ============================================================
# 4) SAVE / LOAD
# ============================================================


def gamestate_to_jsonable(gs: GameState) -> dict:
    """Convert game state to JSON-serializable dictionary.

    Transforms GameState into a flat dictionary suitable for JSON serialization,
    including player data, prices, RNG state, and configuration metadata.

    Args:
        gs (GameState): The game state to serialize.

    Returns:
        dict: JSON-compatible dictionary representation of game state.
    """
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
                "cargo_capacity": p.cargo_capacity,
                "cargo_extensions": p.cargo_extensions,
            }
            for p in gs.players
        ],
        "meta": {
            "START_CASH": START_CASH,
            "CARGO_CAPACITY": CARGO_CAPACITY,
            "AI_CARGO_CAPACITY": AI_CARGO_CAPACITY,
            "GOODS": GOODS,
            "LOCATIONS": list(PRICE_BOUNDS.keys()),
        },
    }


def jsonable_to_gamestate(d: dict) -> GameState:
    """Reconstruct game state from JSON dictionary.

    Parses a JSON dictionary back into a GameState object, rebuilding all player,
    ship, and game data structures from their serialized form.

    Args:
        d (dict): Dictionary produced by gamestate_to_jsonable().

    Returns:
        GameState: Reconstructed game state ready to resume.
    """
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
        cargo_capacity = int(pd.get("cargo_capacity", 0))
        cargo_extensions = int(pd.get("cargo_extensions", 0))
        players.append(
            Player(
                name=pd["name"],
                cash=int(pd["cash"]),
                cargo=cargo,
                ship=ship,
                is_ai=bool(pd.get("is_ai", False)),
                cost_basis=cost_basis,
                total_wealth=int(pd.get("total_wealth", 0)),
                cargo_capacity=cargo_capacity,
                cargo_extensions=cargo_extensions,
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


def save_game(gs: GameState, path: str) -> None:
    """Save game state to a JSON file.

    Serializes the complete game state including RNG for later recall. Automatically
    adds .save extension if not provided. Reproducible replay guaranteed by saved RNG.

    Args:
        gs (GameState): The game state to save.
        path (str): File path (with or without .save extension).
    """
    # Sicherstellen, dass Dateiendung .save hat (optional)
    if not path.lower().endswith(".save"):
        path += ".save"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(gamestate_to_jsonable(gs), f, ensure_ascii=False, indent=2)
    print(f"✅ Spiel gespeichert: {path}")


def load_game(path: str) -> GameState:
    """Load game state from a saved JSON file.

    Deserializes a save file back into a complete GameState with all player data,
    market state, and RNG, allowing seamless game resumption.

    Args:
        path (str): Path to save file (with or without .save extension).

    Returns:
        GameState: The loaded game state ready to resume.

    Raises:
        FileNotFoundError: If the save file doesn't exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
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


def print_header(title: str) -> None:
    """Print a formatted section header to the console.

    Displays a visually distinct title surrounded by separator lines.
    Used to mark major game sections and status updates.

    Args:
        title (str): The header text to display.
    """
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_market(prices_for_loc: Dict[str, int], loc: str) -> None:
    """Display current market prices for all goods at a location.

    Shows a formatted price list for the player's reference during trading decisions.

    Args:
        prices_for_loc (Dict[str, int]): Good names to prices at this location.
        loc (str): Location name to display.
    """
    print(f"\n📍 Marktpreise in {loc}:")
    for g in GOODS:
        print(f"  - {g:<12} {prices_for_loc[g]:>4} Credits")


def print_player_status(p: Player) -> None:
    """Display detailed player information including inventory and ship status.

    Shows cash, total wealth, ship location/transit status, cargo capacity and contents
    with average cost per item. Used to inform player decisions.

    Args:
        p (Player): The player to display information for.
    """
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
    print(
        f"📦 Frachtraum: {p.cargo_used()}/{p.cargo_capacity} (frei: {p.cargo_free()})"
    )
    if p.cargo_used() == 0:
        print("   (leer)")
    else:
        for g in GOODS:
            qty = p.cargo.get(g, 0)
            if qty:
                avg = p.avg_cost(g)
                print(f"   - {g:<12} {qty:>2} Einheit(en) | Ø Einstand: {avg:.2f}")


def choose_int(prompt: str, min_v: int, max_v: int) -> int:
    """Prompt user for integer input within a valid range.

    Repeatedly asks for input until a valid integer within [min_v, max_v] is received.

    Args:
        prompt (str): The question to display.
        min_v (int): Minimum valid value (inclusive).
        max_v (int): Maximum valid value (inclusive).

    Returns:
        int: The validated user input.
    """
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
    """Present a numbered menu and get user selection.

    Displays options numbered 1-N and prompts for selection by number.
    Re-prompts on invalid input.

    Args:
        prompt (str): Question to display before the list.
        options (List[str]): List of options to present.

    Returns:
        str: The selected option from the list.
    """
    for i, opt in enumerate(options, start=1):
        print(f"  {i}) {opt}")
    idx = choose_int(prompt, 0, len(options))
    if idx == 0:
        return "X"  # Abbruchsignal
    return options[idx - 1]


def buy_goods(gs: GameState, p: Player) -> None:
    """Interactive trading: prompt player to buy goods at current location.

    Allows player to purchase available goods up to cash and cargo limits.
    Updates player inventory, cash, and cost basis. Prevents buying while in transit.

    Args:
        gs (GameState): The game state (for prices and validation).
        p (Player): The player making the purchase.
    """
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


def sell_goods(gs: GameState, p: Player) -> None:
    """Interactive trading: prompt player to sell goods at current location.

    Allows player to sell any goods in inventory at current location prices.
    Updates cash and reduces cost basis. Prevents selling while in transit.

    Args:
        gs (GameState): The game state (for prices).
        p (Player): The player making the sale.
    """
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


def set_course(p: Player) -> None:
    """Interactive travel: prompt player to set destination.

    Allows player to choose a destination and initiate 1-round travel.
    Prevents travel if already in transit.

    Args:
        p (Player): The player setting course.
    """
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
    if dest == "X":
        print("Abgebrochen.")
        return
    travel_time = TRAVEL_DURATIONS[(ship.location, dest)]
    ship.start_travel(dest, ship.location)
    print(f"✅ Kurs gesetzt: Flug nach {dest}. ETA: {travel_time} Runde(n).")


def extend_cargo_capacity(p: Player) -> None:
    """Interactive upgrade: allow player to purchase cargo hold expansion.

    Expands cargo capacity by CARGO_EXTENSION_AMOUNT units. Requires empty cargo
    and stationary ship. Cost increases with each upgrade (linear scaling).
    Displays confirmation dialog with cost breakdown.

    Args:
        p (Player): The player upgrading their cargo hold.
    """
    ship = p.ship

    # jede Erweiterung ist teurer als die vorherige (lineare Steigerung)
    extension_cost = CARGO_EXTENSION_COST + (p.cargo_extensions * CARGO_EXTENSION_COST)

    # Bedingungen prüfen
    if ship.in_transit:
        print(
            "⛔ Frachtraumerweiterung nicht möglich: Dein Schiff ist gerade unterwegs."
        )
        return

    if p.cargo_used() > 0:
        print("⛔ Frachtraumerweiterung nicht möglich: Dein Frachtraum muss leer sein.")
        return

    if p.cargo_extensions >= MAX_CARGO_EXTENSIONS:
        max_cap = (AI_CARGO_CAPACITY if p.is_ai else CARGO_CAPACITY) + (
            MAX_CARGO_EXTENSIONS * CARGO_EXTENSION_AMOUNT
        )
        print(
            f"⛔ Maximale Frachtraumerweiterungen erreicht ({p.cargo_capacity}/{max_cap} Einheiten)."
        )
        return

    if p.cash < extension_cost:
        print(
            f"⛔ Nicht genug Geld! Erweiterung kostet {extension_cost} Credits, du hast aber nur {p.cash}."
        )
        return

    # Bestätigung
    print(f"\n🔧 Frachtraumerweiterung")
    print(f"   Aktuelle Kapazität: {p.cargo_capacity} Einheiten")
    print(
        f"   Neue Kapazität:     {p.cargo_capacity + CARGO_EXTENSION_AMOUNT} Einheiten"
    )
    print(f"   Kosten:             {extension_cost} Credits")
    print(f"   Dein Cash nach:     {p.cash - extension_cost} Credits")

    confirm = input("\n✓ Bestätigen? (ja/nein): ").strip().lower()
    if confirm not in ("ja", "j", "yes", "y"):
        print("Abgebrochen.")
        return

    # Durchführung
    p.cash -= extension_cost
    p.cargo_capacity += CARGO_EXTENSION_AMOUNT
    p.cargo_extensions += 1
    # Schiff auf in Transit setzen, damit Erweiterung erst in der nächsten Runde wirksam wird
    p.ship.in_transit = True
    p.ship.destination = p.ship.location  # bleibt am selben Ort, aber in Transit

    print(f"✅ Frachtraum erweitert! Neue Kapazität: {p.cargo_capacity} Einheiten.")


def end_turn(gs: GameState) -> None:
    """Advance to the next player's turn.

    Increments the current player index, wrapping around to player 0 when reaching
    the end of the player list.

    Args:
        gs (GameState): The game state to update.
    """
    gs.current_player_idx = (gs.current_player_idx + 1) % len(gs.players)


def check_pirate_attack(rng: random.Random) -> bool:
    """Determine if a pirate attack occurs on an arriving ship.

    Uses random probability to decide if space pirates attack. Called when a ship
    arrives at its destination. Probability is defined by PIRATE_ATTACK_PROBABILITY.

    Args:
        rng (random.Random): Random number generator.

    Returns:
        bool: True if a pirate attack occurs, False otherwise.
    """
    result: bool = rng.random() < PIRATE_ATTACK_PROBABILITY
    print(
        f"🔍 Piratenüberfall Check: {'JA' if result else 'NEIN'} (Wahrscheinlichkeit: {PIRATE_ATTACK_PROBABILITY*100:.1f}%)"
    )

    return result


def apply_pirate_attack(p: Player, rng: random.Random) -> None:
    """Execute a pirate attack on a player's ship.

    When pirates attack, they steal half of each good in the ship's cargo.
    The ship still reaches its destination later (1 round delay).
    Updates cargo and cost basis proportionally.

    Args:
        p (Player): The player being attacked.
        rng (random.Random): Random number generator (for future variability).
    """
    total_stolen_value = 0
    stolen_goods: Dict[str, int] = {}

    # Schiff braucht 1 Runde länger, um Ziel zu erreichen (Piratenüberfall verzögert Ankunft)
    p.ship.eta_rounds += 1

    # Berechne Diebstahl pro Gut (50% von jedem Gut)
    for g in GOODS:
        qty = p.cargo.get(g, 0)
        if qty > 0:
            stolen_qty = int(qty * PIRATE_CARGO_LOSS)
            if stolen_qty > 0:
                stolen_goods[g] = stolen_qty
                # Reduziere Cargo und Kostenbasis
                avg_cost = p.avg_cost(g)
                stolen_value = stolen_qty * avg_cost
                total_stolen_value += stolen_value

                p.cargo[g] = qty - stolen_qty
                p.cost_basis[g] = max(0, p.cost_basis[g] - int(stolen_value))

    # Display message
    if stolen_goods:
        print("\n⚠️  ☠️ PIRATEN-ÜBERFALL! ☠️")
        print(f"👤 {p.name}s Schiff wurde von Weltraum-Piraten angegriffen!")
        print("🏴 Die Piraten entkamen mit folgenden Gütern:")
        for g, qty in stolen_goods.items():
            print(f"    - {qty} x {g}")
        print(f"💸 Geschätzter Wert: {int(total_stolen_value)} Credits")
        print(f"✅ Das Schiff erreicht das Ziel in {p.ship.eta_rounds} Runden.\n")
    else:
        print(f"\n⚠️  ☠️ PIRATEN-ÜBERFALL! ☠️")
        print(f"👤 {p.name}s Schiff wurde von Weltraum-Piraten angegriffen!")
        print("🏴 Die Piraten fanden keine Güter zum Stehlen.")
        print(f"✅ Das Schiff erreicht das Ziel in {p.ship.eta_rounds} Runden.\n")


def start_new_round(gs: GameState, rng: random.Random) -> None:
    """Begin a new game round: process arrivals, regenerate prices, update history.

    Executes at round transitions: ships complete travel, new prices are generated,
    price history is updated, and RNG state is saved. Increment round counter.

    Args:
        gs (GameState): The game state to advance.
        rng (random.Random): The random number generator for price generation.
    """
    gs.round_no += 1

    # Piraten-Ereignis: mit 10% Chance werden ankommende Schiffe überfallen
    for p in gs.players:
        # Event tritt nur auf, wenn Schiff unterwegs ist
        if p.ship.in_transit and check_pirate_attack(rng):
            apply_pirate_attack(p, rng)
            input("Drücke Enter, um fortzufahren...")

    # Schiffe ticken (Ankünfte zu Beginn der Runde)
    for p in gs.players:
        p.ship.tick()

    # Preise neu berechnen
    gs.prices = generate_prices(rng)

    # Preis-Stats updaten (für AI-Erwartung)
    update_price_stats(gs.price_stats, gs.prices)

    # RNG-State sichern
    gs.rng_store(rng)


def ranking(gs: GameState) -> None:
    """Display current standings with players sorted by total wealth.

    Shows a ranked leaderboard with each player's wealth, cash, and cargo status.
    Updates wealth values based on current market prices. Used for game progress display.

    Args:
        gs (GameState): The game state to display rankings from.
    """
    # Reichtum für alle Spieler aktualisieren (für AI-Entscheidungen und Anzeige)
    for p in gs.players:
        p.update_total_wealth(gs.prices)
    print_header("🏁 Zwischenstand (nach Reichtum sortiert)")
    rows = sorted(gs.players, key=lambda p: p.total_wealth, reverse=True)
    for i, p in enumerate(rows, start=1):
        tag = "🤖" if p.is_ai else "👤"
        print(
            f"{i:>2}. {tag} {p.name:<18} Reichtum: {p.total_wealth:>9,} | Cash: {p.cash:>9,} | Cargo: {p.cargo_used():>2}/{p.cargo_capacity}"
        )


# ============================================================
# 6) AI-LOGIK
# ============================================================


def ai_take_turn(gs: GameState, p: Player, rng: random.Random) -> None:
    """Execute one turn for an AI player.

    Einfacher AI-Zug:
    1) Wenn unterwegs: nichts tun
    2) Wenn angekommen: profitable Güter am Standort verkaufen
    3) Beste erwartete Arbitrage suchen (History-basierte Erwartung am Ziel), kaufen, fliegen

    AI strategy: (1) Sell profitable goods at current location. (2) Identify best
    expected arbitrage using historical price data and profit margins. (3) Buy goods
    and travel to destination, or wait/explore if no clear opportunity.

    Args:
        gs (GameState): The game state (prices, stats).
        p (Player): The AI player taking a turn.
        rng (random.Random): Random number generator for decision randomness.
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
            travel_time = TRAVEL_DURATIONS[(loc, dest)]
            p.ship.start_travel(dest, loc)
            print(
                f"🤖 {p.name} findet keinen klaren Deal und fliegt auf Verdacht nach {dest} (ETA: {travel_time} Runde(n))."
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
        travel_time = TRAVEL_DURATIONS[(loc, dest)]
        p.ship.start_travel(dest, loc)
        print(
            f"🤖 {p.name} will {good} handeln, hat aber kein Budget/Frachtraum. Fliegt trotzdem nach {dest} (ETA: {travel_time} Runde(n))."
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
    travel_time = TRAVEL_DURATIONS[(loc, dest)]
    p.ship.start_travel(dest, loc)
    print(f"🤖 {p.name} setzt Kurs nach {dest}. ETA: {travel_time} Runde(n).")


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
  expandieren   - Frachtraum erweitern (Schiff muss leer + nicht unterwegs sein)
  ende          - Zug beenden
  save <datei>  - Spiel speichern (z.B. save savegame.json)
  load <datei>  - Spiel laden
  rang          - Zwischenstand / Ranking
  help          - Hilfe anzeigen
  quit          - Spiel beenden (ohne automatisch zu speichern)
  ----------
  pirat 50 - 50% Chance, dass ankommende Schiffe überfallen werden, normal sind 10 
  sonne 50 - 50% Chance, dass ein Sonnensturm auftritt, normal sind 5
"""


def run_game(gs: GameState) -> None:
    """Execute the main game loop.

    Manages turn-based gameplay: alternating between human and AI player turns,
    processing commands, updating game state, and handling round transitions.
    Continues until player quits. Supports save/load mid-game.

    Args:
        gs (GameState): The initialized game state to run.
    """
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

            elif cmd in ("status", "st"):
                print_player_status(p)

            elif cmd in ("markt", "m"):
                if p.ship.in_transit:
                    print("ℹ️ Du bist unterwegs. Marktpreise siehst du erst am Ziel.")
                else:
                    loc = p.ship.location
                    print_market(gs.prices[loc], loc)

            elif cmd in ("buy", "b"):
                buy_goods(gs, p)

            elif cmd in ("sell", "s"):
                sell_goods(gs, p)

            elif cmd in ("kurs", "k"):
                set_course(p)

            elif cmd in ("expandieren", "exp"):
                extend_cargo_capacity(p)

            elif cmd in ("rang", "ra"):
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

            elif cmd in ("quit", "exit", "q", "x"):  # Spiel beenden
                print("👋 Spiel beendet.")
                return

            elif cmd in ("ende", "e"):  # Zug beenden
                gs.rng_store(rng)
                end_turn(gs)

                if gs.current_player_idx == 0:
                    print_header(
                        "⏭️ Rundenwechsel: Neue Runde beginnt (Preise neu, Reisen ticken)"
                    )
                    start_new_round(gs, rng)
                    ranking(gs)

                break

            # geheime Befehle für Tests / Debugging
            elif cmd == "pirat":
                global PIRATE_ATTACK_PROBABILITY
                if len(parts) == 2:
                    try:
                        val = float(parts[1])
                        PIRATE_ATTACK_PROBABILITY = val / 100.0
                        print(
                            f"⚠️ Piraten-Angriffs-Wahrscheinlichkeit auf {val}% gesetzt."
                        )
                    except ValueError:
                        print("⛔ Ungültiger Wert. Nutzung: pirat <Prozent>")
                else:
                    print("⛔ Nutzung: pirat <Prozent>")

            elif cmd == "sonne":
                global SUN_FLARE_PROBABILITY
                if len(parts) == 2:
                    try:
                        val = float(parts[1])
                        SUN_FLARE_PROBABILITY = val / 100.0
                        print(f"⚠️ Sonnenstrahl-Wahrscheinlichkeit auf {val}% gesetzt.")
                    except ValueError:
                        print("⛔ Ungültiger Wert. Nutzung: sonne <Prozent>")
                else:
                    print("⛔ Nutzung: sonne <Prozent>")

            else:
                print("Unbekannter Befehl. Tipp: 'help' eingeben.")


# ============================================================
# 8) START / CLI + NEUES SPIEL MIT HUMAN + AI
# ============================================================


def make_unique_ai_names(count: int, rng: random.Random) -> List[str]:
    """Generate unique AI player names from name pool.

    Randomly selects and returns unique AI names from AI_NAME_POOL. If more names
    needed than available in pool, appends numeric suffixes to avoid duplicates.

    Args:
        count (int): Number of AI names to generate.
        rng (random.Random): Random number generator for shuffling.

    Returns:
        List[str]: List of unique AI player names.
    """
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
    """Initialize a new game with interactive setup.

    Prompts user for number of human and AI players, collects human player names,
    generates AI names, initializes all players at start location with starting capital,
    and seeds RNG for reproducible gameplay.

    Args:
        seed (Optional[int]): Random seed for reproducible games. Auto-generated if None.

    Returns:
        GameState: A freshly initialized game state ready to play.
    """
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

    # Menschen
    for i in range(human_n):
        name = (
            input(f"Name Spieler {i+1} (leer = Spieler{i+1}): ").strip()
            or f"Spieler{i+1}"
        )
        cargo = {g: 0 for g in GOODS}
        start_loc = rng.choice(list(PRICE_BOUNDS.keys()))
        ship = Ship(location=start_loc)
        players.append(
            Player(name=name, cash=START_CASH, cargo=cargo, ship=ship, is_ai=False)
        )

    # AI
    ai_names = make_unique_ai_names(ai_n, rng)
    for name in ai_names:
        cargo = {g: 0 for g in GOODS}
        start_loc = rng.choice(list(PRICE_BOUNDS.keys()))
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


def main() -> None:
    """Parse command-line arguments and start the game.

    Supports --load to resume a saved game or --seed to start deterministic new game.
    If neither provided, begins interactive new game setup.

    Command-line Usage:
        python script.py                          # Interactive new game
        python script.py --load game.save         # Resume from save
        python script.py --seed 12345             # New game with seed
    """
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


def clear() -> None:
    """Clear the terminal/console screen.

    Executes platform-specific clear command (cls on Windows, clear on Unix/Linux/Mac).
    Used to provide clean display at game startup.
    """
    os.system("cls" if os.name == "nt" else "clear")


if __name__ == "__main__":
    clear()
    main()
