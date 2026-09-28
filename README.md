# Laya AI Games (CLI)

Terminal games powered by [Laya AI](https://github.com/convaiinnovations/laya) for real-time decision-making.

---

## Games

### 1. Snake Game (`snake_game.py` / `main.py`)
An autonomous snake game played on a 20x20 grid, fully controlled by Laya AI.

- **5-to-0 Second Countdown:** Visual countdown before the game starts.
- **Dynamic Targets & Growth:** Food appears randomly across open cells; the snake grows upon eating food.
- **Continuous Play:** Automatically respawns on game over and continues until stopped (`Ctrl+C`).
- **Live Telemetry HUD:** Displays score, snake length, high score, Laya's decided direction, calibrated confidence, and probability distribution across all 4 directions.

#### How the Snake AI Works
1. **Scene Analysis:** On every step, the game analyzes the 20x20 field:
   - Obstacles (walls, snake body, and 180° neck reversals).
   - BFS pathfinding distance to the active food target.
   - Flood-fill open space to prevent entering dead ends.
2. **Criteria-Driven Decision:** State and candidate moves (`UP`, `DOWN`, `LEFT`, `RIGHT`) are formatted into typed choice questions with dynamic criteria for Laya to evaluate in a single forward pass.

---

### 2. Player vs Computer (PvC) Pong (`pong.py`)
A real-time Pong match where you play against a Laya AI opponent.

- **Controls:**
  - `W` / `S` or `↑` / `↓` : Move paddle up / down
  - `1` / `2` / `3` : Switch game speed on the fly (`1`: Relaxed, `2`: Normal, `3`: Fast)
  - `R` : Reset score and rally count
  - `Q` or `Ctrl+C` : Quit game
- **Live Scoreboard & Telemetry:** Tracks player score, AI score, current rally length, best rally record, and real-time AI move confidence.

#### How the Pong AI Works
1. **Multithreaded Execution:** Laya AI inference runs in a dedicated background worker thread, ensuring the game loop and user keyboard input remain fluid and responsive with zero lag.
2. **Trajectory Prediction:** Simulates ball vector and wall reflections to predict intercept points on the AI paddle line.
3. **AI Decision Engine:** Formulates paddle positioning decisions (`UP`, `DOWN`, `STAY`) based on predicted intercept coordinates.

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
