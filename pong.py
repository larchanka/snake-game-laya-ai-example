#!/usr/bin/env python3
"""
Player vs Computer (PvC) Pong Game against Laya AI.
High-speed 60-FPS engine with multithreaded real-time Laya AI paddle navigation.
"""

import sys
import os
import time
import random
import select
import tty
import termios
import threading
import warnings
from typing import Dict, Tuple, Optional

# Suppress temperature warnings from laya
warnings.filterwarnings("ignore")

import laya

# Court Constants
COURT_WIDTH = 56
COURT_HEIGHT = 18
PADDLE_HEIGHT = 4

# Colors & ANSI Sequences
CLEAR_SCREEN = "\033[2J"
CURSOR_HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_CYAN = "\033[96m"
COLOR_YELLOW = "\033[93m"
COLOR_GREEN = "\033[92m"
COLOR_MAGENTA = "\033[95m"
COLOR_RED = "\033[91m"
COLOR_GRAY = "\033[90m"
COLOR_WHITE = "\033[97m"


class PongGame:
    def __init__(self, agent: Optional[laya.Agent] = None):
        self.width = COURT_WIDTH
        self.height = COURT_HEIGHT
        self.paddle_height = PADDLE_HEIGHT

        # Initialize Laya Agent (fast mode)
        self.agent = agent if agent is not None else laya.load("convaiinnovations/laya", fast=True)

        # Player (Left) and AI (Right) paddle positions (top Y coordinate)
        self.player_x = 2
        self.ai_x = self.width - 3
        
        self.player_score = 0
        self.ai_score = 0
        self.rally_count = 0
        self.high_rally = 0
        self.game_speed_name = "Fast (60 FPS)"
        self.base_speed = 1.3

        # AI decision state & thread synchronization
        self.ai_action = "STAY"
        self.ai_confidence = 0.0
        self.ai_probs = {}
        self.state_lock = threading.Lock()
        self.running = True

        self.reset_round(serve_to_player=random.choice([True, False]))

        # Start Background AI Worker Thread for non-blocking high-speed gameplay
        self.ai_thread = threading.Thread(target=self._ai_worker_loop, daemon=True)
        self.ai_thread.start()

    def reset_round(self, serve_to_player: bool = True):
        """Reset ball and paddles for a new round."""
        with self.state_lock:
            self.player_y = (self.height - self.paddle_height) // 2
            self.ai_y = (self.height - self.paddle_height) // 2

            self.ball_x = float(self.width // 2)
            self.ball_y = float(self.height // 2)

            # Serve ball at brisk speed
            dir_x = -1.0 if serve_to_player else 1.0
            self.vx = dir_x * self.base_speed
            self.vy = random.choice([-0.7, -0.4, 0.4, 0.7])
            self.rally_count = 0

    def predict_ball_intercept(self, bx: float, by: float, vx: float, vy: float) -> float:
        """Simulate ball trajectory to predict where it reaches AI paddle line (x = ai_x)."""
        if vx <= 0:
            # Ball moving towards player, track ball height or center
            return float(by)

        sim_x = bx
        sim_y = by
        sim_vx = vx
        sim_vy = vy

        max_steps = 80
        steps = 0
        while sim_x < self.ai_x and steps < max_steps:
            steps += 1
            sim_x += sim_vx
            sim_y += sim_vy

            if sim_y <= 0:
                sim_y = -sim_y
                sim_vy = -sim_vy
            elif sim_y >= self.height - 1:
                sim_y = 2 * (self.height - 1) - sim_y
                sim_vy = -sim_vy

        return max(0.0, min(float(self.height - 1), sim_y))

    def _ai_worker_loop(self):
        """Background worker thread continuously running Laya AI decision inference."""
        while self.running:
            with self.state_lock:
                bx, by = self.ball_x, self.ball_y
                vx, vy = self.vx, self.vy
                ai_y = self.ai_y

            intercept_y = self.predict_ball_intercept(bx, by, vx, vy)
            ai_center_y = ai_y + (self.paddle_height - 1) / 2.0
            diff = intercept_y - ai_center_y

            if diff < -0.8:
                needed = "UP"
                reason = f"Ball target Y={intercept_y:.1f} is above paddle center Y={ai_center_y:.1f}. Paddle must move UP."
            elif diff > 0.8:
                needed = "DOWN"
                reason = f"Ball target Y={intercept_y:.1f} is below paddle center Y={ai_center_y:.1f}. Paddle must move DOWN."
            else:
                needed = "STAY"
                reason = f"Ball target Y={intercept_y:.1f} is aligned with paddle center Y={ai_center_y:.1f}. Paddle should hold position."

            state = {
                "ball_target_y": f"{intercept_y:.1f}",
                "ai_paddle_center_y": f"{ai_center_y:.1f}",
                "analysis": reason,
                "recommended_action": needed
            }

            questions = {
                "ai_action": {
                    "type": "choice",
                    "instructions": f"The target ball position is Y={intercept_y:.1f} and paddle center is at Y={ai_center_y:.1f}. Which direction should the paddle move?",
                    "criteria": {
                        "UP": "Move paddle up towards top of court to intercept high ball",
                        "DOWN": "Move paddle down towards bottom of court to intercept low ball",
                        "STAY": "Hold paddle in current position (ball is already aligned)"
                    }
                }
            }

            try:
                res = self.agent.predict(state, questions)
                ans = res.get("answers", {}).get("ai_action", {})
                choice = ans.get("choice", needed)
                conf = ans.get("confidence", 0.0)
                probs = ans.get("probabilities", {})
            except Exception:
                choice = needed
                conf = 1.0
                probs = {choice: 1.0}

            with self.state_lock:
                self.ai_action = choice
                self.ai_confidence = conf
                self.ai_probs = probs

            # Micro sleep to yield thread
            time.sleep(0.005)

    def apply_ai_move(self):
        """Apply AI action to paddle in the main physics loop."""
        with self.state_lock:
            choice = self.ai_action
            if choice == "UP" and self.ai_y > 0:
                self.ai_y -= 1
            elif choice == "DOWN" and self.ai_y + self.paddle_height < self.height:
                self.ai_y += 1

    def move_player(self, delta: int):
        """Move player paddle up (-1) or down (+1)."""
        with self.state_lock:
            new_y = self.player_y + delta
            if 0 <= new_y <= self.height - self.paddle_height:
                self.player_y = new_y

    def update_physics(self) -> Optional[str]:
        """Update ball position and handle collisions."""
        with self.state_lock:
            self.ball_x += self.vx
            self.ball_y += self.vy

            # Wall Bounce (Top/Bottom)
            if self.ball_y <= 0:
                self.ball_y = 0.0
                self.vy = abs(self.vy)
            elif self.ball_y >= self.height - 1:
                self.ball_y = float(self.height - 1)
                self.vy = -abs(self.vy)

            int_bx = int(round(self.ball_x))
            int_by = int(round(self.ball_y))

            # Player Paddle Collision (Left)
            if int_bx <= self.player_x and self.player_y <= int_by < self.player_y + self.paddle_height:
                if self.vx < 0:
                    # Accelerate ball slightly on return
                    speed = min(2.4, abs(self.vx) * 1.04)
                    self.vx = speed
                    hit_offset = int_by - (self.player_y + (self.paddle_height - 1) / 2.0)
                    self.vy = hit_offset * 0.4 + random.uniform(-0.1, 0.1)
                    self.rally_count += 1
                    if self.rally_count > self.high_rally:
                        self.high_rally = self.rally_count

            # AI Paddle Collision (Right)
            if int_bx >= self.ai_x and self.ai_y <= int_by < self.ai_y + self.paddle_height:
                if self.vx > 0:
                    speed = min(2.4, abs(self.vx) * 1.04)
                    self.vx = -speed
                    hit_offset = int_by - (self.ai_y + (self.paddle_height - 1) / 2.0)
                    self.vy = hit_offset * 0.4 + random.uniform(-0.1, 0.1)
                    self.rally_count += 1
                    if self.rally_count > self.high_rally:
                        self.high_rally = self.rally_count

            # Point Scored
            if self.ball_x < 0:
                self.ai_score += 1
                return "AI"
            elif self.ball_x >= self.width:
                self.player_score += 1
                return "PLAYER"

            return None

    def render(self, header_note: Optional[str] = None):
        """Render the Pong court and HUD to stdout."""
        lines = []
        lines.append(f"{CURSOR_HOME}")

        # Banner
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}╔════════════════════════════════════════════════════════════╗{COLOR_RESET}")
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}║         🏓 FAST REAL-TIME PLAYER vs LAYA AI PONG           ║{COLOR_RESET}")
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}╚════════════════════════════════════════════════════════════╝{COLOR_RESET}")

        with self.state_lock:
            pscore = self.player_score
            ascore = self.ai_score
            rally = self.rally_count
            hrally = self.high_rally
            py = self.player_y
            ay = self.ai_y
            bx = self.ball_x
            by = self.ball_y
            action = self.ai_action
            conf = self.ai_confidence
            probs = self.ai_probs

        # Scoreboard
        lines.append(
            f" {COLOR_BOLD}{COLOR_GREEN}PLAYER [You]: {pscore:<2}{COLOR_RESET} "
            f"  {COLOR_BOLD}{COLOR_GRAY}│{COLOR_RESET}   "
            f"{COLOR_BOLD}{COLOR_MAGENTA}LAYA AI: {ascore:<2}{COLOR_RESET} "
            f"  {COLOR_BOLD}{COLOR_GRAY}│{COLOR_RESET}   "
            f"Rally: {COLOR_YELLOW}{rally:<2}{COLOR_RESET} (Best: {hrally}) | Mode: {COLOR_CYAN}{self.game_speed_name}{COLOR_RESET}"
        )

        if header_note:
            lines.append(f" {header_note}")
        else:
            lines.append(f" {COLOR_GRAY}Controls: [W/S] or [↑/↓] Move Paddle | [Q] Quit | [R] Reset{COLOR_RESET}")

        # Court Top Border
        lines.append(f"{COLOR_BOLD}┌" + "─" * self.width + "┐" + COLOR_RESET)

        int_bx = int(round(bx))
        int_by = int(round(by))
        mid_x = self.width // 2

        # Court Rows
        for y in range(self.height):
            row = ["│"]
            for x in range(self.width):
                # Player Paddle (Left)
                if x == self.player_x and py <= y < py + self.paddle_height:
                    row.append(f"{COLOR_BOLD}{COLOR_GREEN}█{COLOR_RESET}")
                # AI Paddle (Right)
                elif x == self.ai_x and ay <= y < ay + self.paddle_height:
                    row.append(f"{COLOR_BOLD}{COLOR_MAGENTA}█{COLOR_RESET}")
                # Ball
                elif x == int_bx and y == int_by:
                    row.append(f"{COLOR_BOLD}{COLOR_WHITE}●{COLOR_RESET}")
                # Net
                elif x == mid_x:
                    row.append(f"{COLOR_GRAY}┆{COLOR_RESET}")
                else:
                    row.append(" ")
            row.append("│")
            lines.append("".join(row))

        # Court Bottom Border
        lines.append(f"{COLOR_BOLD}└" + "─" * self.width + "┘" + COLOR_RESET)

        prob_str = " | ".join(
            f"{act}: {probs.get(act, 0.0):.1%}" for act in ["UP", "DOWN", "STAY"]
        ) if probs else "N/A"

        lines.append(
            f"Laya AI Move  : {COLOR_BOLD}{COLOR_MAGENTA}{action:<5}{COLOR_RESET} "
            f"(Confidence: {COLOR_YELLOW}{conf:.2f}{COLOR_RESET})"
        )
        lines.append(f"Probabilities : {COLOR_GRAY}{prob_str}{COLOR_RESET}")

        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def run_countdown(self, seconds: int = 3):
        """Short countdown before game start."""
        for remaining in range(seconds, -1, -1):
            msg = f"{COLOR_BOLD}{COLOR_YELLOW}Match starts in {COLOR_RED}{remaining}{COLOR_YELLOW}s... {'(Get Ready!)' if remaining > 0 else '(PLAY!)'}{COLOR_RESET}"
            self.render(header_note=msg)
            time.sleep(1.0)


