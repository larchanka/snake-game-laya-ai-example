#!/usr/bin/env python3
"""
Checkers (Draughts) Game vs Laya AI.
Play against Laya AI on an 8x8 board in your terminal.
"""

import sys
import os
import copy
import warnings
from typing import List, Tuple, Dict, Optional, Any

# Suppress temperature warnings from laya
warnings.filterwarnings("ignore")

import laya

# Colors & ANSI Sequences
CLEAR_SCREEN = "\033[2J"
CURSOR_HOME = "\033[H"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_CYAN = "\033[96m"
COLOR_YELLOW = "\033[93m"
COLOR_GREEN = "\033[92m"
COLOR_MAGENTA = "\033[95m"
COLOR_RED = "\033[91m"
COLOR_GRAY = "\033[90m"
COLOR_WHITE = "\033[97m"
BG_DARK = "\033[48;5;236m"
BG_LIGHT = "\033[48;5;238m"

# Piece Constants
EMPTY = 0
PLAYER_MAN = 1     # 🔴 Player Man (moves UP)
PLAYER_KING = 2    # 👑 Player King (moves UP/DOWN)
AI_MAN = -1        # 🔵 AI Man (moves DOWN)
AI_KING = -2       # 💎 AI King (moves UP/DOWN)

PLAYER_SIDE = 1
AI_SIDE = -1


