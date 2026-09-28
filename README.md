# Laya AI Snake Game (20x20 CLI)

An autonomous, terminal-based Snake game where every move is decided in real time by the [Laya AI](https://github.com/convaiinnovations/laya) decision model.

---

## Overview

- **Field Size:** 20x20 grid with ANSI borders.
- **Controller:** Autonomous navigation powered by Laya AI (`convaiinnovations/laya`).
- **Countdown:** 5-to-0 second visual countdown before the game starts.
- **Mechanics:** Snake grows by 1 segment whenever it eats a randomly spawned food target.
- **Continuous Gameplay:** Runs continuously until stopped with `Ctrl+C` (auto-respawns on game over).
- **Telemetry HUD:** Displays real-time score, snake length, high score, Laya's chosen move, calibrated confidence, and probability distribution across all 4 directions.

---

## How It Works

### 1. State Representation & Scene Analysis
On each game tick, the game inspects the current board and extracts:
- Coordinates of the snake head and the active food target.
- Relative position of the food (e.g. `RIGHT` and `DOWN`).
- Obstacle grid (walls and existing snake body segments).
- Evaluated metrics for each direction (`UP`, `DOWN`, `LEFT`, `RIGHT`):
  - **Immediate safety:** Collision checks against boundaries, body segments, and 180° neck reversals.
  - **Shortest path distance:** Breadth-First Search (BFS) distance through open cells to the food target.
  - **Accessible space:** Flood-fill calculation to avoid trapping the snake in closed loops.

### 2. Decision Making with Laya
The game formats the state and queries Laya using typed `choice` questions with dynamic `criteria`:

```python
questions = {
    "next_move": {
        "type": "choice",
        "instructions": f"Which direction is best for the snake at ({head_x}, {head_y}) to safely reach the food target at ({tx}, {ty})?",
        "criteria": {
            "UP": "OPTIMAL MOVE: Safely moves directly towards food at (15, 5), reducing distance to 4.",
            "DOWN": "SUBOPTIMAL: Safe move but moves away from food, increasing distance to 6.",
            "LEFT": "UNSAFE: Immediate collision with snake body.",
            "RIGHT": "SUBOPTIMAL: Safe move into open space, path distance 8."
        }
    }
}

res = agent.predict(state, questions)
```

Laya evaluates the context and option criteria in a single forward pass, returning the chosen move along with calibrated confidence and probabilities for all candidate directions.

### 3. Execution & Rendering
1. The game executes the chosen move.
2. If the snake reaches the target cell, it grows, the score increments, and a new target spawns on a random empty cell.
3. The board and telemetry dashboard update in-place in the terminal.

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

## Running the Game

Run either:

```bash
python snake_game.py
```

or:

```bash
python main.py
```

### Stopping
Press `Ctrl+C` in your terminal at any time to safely exit and view your final stats.