def read_key_nonblocking() -> Optional[str]:
    """Read a single keypress without blocking the terminal."""
    if select.select([sys.stdin], [], [], 0)[0]:
        ch = sys.stdin.read(1)
        if ch == "\033":
            # Handle escape sequences (e.g. arrow keys)
            if select.select([sys.stdin], [], [], 0.02)[0]:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    if select.select([sys.stdin], [], [], 0.02)[0]:
                        ch3 = sys.stdin.read(1)
                        if ch3 == "A":
                            return "UP"
                        elif ch3 == "B":
                            return "DOWN"
        return ch
    return None


def main():
    print("Loading Laya AI model (fast mode)...")
    agent = laya.load("convaiinnovations/laya", fast=True)
    game = PongGame(agent=agent)

    # Setup raw non-blocking terminal
    fd = sys.stdin.fileno()
    old_term_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    sys.stdout.write(CLEAR_SCREEN + HIDE_CURSOR)
    sys.stdout.flush()

    try:
        game.run_countdown(3)

        ai_paddle_move_interval = 0.03
        last_ai_paddle_move = 0.0

        # High-performance 60 FPS loop
        target_fps = 60
        frame_duration = 1.0 / target_fps

        while True:
            frame_start = time.time()

            # 1. Non-blocking Player Input (Instant response)
            while True:
                key = read_key_nonblocking()
                if not key:
                    break
                if key in ["q", "Q", "\x03"]:  # 'q' or Ctrl+C
                    game.running = False
                    return
                elif key in ["w", "W", "UP", "k"]:
                    game.move_player(-1)
                elif key in ["s", "S", "DOWN", "j"]:
                    game.move_player(1)
                elif key in ["r", "R"]:
                    game.player_score = 0
                    game.ai_score = 0
                    game.reset_round()

            # 2. Update AI Paddle Position smoothly
            now = time.time()
            if now - last_ai_paddle_move >= ai_paddle_move_interval:
                last_ai_paddle_move = now
                game.apply_ai_move()

            # 3. Update Ball Physics
            scorer = game.update_physics()
            if scorer:
                winner_text = (
                    f"{COLOR_GREEN}{COLOR_BOLD}POINT PLAYER! 🎉{COLOR_RESET}"
                    if scorer == "PLAYER"
                    else f"{COLOR_MAGENTA}{COLOR_BOLD}POINT LAYA AI! 🤖{COLOR_RESET}"
                )
                game.render(header_note=winner_text)
                time.sleep(0.8)
                game.reset_round(serve_to_player=(scorer == "AI"))

            # 4. Render Frame (smooth 60 FPS)
            game.render()

            # 5. Precise Frame Rate Sleep
            elapsed = time.time() - frame_start
            sleep_time = max(0.001, frame_duration - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass
    finally:
        game.running = False
        # Restore terminal settings
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term_settings)
        sys.stdout.write(SHOW_CURSOR + COLOR_RESET + "\n\n")
        print(f"{COLOR_BOLD}{COLOR_CYAN}Game exited. Final Score - Player: {game.player_score} | Laya AI: {game.ai_score}{COLOR_RESET}\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
