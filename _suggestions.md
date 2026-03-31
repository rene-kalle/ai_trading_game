
I've reviewed the code. Here are my **improvement suggestions** organized by category:

## **Code Quality & Architecture**

1. **Module splitting** — The file is 1500+ lines. Consider splitting into:
   - `models.py` (Player, Ship, GameState dataclasses)
   - `engine.py` (price generation, game state management)
   - `ui.py` (all print/input functions)
   - `ai_strategy.py` (AI decision logic)
   - `main.py` (game loop, CLI)

2. **Magic numbers** — Extract more values to named constants at the top:
   - Terminal formatting widths (e.g., `"=" * 70`)
   - Menu item indices, message formatting strings
   - Currently `70` appears several times uncaptured

3. **Input validation** — `choose_int()` and `choose_from_list()` could provide more informative error messages with retry counters

## **Bug Fixes & Logic Issues**

1. **Sun flare factor not reset** — In `generate_prices()`, the `faktor` variable persists across locations. It should be reset for each location:
   ```
   for loc...:
       faktor = 1  # Reset here
       if check_sun_flare(rng):
           faktor = 2
   ```

2. **Pirate attack arrival detection** — The check `if not p.ship.in_transit and p.cargo_used() > 0` doesn't verify the ship *just* arrived (could trigger incorrectly if ship stays in one location with cargo). Consider adding an `arrived_this_round` flag.

3. **Cargo extension same-round bypass** — A player can extend cargo mid-round by staying stationary. The code sets `in_transit = True` with `destination = location`, but this is a workaround. Better flag: `in_cargo_extension`.

4. **Load game breaks outer loop** — In `run_game()`, `load_game()` breaks the inner command loop but doesn't properly reinitialize the outer loop. Should use a flag to signal reload.

## **AI Strategy Enhancements**

1. **Risk assessment** — AI doesn't account for pirate attack probability. Could discount expected prices by loss risk.

2. **Location diversity** — AI only exploits profitable arbitrage. Could add exploration bonus for undervisited locations.

3. **Dynamic pricing factors** — AI ignores sun flares. Could recognize price doubles and adjust expectations.

4. **Portfolio tracking** — No rebalancing; AI just dumps and buys. Could track exposure and hedge.

## **User Experience**

1. **Clear screen function** — Replace `os.system('cls')` with:
   ```python
   import subprocess
   subprocess.run(['cls' if os.name == 'nt' else 'clear'], check=False)
   ```
   (More modern and safer)

2. **Command case sensitivity** — Commands work with `.lower()` but help text shows lowercase. Normalize help text too.

3. **Cargo capacity display** — Show cargo *remaining* more prominently (e.g., "📦 4/30 free" instead of "used/total").

4. **Menu optimization** — `choose_from_list()` displays all 5 goods even if only 2 are sellable. Filter displayed options.

## **Testing & Debugging**

1. **No logging** — Add optional `--verbose` flag to log AI decisions, price rolls, pirate attacks.

2. **Seed reproducibility** — Document how to replay a specific game via seed.

3. **Assertions for invariants** — Add checks like:
   - `cash >= 0`
   - `cargo values >= 0`
   - `cost_basis >= 0`

## **Documentation**

1. **Game rules doc** — Add a `RULES.md` explaining:
   - How prices are generated
   - AI decision tree
   - Event probabilities
   - Win conditions

2. **Type hints** — Complete missing hints (e.g., `Optional[int]` defaults, return types for helper functions)

3. **Sun flare impact** — Document price doubling behavior in docstring (currently vague)

---

**Which of these would you like me to prioritize?** I can implement the most impactful fixes (sun flare reset bug, AI strategy enhancements, module splitting) or focus on a specific category.