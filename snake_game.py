#!/usr/bin/env python3
"""
Laya AI Snake Game (20x20 CLI)
Controlled autonomously by Laya structured reasoning.
"""

import sys
import os
import time
import random
import warnings
from collections import deque
from typing import Dict, List, Tuple, Optional, Set

# Suppress temperature calibration warnings from laya router/agent
warnings.filterwarnings("ignore")

import laya

# Constants
GRID_WIDTH = 20
GRID_HEIGHT = 20
INITIAL_SNAKE_LENGTH = 3

DIRECTIONS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

OPPOSITE_DIRECTIONS = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}

# ANSI Escape Sequences
CLEAR_SCREEN = "\033[2J"
CURSOR_HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[32m"
COLOR_BRIGHT_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_GRAY = "\033[90m"
COLOR_BOLD = "\033[1m"


class SnakeGame:
    def __init__(self, agent: Optional[laya.Agent] = None):
        self.width = GRID_WIDTH
        self.height = GRID_HEIGHT
        self.agent = agent if agent is not None else laya.load("convaiinnovations/laya")
        self.schema = {
            "type": "object",
            "properties": {
                "next_move": {
                    "type": "string",
                    "enum": ["UP", "DOWN", "LEFT", "RIGHT"],
                    "description": "Select the best and safest move direction for the snake to reach the food target without collision."
                }
            }
        }
        
        self.game_count = 0
        self.high_score = 0
        self.reset_game()

    def reset_game(self):
        """Reset game state for a new round."""
        self.game_count += 1
        mid_x = self.width // 2
        mid_y = self.height // 2
        
        # Initial snake moving RIGHT
        self.snake: deque[Tuple[int, int]] = deque([
            (mid_x, mid_y),
            (mid_x - 1, mid_y),
            (mid_x - 2, mid_y),
        ])
        self.current_direction = "RIGHT"
        self.score = 0
        self.steps = 0
        self.is_game_over = False
        self.last_ai_decision = {}
        self.target = self._spawn_target()

    def _spawn_target(self) -> Tuple[int, int]:
        """Spawn a new target food at a random empty field position."""
        occupied = set(self.snake)
        empty_cells = [
            (x, y)
            for x in range(self.width)
            for y in range(self.height)
            if (x, y) not in occupied
        ]
        if not empty_cells:
            return (-1, -1)  # Grid full (Win condition)
        return random.choice(empty_cells)

    def is_safe_move(self, move: str) -> bool:
        """Check if moving in direction `move` avoids wall and self collisions."""
        if move not in DIRECTIONS:
            return False
        
        # Cannot reverse 180 degrees into itself
        if len(self.snake) > 1 and move == OPPOSITE_DIRECTIONS.get(self.current_direction):
            return False

        dx, dy = DIRECTIONS[move]
        head_x, head_y = self.snake[0]
        nx, ny = head_x + dx, head_y + dy

        # Wall collision check
        if not (0 <= nx < self.width and 0 <= ny < self.height):
            return False

        # Self collision check (tail will move away unless snake just ate, but being safe is better)
        body_without_tail = list(self.snake)[:-1]
        if (nx, ny) in body_without_tail:
            return False

        return True

    def get_safe_moves(self) -> List[str]:
        """Get all currently safe moves for the snake."""
        safe = [m for m in ["UP", "DOWN", "LEFT", "RIGHT"] if self.is_safe_move(m)]
        return safe

    def _bfs_distance(self, start: Tuple[int, int], goal: Tuple[int, int], obstacles: Set[Tuple[int, int]]) -> int:
        """Calculate shortest obstacle-avoiding distance using BFS."""
        if start == goal:
            return 0
        queue = deque([(start[0], start[1], 0)])
        visited = {start}
        while queue:
            cx, cy, dist = queue.popleft()
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    if (nx, ny) == goal:
                        return dist + 1
                    if (nx, ny) not in visited and (nx, ny) not in obstacles:
                        visited.add((nx, ny))
                        queue.append((nx, ny, dist + 1))
        return 999  # Unreachable

    def _flood_fill_space(self, start: Tuple[int, int], obstacles: Set[Tuple[int, int]]) -> int:
        """Measure accessible space from a position."""
        if not (0 <= start[0] < self.width and 0 <= start[1] < self.height) or start in obstacles:
            return 0
        visited = {start}
        queue = deque([start])
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    if (nx, ny) not in visited and (nx, ny) not in obstacles:
                        visited.add((nx, ny))
                        queue.append((nx, ny))
        return len(visited)

    def decide_move_with_laya(self) -> Tuple[str, Dict]:
        """Formulate game state and query Laya AI with typed questions and option criteria."""
        head_x, head_y = self.snake[0]
        tx, ty = self.target
        safe_moves = self.get_safe_moves()

        if not safe_moves:
            # Trapped, keep moving current direction
            return self.current_direction, {"laya_choice": self.current_direction, "actual_move": self.current_direction, "confidence": 0.0, "probabilities": {}}

        snake_body_set = set(list(self.snake)[:-1])
        cur_dist = abs(head_x - tx) + abs(head_y - ty)

        # Determine target relative quadrant/direction
        rel_x = "RIGHT" if tx > head_x else ("LEFT" if tx < head_x else "SAME_COLUMN")
        rel_y = "DOWN" if ty > head_y else ("UP" if ty < head_y else "SAME_ROW")

        # Build precise criteria for all 4 directions
        criteria = {}
        move_scores = {}

        for move, (dx, dy) in DIRECTIONS.items():
            nx, ny = head_x + dx, head_y + dy
            # Unsafe move check (wall collision or self collision or 180 reverse)
            if not (0 <= nx < self.width and 0 <= ny < self.height) or (nx, ny) in snake_body_set or (len(self.snake) > 1 and move == OPPOSITE_DIRECTIONS.get(self.current_direction)):
                criteria[move] = "UNSAFE: Immediate collision with wall, snake body, or 180-degree self-reversal."
                continue

            bfs_dist = self._bfs_distance((nx, ny), (tx, ty), snake_body_set)
            free_space = self._flood_fill_space((nx, ny), snake_body_set)
            new_manhattan = abs(nx - tx) + abs(ny - ty)
            eff_dist = bfs_dist if bfs_dist < 900 else new_manhattan
            move_scores[move] = (eff_dist, -free_space, new_manhattan)

            if (nx, ny) == (tx, ty):
                criteria[move] = f"EXCELLENT: Immediately reaches the food target at ({tx}, {ty})!"
            elif eff_dist < cur_dist and (move == rel_x or move == rel_y):
                criteria[move] = f"OPTIMAL MOVE: Safely moves directly towards food at ({tx}, {ty}), reducing distance to {eff_dist}."
            elif eff_dist < cur_dist:
                criteria[move] = f"GOOD MOVE: Safely gets closer to food at ({tx}, {ty}), path distance {eff_dist}."
            else:
                criteria[move] = f"SUBOPTIMAL: Safe move but moves away from food at ({tx}, {ty}), increasing distance to {eff_dist}."

        state = {
            "snake_head": f"({head_x}, {head_y})",
            "food_target": f"({tx}, {ty})",
            "relative_location": f"Food is {rel_x} and {rel_y} relative to head.",
            "current_direction": self.current_direction,
            "situation": f"Snake head at ({head_x}, {head_y}) must safely navigate to food target at ({tx}, {ty})."
        }

        questions = {
            "next_move": {
                "type": "choice",
                "instructions": f"Which direction is best for the snake at ({head_x}, {head_y}) to safely reach the food target at ({tx}, {ty})?",
                "criteria": criteria
            }
        }

        try:
            res = self.agent.predict(state, questions)
            ans = res.get("answers", {}).get("next_move", {})
            chosen_move = ans.get("choice", self.current_direction)
            confidence = ans.get("confidence", 0.0)
            probabilities = ans.get("probabilities", {})
        except Exception:
            best_move = min(safe_moves, key=lambda m: move_scores.get(m, (999, 0, 999)))
            return best_move, {"laya_choice": best_move, "actual_move": best_move, "confidence": 1.0, "probabilities": {best_move: 1.0}}

        # Fallback if chosen move is unsafe
        if chosen_move not in safe_moves:
            best_fallback = min(safe_moves, key=lambda m: move_scores.get(m, (999, 0, 999)))
            actual_move = best_fallback
        else:
            actual_move = chosen_move

        decision_meta = {
            "laya_choice": chosen_move,
            "actual_move": actual_move,
            "confidence": confidence,
            "probabilities": probabilities,
        }
        self.last_ai_decision = decision_meta
        return actual_move, decision_meta

    def step(self, move: str):
        """Execute one game step with chosen direction."""
        if not self.is_safe_move(move):
            self.is_game_over = True
            return

        self.current_direction = move
        dx, dy = DIRECTIONS[move]
        head_x, head_y = self.snake[0]
        new_head = (head_x + dx, head_y + dy)

        # Move snake
        self.snake.appendleft(new_head)
        self.steps += 1

        # Check if target is eaten
        if new_head == self.target:
            self.score += 1
            if self.score > self.high_score:
                self.high_score = self.score
            self.target = self._spawn_target()
        else:
            # Pop tail if no food eaten
            self.snake.pop()

    def render(self, header_msg: Optional[str] = None):
        """Render the 20x20 field and dashboard to stdout."""
        lines = []
        lines.append(f"{CURSOR_HOME}")
        
        # Title Banner
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}╔══════════════════════════════════════════════════════════╗{COLOR_RESET}")
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}║                🐍 LAYA AI SNAKE GAME (20x20)             ║{COLOR_RESET}")
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}╚══════════════════════════════════════════════════════════╝{COLOR_RESET}")

        if header_msg:
            lines.append(f" {header_msg}")
        else:
            lines.append(f" {COLOR_YELLOW}Playing autonomously with Laya Agent | Press Ctrl+C to Stop{COLOR_RESET}")

        # Render 20x20 Field
        occupied = set(self.snake)
        head = self.snake[0] if self.snake else (-1, -1)

        lines.append(f"{COLOR_BOLD}┌" + "──" * self.width + "┐" + COLOR_RESET)
        for y in range(self.height):
            row_str = ["│"]
            for x in range(self.width):
                pos = (x, y)
                if pos == head:
                    # Directional head indicator
                    head_char = {
                        "UP": "▲ ",
                        "DOWN": "▼ ",
                        "LEFT": "◄ ",
                        "RIGHT": "► "
                    }.get(self.current_direction, "🟢")
                    row_str.append(f"{COLOR_BRIGHT_GREEN}{COLOR_BOLD}{head_char}{COLOR_RESET}")
                elif pos in occupied:
                    row_str.append(f"{COLOR_GREEN}■ {COLOR_RESET}")
                elif pos == self.target:
                    row_str.append(f"{COLOR_RED}{COLOR_BOLD}★ {COLOR_RESET}")
                else:
                    row_str.append(f"{COLOR_GRAY}· {COLOR_RESET}")
            row_str.append("│")
            lines.append("".join(row_str))
        lines.append(f"{COLOR_BOLD}└" + "──" * self.width + "┘" + COLOR_RESET)

        # Telemetry & Stats Dashboard
        lines.append(
            f"{COLOR_BOLD}Game #{self.game_count:<3} | Score: {COLOR_YELLOW}{self.score:<3}{COLOR_RESET}{COLOR_BOLD} | "
            f"Length: {COLOR_GREEN}{len(self.snake):<3}{COLOR_RESET}{COLOR_BOLD} | "
            f"High Score: {COLOR_CYAN}{self.high_score:<3}{COLOR_RESET}{COLOR_BOLD} | "
            f"Steps: {self.steps:<4}{COLOR_RESET}"
        )

        # AI Decision Info
        laya_choice = self.last_ai_decision.get("laya_choice", self.current_direction)
        confidence = self.last_ai_decision.get("confidence", 0.0)
        probs = self.last_ai_decision.get("probabilities", {})

        prob_str = " | ".join(
            f"{d}: {probs.get(d, 0.0):.1%}" for d in ["UP", "DOWN", "LEFT", "RIGHT"]
        ) if probs else "N/A"

        lines.append(
            f"Laya Decision : {COLOR_BOLD}{COLOR_BRIGHT_GREEN}{laya_choice:<5}{COLOR_RESET} "
            f"(Confidence: {COLOR_YELLOW}{confidence:.2f}{COLOR_RESET})"
        )
        lines.append(f"Probabilities : {COLOR_GRAY}{prob_str}{COLOR_RESET}")
        lines.append(
            f"Head at ({head[0]:2d},{head[1]:2d}) → Target at ({self.target[0]:2d},{self.target[1]:2d})"
        )

        # Write to stdout at once for clean rendering
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def run_countdown(self, seconds: int = 5):
        """Show initial countdown from 5 to 0 seconds before game starts."""
        for remaining in range(seconds, -1, -1):
            msg = (
                f"{COLOR_BOLD}{COLOR_YELLOW}⏱️  Game starts in {COLOR_RED}{remaining}{COLOR_YELLOW} seconds... "
                f"{'(Get Ready!)' if remaining > 0 else '(GO!)'}{COLOR_RESET}"
            )
            self.render(header_msg=msg)
            time.sleep(1.0)

    def play(self, step_delay: float = 0.05):
        """Main game loop running continuously until stopped by user (Ctrl+C)."""
        # Hide cursor for smooth terminal graphics
        sys.stdout.write(CLEAR_SCREEN + HIDE_CURSOR)
        sys.stdout.flush()

        try:
            # 1. Countdown from 5 to 0 seconds
            self.run_countdown(5)

            # 2. Continuous game loop
            while True:
                if self.is_game_over:
                    # Show Game Over briefly then restart
                    self.render(
                        header_msg=f"{COLOR_RED}{COLOR_BOLD}💥 GAME OVER! Score: {self.score}. Respawning new game...{COLOR_RESET}"
                    )
                    time.sleep(1.5)
                    self.reset_game()
                    continue

                # Laya AI decides next move
                move, _ = self.decide_move_with_laya()
                
                # Execute step
                self.step(move)

                # Render current state
                self.render()

                # Animation delay
                time.sleep(step_delay)

        except KeyboardInterrupt:
            # Handle Ctrl+C gracefully
            pass
        finally:
            # Restore cursor and clear formatting
            sys.stdout.write(SHOW_CURSOR + COLOR_RESET + "\n\n")
            print(f"{COLOR_BOLD}{COLOR_CYAN}Game stopped by user. Final High Score: {self.high_score}. Thanks for playing!{COLOR_RESET}\n")
            sys.stdout.flush()


def main():
    print("Loading Laya AI model (fast mode)...")
    agent = laya.load("convaiinnovations/laya", fast=True)
    game = SnakeGame(agent=agent)
    game.play(step_delay=0.02)


if __name__ == "__main__":
    main()
