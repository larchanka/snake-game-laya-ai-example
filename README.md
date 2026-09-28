# Laya AI Games Suite (CLI)

Terminal-based games where gameplay and computer decisions are driven in real time by the [Laya AI](https://github.com/convaiinnovations/laya) decision model.

---

## Games

### 1. Snake Game (`snake_game.py` / `main.py`)
- **Field Size:** 20x20 grid with ANSI borders.
- **Controller:** Autonomous navigation powered by Laya AI (`convaiinnovations/laya`).
- **Countdown:** 5-to-0 second countdown before the game starts.
- **Mechanics:** Snake grows when eating randomly placed food targets.
- **Continuous Gameplay:** Runs continuously until stopped with `Ctrl+C` (auto-respawns on game over).
- **Telemetry HUD:** Live score, length, high score, Laya's chosen move, confidence, and move probability distributions.

### 2. Player vs Computer (PvC) Pong (`pong.py`)
- **Mode:** Human Player (Left Paddle) vs Laya AI (Right Paddle).
- **Controls:**
  - `W` / `S` or `↑` / `↓` Arrow keys: Move paddle
  - `Q` or `Ctrl+C`: Quit
  - `R`: Reset scoreboard
- **Laya AI Opponent:** Predicts ball trajectory and intercept points to choose between `UP`, `DOWN`, and `STAY`.
- **Telemetry & Scoreboard:** Tracks points, current rally count, best rally record, AI confidence, and move probabilities.

---

## Installation

1. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Running the Games

### Run Snake:
```bash
python snake_game.py
# or
python main.py
```

### Run Pong:
```bash
python pong.py
```
