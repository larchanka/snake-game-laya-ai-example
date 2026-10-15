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

### 3. Checkers Game (`checkers.py`)
An 8x8 Checkers (English Draughts) game where a human player competes against Laya AI. (Formerly `chess.py`, with backwards-compatible stub).

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

### 4. Laya Sentinel // Real-Time AI Moderator & Trust Engine (`chat.py`)
A terminal-based dual-column GUI for message moderation and content safety powered by Laya System 1 single-pass neural evaluation.

- **Dual-Column Terminal GUI:** Real-time chat feed on the left; live telemetry, confidence meters, and trust stats on the right.
- **GOOD vs BAD Content Safety:**
  - High-precision classification distinguishing constructive/polite discourse from offensive/swearing content and gibberish/spam.
  - Categorizes verdicts into `CLEAN`, `OFFENSIVE`, `GIBBERISH`, and `SPAM` with severity tiers (0 to 3).
- **Telemetry HUD & Probability Distributions:**
  - Calibrated decision confidence and visual ASCII probability bars.
  - Ultra-low latency tracking (sub-50ms inference), decision throughput, and approval/block ratios.
- **Persistent Trust & Karma Engine:**
  - Live reputation scoring (0–100% karma) dynamically adjusting based on participant history.
  - Visual trust badges: `VERIFIED VIP`, `NEUTRAL`, `PROBATION`, `RESTRICTED`.
- **Interactive Commands & Flags:**
  - In-app commands: `/test` (runs demo test suite), `/stats` (shows telemetry metrics), `/clear` (resets chat window), `/quit` (exits).
  - CLI flags: `--test` (runs automated test suite non-interactively and exits), `--msg "<text>"` (single-message evaluation with instant verdict output).

---

### 5. Laya Poker Arena // 3-NPC Texas Hold'em Spectator Terminal (`poker.py`)
A spectator terminal arena featuring 3 distinct AI personalities competing in No-Limit Texas Hold'em powered by Laya AI decision-making.

- **Spectator God-Mode Visuals:**
  - Full ASCII table rendering community board cards (Flop, Turn, River), pot size, current bet, dealer button (`[D]`), and active chip stacks.
  - God-mode visibility revealing all player private hole cards and active statuses.
- **Strict Information Isolation:**
  - While spectators observe all cards, NPCs operate under true imperfect information: each AI agent's decision prompt only contains its private hole cards, the visible community board, and the round's betting history. Zero access to opponent cards.
- **Real-Time Laya Telemetry:**
  - Live poker hand evaluation (High Card, Pairs, Straight, Flush, Full House, etc.).
  - Mathematical pot odds calculations paired with Laya decision confidence.
  - Candidate action probability distributions over `FOLD`, `CHECK`, `CALL`, `RAISE`, and `ALL-IN`.
- **Distinct AI Personalities:**
  - **Aggressive Alice:** High betting pressure, frequent raises, and calculated bluffing.
  - **Solid Bob:** Tight-aggressive fundamentals, disciplined pot odds management, and value betting.
  - **Chaos Charlie:** Wild, unpredictable betting patterns, wide range, and high-variance play.
- **Interactive Controls:**
  - `[SPACE]` / `[ENTER]`: Step-by-step turn inspection (advance one action at a time).
  - `[A]`: Toggle continuous auto-play spectator mode on/off.
  - `[1-5]`: Change auto-play simulation speed (`1`: Relaxed/cinematic, `3`: Standard, `5`: Ultra-fast).
  - `[Q]`: Quit to terminal.

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

All games can be run either from within the `snake/` directory using the activated virtual environment, or directly from the workspace root using the virtual environment python binary (`snake/.venv/bin/python`).

### Run Laya Sentinel Moderator (`chat.py`):
```bash
# Interactive mode (from repo root)
snake/.venv/bin/python snake/chat.py

# Or within the snake directory:
python chat.py

# Non-interactive automated test suite:
snake/.venv/bin/python snake/chat.py --test

# Single message evaluation:
snake/.venv/bin/python snake/chat.py --msg "Have a wonderful day!"
```

### Run Laya Poker Arena (`poker.py`):
```bash
# From repo root
snake/.venv/bin/python snake/poker.py

# Or within the snake directory:
python poker.py
```

### Run Checkers:
```bash
# From repo root
snake/.venv/bin/python snake/checkers.py

# Or within the snake directory:
python checkers.py

# (Backwards compatibility: python chess.py delegates to checkers.py)
```

### Run Snake:
```bash
# From repo root
snake/.venv/bin/python snake/snake_game.py

# Or within the snake directory:
python snake_game.py
# or
python main.py
```

### Run Pong:
```bash
# From repo root
snake/.venv/bin/python snake/pong.py

# Or within the snake directory:
python pong.py
```
