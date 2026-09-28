# Laya AI Games Suite (CLI)

Terminal games powered by [Laya AI](https://github.com/convaiinnovations/laya) for real-time decision-making.

---

## Games

### 1. Snake Game (`snake_game.py` / `main.py`)
An autonomous snake game played on a 20x20 grid, fully controlled by Laya AI.

- **5-to-0 Second Countdown:** Visual countdown before the game starts.
- **Dynamic Targets & Growth:** Food appears randomly across open cells; the snake grows upon eating food.
- **Continuous Play:** Automatically respawns on game over and continues until stopped (`Ctrl+C`).
- **Telemetry HUD:** Displays score, snake length, high score, Laya's decided direction, calibrated confidence, and probability distribution across all 4 directions.

---

### 2. Player vs Computer (PvC) Pong (`pong.py`)
A real-time Pong match where you play against a Laya AI opponent.

- **Controls:**
  - `W` / `S` or `↑` / `↓` : Move paddle up / down
  - `1` / `2` / `3` : Switch game speed on the fly (`1`: Relaxed, `2`: Normal, `3`: Fast)
  - `R` : Reset score and rally count
  - `Q` or `Ctrl+C` : Quit game
- **Live Scoreboard & Telemetry:** Tracks player score, AI score, current rally length, best rally record, and real-time AI move confidence.

---

### 3. Checkers Game (`chess.py`)
An 8x8 Checkers (English Draughts) game where a human player competes against Laya AI.

- **Pieces:**
  - `🔴` Player Men / `👑` Player Kings (Red/Green)
  - `🔵` AI Men / `💎` AI Kings (Cyan/Magenta)
- **Rules & Mechanics:**
  - Diagonal single-step forward advances.
  - Jump captures and chained multi-jumps (mandatory capture rule).
  - King crowning on reaching the opposite back row (Kings move & jump in all 4 diagonal directions).
- **Controls & Input:**
  - Enter move number (e.g. `1`, `2`) from the legal moves list.
  - Or enter algebraic notation (e.g. `C3-D4`, `C3 to D4`, `C3xD4`).
  - Type `q` or `quit` to exit.
- **Laya AI Decision Engine:**
  - Evaluates all legal moves, tactical captures, king promotion opportunities, and center control.
  - Selects moves via typed choice reasoning with calibrated confidence and candidate probability distributions.

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

### Run Checkers:
```bash
python chess.py
```

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
