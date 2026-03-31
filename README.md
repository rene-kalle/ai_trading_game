# AI Trading Games

A turn-based space trading simulation with support for multiple players, locations, goods, and AI opponents. Manage your merchant vessel across interplanetary markets, buy and sell goods at dynamic prices, and maximize your wealth!

## Features

### Core Gameplay
- **Multi-Player**: Play with human players and/or AI opponents
- **Multiple Locations**: Trade across 4 unique space locations (Terra, Luna, Mars, Jovian Station)
- **Multiple Goods**: Buy and sell 5 different commodity types (Water, Ore, Food, Medicine, Electronics)
- **Dynamic Pricing**: Prices fluctuate each round within location-specific min/max bounds
- **Turn-Based Rounds**: Sequential player turns with automatic price regeneration each round
- **Travel Mechanics**: Travel between locations takes exactly 1 round; arrive at the start of your next turn

### Trading System
- **Buy/Sell at Market Prices**: Purchase and sell goods at current location prices
- **Cargo Management**: Limited cargo capacity (30 units for players, 50 for AI)
- **Cargo Expansion**: Upgrade your cargo hold up to 5 times (+10 units per upgrade)
- **Cost Tracking**: System tracks cost basis for profit/loss calculations
- **Price History**: AI players use historical price data to make trading decisions

### AI Players
- **Automated Opponents**: Add AI players to increase challenge
- **Smart Strategy**: AI players evaluate profit margins and expected returns before trading
- **Adaptive Behavior**: AI considers price history, market trends, and position wealth
- **Randomness**: Small randomization ensures varied behavior and interesting gameplay

### Game Management
- **Save/Load Games**: Fully serialize game state including RNG state for deterministic replay
- **Configurable Setup**: Easy-to-modify game parameters (start cash, cargo capacity, prices)
- **Seed Control**: Optional random seed for reproducible games

## Installation

### Requirements
- Python 3.7+
- No external dependencies (uses only Python standard library)

### Setup
1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd ai_trading_game
   ```

2. No additional installation needed—run directly with Python

## Usage

### Starting a New Game

#### Human-Only Game
```bash
python m365_space_trader.py
```
The game will prompt you to enter player names and start a new game.

#### Game with AI Players
```bash
python m365_space_trader_ai.py
```
Customize the number of human and AI players when prompted.

### Load a Saved Game
```bash
python m365_space_trader.py --load game-001.save
```

### Reproducible Games
```bash
python m365_space_trader.py --seed 12345
```
Use the same seed to generate identical price sequences across games.

## Game Mechanics

### The Round System
1. Each round, active player takes their turn
2. Player can:
   - View current market prices at their location
   - Buy goods (if they have cash and cargo space)
   - Sell goods (if they own them)
   - Travel to another location (takes 1 round to arrive)
   - Upgrade cargo capacity
3. After all players take turns, prices regenerate for the next round
4. Ships in transit automatically arrive at the start of the next turn

### Winning Strategy
- **Buy Low, Sell High**: Purchase goods at low prices and sell at high prices elsewhere
- **Market Awareness**: Monitor price trends across different locations
- **Timing**: Plan your travel and trades to maximize time at profitable locations
- **Capital Management**: Balance spending on cargo upgrades vs. trading capital
- **Risk Assessment**: AI players make calculated decisions based on profit potential

### Game State
Your save game file includes:
- All player names, cash, and cargo inventories
- Ship locations and transit status
- Current market prices
- Price history (for AI decision making)
- Random number generator state (ensures reproducibility)

## Files

- **m365_space_trader.py**: Human multiplayer version
- **m365_space_trader_ai.py**: Version with AI player support
- **README.md**: This file
- **game-*.save**: Save game files (JSON format with encoded RNG state)

## Configuration

Edit the configuration sections at the top of each Python file to customize:
- `GOODS`: Available commodities
- `PRICE_BOUNDS`: Min/max prices for each good at each location
- `START_CASH`: Initial player capital
- `CARGO_CAPACITY`: Default cargo capacity for human players
- `AI_CARGO_CAPACITY`: Cargo capacity for AI players
- `TRAVEL_TIME_ROUNDS`: Rounds required to travel between locations
- `CARGO_EXTENSION_COST`: Cost to upgrade cargo hold
- `CARGO_EXTENSION_AMOUNT`: Units added per upgrade
- `MAX_CARGO_EXTENSIONS`: Maximum allowed cargo upgrades

## Example Gameplay

1. Start with 1,000 credits
2. At Terra: Water costs 12 credits, Ore costs 45 credits
3. Buy 10 units of Water (120 credits spent, 880 remaining)
4. Travel to Luna
5. At Luna: Water sells for 25 credits, Ore for 40 credits
6. Sell 10 units of Water (250 credits gained, 1,130 total)
7. Profit: 130 credits on the water arbitrage!
8. Continue trading across multiple locations to grow your wealth

## Developer Notes

- **Code Structure**: Clear separation of game logic, data models, and UI
- **RNG State**: Uses pickle+base64 encoding to preserve exact random state in save files
- **Extensibility**: Easy to add new locations, goods, or game mechanics
- **Type Hints**: Python 3 type annotations for better code clarity

## Future Enhancements

Possible expansions:
- Graphical user interface (GUI)
- Network multiplayer support
- Market events and disruptions
- Ship upgrades and special abilities
- Quest system
- Player rankings and statistics