class CheckersGame:
    def __init__(self, agent: Optional[laya.Agent] = None):
        self.agent = agent if agent is not None else laya.load("convaiinnovations/laya", fast=True)
        self.board = self._init_board()
        self.current_turn = PLAYER_SIDE  # Player moves first
        self.move_history: List[str] = []
        self.last_ai_decision: Dict[str, Any] = {}
        self.game_over = False
        self.winner = None

    def _init_board(self) -> List[List[int]]:
        """Initialize standard 8x8 checkers board."""
        board = [[EMPTY for _ in range(8)] for _ in range(8)]
        # Rows 0-2: AI pieces
        for r in range(3):
            for c in range(8):
                if (r + c) % 2 == 1:
                    board[r][c] = AI_MAN
        # Rows 5-7: Player pieces
        for r in range(5, 8):
            for c in range(8):
                if (r + c) % 2 == 1:
                    board[r][c] = PLAYER_MAN
        return board

    def get_piece_count(self) -> Tuple[int, int, int, int]:
        """Return (player_men, player_kings, ai_men, ai_kings)."""
        p_men, p_kings, ai_men, ai_kings = 0, 0, 0, 0
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p == PLAYER_MAN:
                    p_men += 1
                elif p == PLAYER_KING:
                    p_kings += 1
                elif p == AI_MAN:
                    ai_men += 1
                elif p == AI_KING:
                    ai_kings += 1
        return p_men, p_kings, ai_men, ai_kings

    def pos_to_notation(self, r: int, c: int) -> str:
        """Convert (row, col) (0-7, 0-7) to algebraic notation (e.g. A3, C5)."""
        col_char = chr(ord('A') + c)
        row_num = 8 - r  # Row 8 is top, Row 1 is bottom
        return f"{col_char}{row_num}"

    def notation_to_pos(self, not_str: str) -> Optional[Tuple[int, int]]:
        """Convert notation (e.g. 'C3', 'c3') to (row, col)."""
        not_str = not_str.strip().upper()
        if len(not_str) != 2:
            return None
        c_char, r_char = not_str[0], not_str[1]
        if not ('A' <= c_char <= 'H') or not ('1' <= r_char <= '8'):
            return None
        c = ord(c_char) - ord('A')
        r = 8 - int(r_char)
        return r, c

    def move_to_string(self, move: Dict[str, Any]) -> str:
        """Format move as 'C3-D4' or 'C3xExG7' for captures."""
        path = move["path"]
        sep = "x" if move.get("is_capture") else "-"
        return sep.join(self.pos_to_notation(r, c) for r, c in path)

    def is_opponent(self, piece: int, side: int) -> bool:
        """Check if a piece belongs to the opponent of `side`."""
        if side == PLAYER_SIDE:
            return piece < 0
        else:
            return piece > 0

    def is_own_piece(self, piece: int, side: int) -> bool:
        """Check if a piece belongs to `side`."""
        if side == PLAYER_SIDE:
            return piece > 0
        else:
            return piece < 0

    def _get_capture_chains(self, board: List[List[int]], r: int, c: int, piece: int, side: int) -> List[Dict[str, Any]]:
        """Recursively find all multi-jump capture paths for a piece."""
        is_king = abs(piece) == 2
        if is_king:
            directions = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        elif side == PLAYER_SIDE:
            directions = [(-1, -1), (-1, 1)]
        else:
            directions = [(1, -1), (1, 1)]

        chains = []

        for dr, dc in directions:
            mid_r, mid_c = r + dr, c + dc
            land_r, land_c = r + 2 * dr, c + 2 * dc

            if 0 <= land_r < 8 and 0 <= land_c < 8:
                mid_piece = board[mid_r][mid_c]
                land_piece = board[land_r][land_c]

                if self.is_opponent(mid_piece, side) and land_piece == EMPTY:
                    # Execute this jump on a copy of board
                    next_board = [row[:] for row in board]
                    next_board[r][c] = EMPTY
                    next_board[mid_r][mid_c] = EMPTY
                    
                    # Promotion check during chain
                    next_piece = piece
                    if side == PLAYER_SIDE and land_r == 0:
                        next_piece = PLAYER_KING
                    elif side == AI_SIDE and land_r == 7:
                        next_piece = AI_KING
                    next_board[land_r][land_c] = next_piece

                    # Check for continuation jumps
                    sub_chains = self._get_capture_chains(next_board, land_r, land_c, next_piece, side)
                    if sub_chains:
                        for sc in sub_chains:
                            chains.append({
                                "from": (r, c),
                                "to": sc["to"],
                                "path": [(r, c)] + sc["path"],
                                "captured": [(mid_r, mid_c)] + sc["captured"],
                                "is_capture": True,
                                "is_king_promotion": (abs(piece) != 2 and abs(next_piece) == 2) or sc.get("is_king_promotion", False)
                            })
                    else:
                        chains.append({
                            "from": (r, c),
                            "to": (land_r, land_c),
                            "path": [(r, c), (land_r, land_c)],
                            "captured": [(mid_r, mid_c)],
                            "is_capture": True,
                            "is_king_promotion": (abs(piece) != 2 and abs(next_piece) == 2)
                        })

        return chains

    def get_legal_moves(self, side: int) -> List[Dict[str, Any]]:
        """Get all legal moves for `side`. If captures exist, only captures are allowed."""
        captures = []
        regular_moves = []

        for r in range(8):
            for c in range(8):
                piece = self.board[r][c]
                if not self.is_own_piece(piece, side):
                    continue

                # Check captures
                chains = self._get_capture_chains(self.board, r, c, piece, side)
                captures.extend(chains)

                # Check regular 1-step moves
                if not captures:
                    is_king = abs(piece) == 2
                    if is_king:
                        directions = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
                    elif side == PLAYER_SIDE:
                        directions = [(-1, -1), (-1, 1)]
                    else:
                        directions = [(1, -1), (1, 1)]

                    for dr, dc in directions:
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < 8 and 0 <= nc < 8 and self.board[nr][nc] == EMPTY:
                            is_promo = (side == PLAYER_SIDE and nr == 0) or (side == AI_SIDE and nr == 7)
                            regular_moves.append({
                                "from": (r, c),
                                "to": (nr, nc),
                                "path": [(r, c), (nr, nc)],
                                "captured": [],
                                "is_capture": False,
                                "is_king_promotion": is_promo and not is_king
                            })

        # Mandatory captures rule
        if captures:
            return captures
        return regular_moves

    def apply_move(self, move: Dict[str, Any], side: int):
        """Apply a move to the board."""
        from_r, from_c = move["from"]
        to_r, to_c = move["to"]
        piece = self.board[from_r][from_c]

        self.board[from_r][from_c] = EMPTY
        for cap_r, cap_c in move.get("captured", []):
            self.board[cap_r][cap_c] = EMPTY

        # King promotion
        if side == PLAYER_SIDE and to_r == 0 and piece == PLAYER_MAN:
            piece = PLAYER_KING
        elif side == AI_SIDE and to_r == 7 and piece == AI_MAN:
            piece = AI_KING

        self.board[to_r][to_c] = piece
        move_str = self.move_to_string(move)
        side_name = "Player" if side == PLAYER_SIDE else "Laya AI"
        self.move_history.append(f"{side_name}: {move_str}")

        # Switch turn
        self.current_turn = -side

        # Check win/loss
        next_moves = self.get_legal_moves(self.current_turn)
        if not next_moves:
            self.game_over = True
            self.winner = side

    def render(self, note: Optional[str] = None):
        """Render board, pieces, and HUD to stdout."""
        lines = []
        lines.append(f"{CURSOR_HOME}")

        # Title
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}╔════════════════════════════════════════════════════════════╗{COLOR_RESET}")
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}║             👑 CHECKERS vs LAYA AI (8x8)                   ║{COLOR_RESET}")
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}╚════════════════════════════════════════════════════════════╝{COLOR_RESET}")

        p_men, p_kings, ai_men, ai_kings = self.get_piece_count()
        total_p = p_men + p_kings
        total_ai = ai_men + ai_kings

        # Status Bar
        lines.append(
            f" {COLOR_BOLD}{COLOR_GREEN}PLAYER [🔴]: {total_p} (Kings: {p_kings}){COLOR_RESET} "
            f"  {COLOR_BOLD}{COLOR_GRAY}│{COLOR_RESET}   "
            f"{COLOR_BOLD}{COLOR_MAGENTA}LAYA AI [🔵]: {total_ai} (Kings: {ai_kings}){COLOR_RESET} "
            f"  {COLOR_BOLD}{COLOR_GRAY}│{COLOR_RESET}   "
            f"Turn: {COLOR_YELLOW}{'YOUR TURN (Player)' if self.current_turn == PLAYER_SIDE else 'LAYA AI THINKING...'}{COLOR_RESET}"
        )

        if note:
            lines.append(f" {note}")
        else:
            lines.append(f" {COLOR_GRAY}Legend: 🔴 Player Man | 👑 Player King | 🔵 AI Man | 💎 AI King{COLOR_RESET}")

        lines.append("")
        lines.append("     A   B   C   D   E   F   G   H  ")
        lines.append("   ┌───┬───┬───┬───┬───┬───┬───┬───┐")

        for r in range(8):
            row_num = 8 - r
            row_cells = [f" {row_num} │"]
            for c in range(8):
                piece = self.board[r][c]
                is_dark = (r + c) % 2 == 1

                if piece == PLAYER_MAN:
                    glyph = f"{COLOR_RED}{COLOR_BOLD}🔴{COLOR_RESET}"
                elif piece == PLAYER_KING:
                    glyph = f"{COLOR_YELLOW}{COLOR_BOLD}👑{COLOR_RESET}"
                elif piece == AI_MAN:
                    glyph = f"{COLOR_CYAN}{COLOR_BOLD}🔵{COLOR_RESET}"
                elif piece == AI_KING:
                    glyph = f"{COLOR_MAGENTA}{COLOR_BOLD}💎{COLOR_RESET}"
                elif is_dark:
                    glyph = f"{COLOR_GRAY} ·{COLOR_RESET}"
                else:
                    glyph = "  "

                row_cells.append(f" {glyph}│")
            row_cells.append(f" {row_num}")
            lines.append("".join(row_cells))
            if r < 7:
                lines.append("   ├───┼───┼───┼───┼───┼───┼───┼───┤")
            else:
                lines.append("   └───┴───┴───┴───┴───┴───┴───┴───┘")
        lines.append("     A   B   C   D   E   F   G   H  ")
        lines.append("")

        # AI Telemetry Info
        if self.last_ai_decision:
            chosen = self.last_ai_decision.get("choice_name", "N/A")
            conf = self.last_ai_decision.get("confidence", 0.0)
            probs = self.last_ai_decision.get("probabilities", {})
            prob_str = " | ".join(f"{k}: {v:.1%}" for k, v in list(probs.items())[:4])
            lines.append(f"Laya AI Last Decision: {COLOR_BOLD}{COLOR_MAGENTA}{chosen}{COLOR_RESET} (Confidence: {COLOR_YELLOW}{conf:.2f}{COLOR_RESET})")
            if prob_str:
                lines.append(f"AI Candidate Probs   : {COLOR_GRAY}{prob_str}{COLOR_RESET}")

        if self.move_history:
            recent_moves = self.move_history[-4:]
            lines.append(f"Recent Moves         : {', '.join(recent_moves)}")

        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def evaluate_move_tactics(self, move: Dict[str, Any], side: int) -> str:
        """Build descriptive criteria string for a candidate move."""
        move_str = self.move_to_string(move)
        caps = len(move.get("captured", []))
        is_promo = move.get("is_king_promotion", False)
        to_r, to_c = move["to"]
        from_r, from_c = move["from"]

        desc = []
        if caps > 1:
            desc.append(f"MULTI-JUMP CAPTURE! Jumps over and captures {caps} enemy pieces landing at {self.pos_to_notation(to_r, to_c)} (Huge material gain).")
        elif caps == 1:
            desc.append(f"JUMP CAPTURE: Captures 1 enemy piece landing at {self.pos_to_notation(to_r, to_c)} (Material gain).")
        
        if is_promo:
            desc.append(f"PROMOTION: Piece crowns into KING at {self.pos_to_notation(to_r, to_c)}!")

        if not caps:
            # Advance towards center / king row
            if 2 <= to_r <= 5 and 2 <= to_c <= 5:
                desc.append(f"Center control: Moves from {self.pos_to_notation(from_r, from_c)} to center square {self.pos_to_notation(to_r, to_c)}.")
            else:
                desc.append(f"Advance: Moves from {self.pos_to_notation(from_r, from_c)} to {self.pos_to_notation(to_r, to_c)}.")

        return f"{move_str}: " + " ".join(desc)

    def decide_ai_move_with_laya(self) -> Dict[str, Any]:
        """Query Laya AI to select the optimal move among legal options."""
        legal_moves = self.get_legal_moves(AI_SIDE)
        if not legal_moves:
            return {}

        if len(legal_moves) == 1:
            # Only one legal move (forced)
            move = legal_moves[0]
            move_str = self.move_to_string(move)
            self.last_ai_decision = {
                "choice_name": move_str,
                "confidence": 1.0,
                "probabilities": {move_str: 1.0}
            }
            return move

        # Map each legal move to an option key
        criteria = {}
        option_map = {}
        for idx, m in enumerate(legal_moves):
            opt_key = f"MOVE_{idx+1}"
            move_str = self.move_to_string(m)
            crit_text = self.evaluate_move_tactics(m, AI_SIDE)
            criteria[opt_key] = crit_text
            option_map[opt_key] = m

        p_men, p_kings, ai_men, ai_kings = self.get_piece_count()
        state = {
            "game": "Checkers (English Draughts 8x8)",
            "turn": "Laya AI (Moving DOWN towards Row 1)",
            "ai_pieces": f"{ai_men} Men, {ai_kings} Kings",
            "player_pieces": f"{p_men} Men, {p_kings} Kings",
            "situation": f"AI has {len(legal_moves)} legal moves available. Choose the best strategic move.",
        }

        questions = {
            "best_move": {
                "type": "choice",
                "instructions": "Which checkers move is strategically and tactically best for the AI?",
                "criteria": criteria
            }
        }

        try:
            res = self.agent.predict(state, questions)
            ans = res.get("answers", {}).get("best_move", {})
            choice_key = ans.get("choice")
            conf = ans.get("confidence", 0.0)
            probs = ans.get("probabilities", {})
        except Exception:
            choice_key = "MOVE_1"
            conf = 1.0
            probs = {"MOVE_1": 1.0}

        chosen_move = option_map.get(choice_key, legal_moves[0])
        chosen_move_str = self.move_to_string(chosen_move)

        # Map probabilities to move names for telemetry
        named_probs = {self.move_to_string(option_map[k]): v for k, v in probs.items() if k in option_map}

        self.last_ai_decision = {
            "choice_name": chosen_move_str,
            "confidence": conf,
            "probabilities": named_probs
        }
        return chosen_move

    def play(self):
        """Main interactive checkers game loop."""
        sys.stdout.write(CLEAR_SCREEN)
        sys.stdout.flush()

        while not self.game_over:
            if self.current_turn == PLAYER_SIDE:
                legal_moves = self.get_legal_moves(PLAYER_SIDE)
                if not legal_moves:
                    self.game_over = True
                    self.winner = AI_SIDE
                    break

                self.render()

                # Display legal moves list for easy selection
                print(f"{COLOR_BOLD}{COLOR_GREEN}Legal Moves for Player ({len(legal_moves)} available):{COLOR_RESET}")
                move_lookup: Dict[str, Dict[str, Any]] = {}

                for idx, m in enumerate(legal_moves, 1):
                    m_str = self.move_to_string(m)
                    cap_tag = f" {COLOR_RED}[CAPTURE]{COLOR_RESET}" if m.get("is_capture") else ""
                    promo_tag = f" {COLOR_YELLOW}[KING PROMO]{COLOR_RESET}" if m.get("is_king_promotion") else ""
                    print(f"  {COLOR_CYAN}{idx:2d}{COLOR_RESET}: {COLOR_BOLD}{m_str}{COLOR_RESET}{cap_tag}{promo_tag}")
                    move_lookup[str(idx)] = m
                    move_lookup[m_str.upper()] = m
                    move_lookup[m_str.upper().replace("-", " ")] = m
                    move_lookup[m_str.upper().replace("X", " ")] = m
                    move_lookup[m_str.upper().replace("-", "")] = m

                while True:
                    try:
                        user_input = input(f"\n{COLOR_BOLD}Enter move number or notation (e.g. 1, C3-D4, or 'q' to quit): {COLOR_RESET}").strip()
                    except (KeyboardInterrupt, EOFError):
                        print("\nGame exited by user.")
                        return

                    if user_input.lower() in ['q', 'quit', 'exit']:
                        print("\nGame ended by user.")
                        return

                    clean_key = user_input.upper()
                    if clean_key in move_lookup:
                        chosen_move = move_lookup[clean_key]
                        self.apply_move(chosen_move, PLAYER_SIDE)
                        break
                    else:
                        print(f"{COLOR_RED}Invalid move! Please select a valid move number (1-{len(legal_moves)}) or notation.{COLOR_RESET}")

            else:
                # Laya AI Turn
                self.render(note=f"{COLOR_YELLOW}Laya AI is evaluating the board and deciding move...{COLOR_RESET}")
                ai_move = self.decide_ai_move_with_laya()
                if not ai_move:
                    self.game_over = True
                    self.winner = PLAYER_SIDE
                    break

                self.apply_move(ai_move, AI_SIDE)

        # Game Over Screen
        self.render()
        if self.winner == PLAYER_SIDE:
            print(f"\n{COLOR_BOLD}{COLOR_GREEN}🏆 CONGRATULATIONS! YOU DEFEATED LAYA AI IN CHECKERS! 🎉{COLOR_RESET}\n")
        else:
            print(f"\n{COLOR_BOLD}{COLOR_MAGENTA}🤖 GAME OVER! LAYA AI WINS! Better luck next time!{COLOR_RESET}\n")


def main():
    print("Loading Laya AI model for Checkers...")
    agent = laya.load("convaiinnovations/laya", fast=True)
    game = CheckersGame(agent=agent)
    game.play()


if __name__ == "__main__":
    main()
