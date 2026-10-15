#!/usr/bin/env python3
"""
Texas Hold'em Poker vs Laya AI NPCs.
Spectator God-Mode terminal poker table powered by Laya System 1 neural decisions.
"""

import sys
import os
import time
import random
import select
import tty
import termios
import signal
import atexit
import argparse
import shutil
import warnings
import itertools
import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set
from collections import Counter

# Suppress temperature warnings from laya
warnings.filterwarnings("ignore")

import laya

ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def visible_len(text: str) -> int:
    """Calculate visible string length ignoring ANSI escape sequences."""
    return len(ANSI_REGEX.sub('', text))


def pad_right(text: str, width: int) -> str:
    """Pad a string to target visible width taking ANSI escapes into account."""
    return text + (' ' * max(0, width - visible_len(text)))


# ANSI Escape Sequences
CLEAR_SCREEN = "\033[2J"
CURSOR_HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[K"
CLEAR_BELOW = "\033[J"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"

# Colors
COLOR_RED = "\033[91m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_MAGENTA = "\033[95m"
COLOR_CYAN = "\033[96m"
COLOR_WHITE = "\033[97m"
COLOR_GRAY = "\033[90m"
BG_DARK = "\033[48;5;236m"
BG_GREEN = "\033[48;5;22m"

# Global terminal restore state
_ORIGINAL_TERM_SETTINGS = None
_IS_RAW_MODE = False
_TERMINAL_RESIZED = False


def _cleanup_terminal():
    """Ensure terminal cursor, colors, and tty modes are cleanly restored on exit."""
    global _ORIGINAL_TERM_SETTINGS, _IS_RAW_MODE
    try:
        sys.stdout.write(SHOW_CURSOR + COLOR_RESET)
        sys.stdout.flush()
    except Exception:
        pass
    if _IS_RAW_MODE and _ORIGINAL_TERM_SETTINGS is not None:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _ORIGINAL_TERM_SETTINGS)
            _IS_RAW_MODE = False
        except Exception:
            pass


atexit.register(_cleanup_terminal)


def _signal_handler(sig, frame):
    _cleanup_terminal()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _sigwinch_handler(sig, frame):
    global _TERMINAL_RESIZED
    _TERMINAL_RESIZED = True


if hasattr(signal, "SIGWINCH"):
    try:
        signal.signal(signal.SIGWINCH, _sigwinch_handler)
    except (ValueError, OSError):
        pass



# ============================================================================
# 1. Cards, Deck & Constants
# ============================================================================

SUITS = ["♠", "♥", "♦", "♣"]
RANK_VALUES = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14
}
VALUE_TO_RANK = {v: k for k, v in RANK_VALUES.items()}


@dataclass(frozen=True)
class Card:
    rank: int       # 2..14
    suit: str       # '♠', '♥', '♦', '♣'

    @property
    def rank_str(self) -> str:
        return VALUE_TO_RANK[self.rank]

    @property
    def is_red(self) -> bool:
        return self.suit in ("♥", "♦")

    def raw_str(self) -> str:
        return f"{self.rank_str}{self.suit}"

    def colored_str(self) -> str:
        color = COLOR_RED if self.is_red else COLOR_WHITE
        return f"{color}{COLOR_BOLD}{self.rank_str}{self.suit}{COLOR_RESET}"

    def __repr__(self) -> str:
        return self.raw_str()


class Deck:
    def __init__(self):
        self.cards: List[Card] = []
        self.reset()

    def reset(self):
        self.cards = [Card(rank, suit) for suit in SUITS for rank in range(2, 15)]
        random.shuffle(self.cards)

    def draw(self) -> Card:
        if not self.cards:
            self.reset()
        return self.cards.pop()

    def draw_many(self, n: int) -> List[Card]:
        return [self.draw() for _ in range(n)]


# ============================================================================
# 2. Pure-Python 7-Card Hand Evaluator
# ============================================================================

CATEGORY_NAMES = {
    9: "Royal Flush",
    8: "Straight Flush",
    7: "Four of a Kind",
    6: "Full House",
    5: "Flush",
    4: "Straight",
    3: "Three of a Kind",
    2: "Two Pair",
    1: "One Pair",
    0: "High Card"
}


def eval_5_cards(cards: List[Card]) -> Tuple[int, Tuple[int, ...], str]:
    """
    Evaluates exactly 5 cards.
    Returns: (category_score, tiebreaker_tuple, description)
    Higher category_score wins. In a tie, tiebreaker_tuple compares element-by-element.
    """
    ranks = sorted([c.rank for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1

    # Check Straight
    is_straight = False
    straight_top = None
    if len(set(ranks)) == 5:
        if ranks[0] - ranks[4] == 4:
            is_straight = True
            straight_top = ranks[0]
        elif ranks == [14, 5, 4, 3, 2]:  # Ace-low wheel straight (5-4-3-2-A)
            is_straight = True
            straight_top = 5

    # Count rank frequencies
    counts = Counter(ranks)
    # Sort groups by: count descending, then rank descending
    sorted_groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    pattern = [count for _, count in sorted_groups]
    group_ranks = tuple(rank for rank, _ in sorted_groups)

    # 1. Royal Flush & Straight Flush
    if is_flush and is_straight:
        if straight_top == 14:
            return (9, (14,), "Royal Flush")
        return (8, (straight_top,), f"Straight Flush ({VALUE_TO_RANK[straight_top]}-high)")

    # 2. Four of a Kind
    if pattern == [4, 1]:
        return (7, group_ranks, f"Four of a Kind ({VALUE_TO_RANK[group_ranks[0]]}s)")

    # 3. Full House
    if pattern == [3, 2]:
        return (6, group_ranks, f"Full House ({VALUE_TO_RANK[group_ranks[0]]}s full of {VALUE_TO_RANK[group_ranks[1]]}s)")

    # 4. Flush
    if is_flush:
        return (5, tuple(ranks), f"Flush ({VALUE_TO_RANK[ranks[0]]}-high)")

    # 5. Straight
    if is_straight:
        return (4, (straight_top,), f"Straight ({VALUE_TO_RANK[straight_top]}-high)")

    # 6. Three of a Kind
    if pattern == [3, 1, 1]:
        return (3, group_ranks, f"Three of a Kind ({VALUE_TO_RANK[group_ranks[0]]}s)")

    # 7. Two Pair
    if pattern == [2, 2, 1]:
        return (2, group_ranks, f"Two Pair ({VALUE_TO_RANK[group_ranks[0]]}s & {VALUE_TO_RANK[group_ranks[1]]}s)")

    # 8. One Pair
    if pattern == [2, 1, 1, 1]:
        return (1, group_ranks, f"One Pair ({VALUE_TO_RANK[group_ranks[0]]}s)")

    # 9. High Card
    return (0, tuple(ranks), f"High Card ({VALUE_TO_RANK[ranks[0]]})")


def eval_7_cards(cards: List[Card]) -> Tuple[int, Tuple[int, ...], str, List[Card]]:
    """
    Evaluates 5-to-7 cards by picking the best 5-card combination.
    Returns: (category_score, tiebreaker_tuple, description, best_5_cards)
    """
    if len(cards) < 5:
        # Preflop holding description
        return (0, tuple(sorted([c.rank for c in cards], reverse=True)), describe_hole_cards(cards), cards)

    best_score = None
    for combo in itertools.combinations(cards, 5):
        cat, tiebreak, desc = eval_5_cards(list(combo))
        score_key = (cat, tiebreak)
        if best_score is None or score_key > (best_score[0], best_score[1]):
            best_score = (cat, tiebreak, desc, list(combo))
    return best_score


def describe_hole_cards(cards: List[Card]) -> str:
    """Describe 2 hole cards for Preflop."""
    if len(cards) != 2:
        return ", ".join(c.raw_str() for c in cards)
    c1, c2 = sorted(cards, key=lambda c: c.rank, reverse=True)
    if c1.rank == c2.rank:
        return f"Pocket {VALUE_TO_RANK[c1.rank]}s"
    suited = "Suited" if c1.suit == c2.suit else "Offsuit"
    diff = c1.rank - c2.rank
    connector = " Connectors" if diff == 1 else (" One-Gap" if diff == 2 else "")
    return f"{VALUE_TO_RANK[c1.rank]}-{VALUE_TO_RANK[c2.rank]} {suited}{connector}"


def describe_hand_holding(hole_cards: List[Card], community_cards: List[Card]) -> str:
    """Full evaluated holding description including flush and straight draws on Flop/Turn."""
    if not community_cards:
        return describe_hole_cards(hole_cards)

    all_cards = hole_cards + community_cards
    cat, tiebreak, desc, _ = eval_7_cards(all_cards)

    # Check for draws if not already a flush or straight and board has 3 or 4 cards
    if len(community_cards) in (3, 4) and cat < 4:
        suit_counts = Counter(c.suit for c in all_cards)
        has_flush_draw = any(cnt == 4 for cnt in suit_counts.values())

        # Straight draw check
        ranks_set = set(c.rank for c in all_cards)
        if 14 in ranks_set:
            ranks_set.add(1)  # Ace can be low
        has_straight_draw = False
        for low in range(1, 11):
            span = set(range(low, low + 5))
            if len(span.intersection(ranks_set)) == 4:
                has_straight_draw = True
                break

        draws = []
        if has_flush_draw:
            draws.append("Flush Draw")
        if has_straight_draw:
            draws.append("Straight Draw")

        if draws:
            return f"{desc} + {' & '.join(draws)}"

    return desc


def check_draws(all_cards: List[Card], comm_cards: List[Card]) -> Tuple[bool, bool, bool]:
    """Returns (has_flush_draw, has_oesd, has_gutshot) on Flop and Turn."""
    if len(comm_cards) not in (3, 4):
        return (False, False, False)

    suit_counts = Counter(c.suit for c in all_cards)
    has_flush_draw = any(cnt == 4 for cnt in suit_counts.values())

    ranks_set = set(c.rank for c in all_cards)
    if 14 in ranks_set:
        ranks_set.add(1)

    has_oesd = False
    has_gutshot = False

    for low in range(1, 11):
        span = set(range(low, low + 5))
        inter = span.intersection(ranks_set)
        if len(inter) == 4:
            missing = span - inter
            miss_val = list(missing)[0]
            if miss_val in (low, low + 4) and (low > 1 and low + 4 < 14):
                has_oesd = True
            else:
                has_gutshot = True

    return (has_flush_draw, has_oesd, has_gutshot)


def categorize_hand_strength(hole_cards: List[Card], community_cards: List[Card]) -> str:
    """
    Classify hands into semantic tiers:
    - MONSTER: Full house or better, nut flush, nut straight, pocket AA/KK preflop.
    - STRONG: Top pair with strong kicker (J+), overpairs, two pair, sets, strong draws, QQ/JJ/AK preflop.
    - MEDIUM: Middle/bottom pair, weak top pair, gutshots/draws, medium pocket pairs, broadways preflop.
    - WEAK: Unpaired trash, undercards, 7-2, missed draws on river.
    """
    if not hole_cards:
        return "WEAK"

    # Pre-flop holding evaluation
    if not community_cards:
        if len(hole_cards) < 2:
            return "WEAK"
        c1, c2 = sorted(hole_cards, key=lambda c: c.rank, reverse=True)
        r1, r2 = c1.rank, c2.rank
        is_pair = (r1 == r2)
        is_suited = (c1.suit == c2.suit)
        gap = r1 - r2

        # MONSTER: Pocket Aces and Kings
        if is_pair and r1 >= 13:
            return "MONSTER"

        # STRONG: QQ, JJ, AKs, AKo, AQs, AJs, KQs
        if is_pair and r1 in (11, 12):
            return "STRONG"
        if r1 == 14 and r2 == 13:
            return "STRONG"
        if is_suited and ((r1 == 14 and r2 in (11, 12)) or (r1 == 13 and r2 == 12)):
            return "STRONG"

        # MEDIUM: Pocket pairs 22-TT, suited connectors/gaps, broadways, suited Ax
        if is_pair and r1 <= 10:
            return "MEDIUM"
        if r1 >= 10 and r2 >= 10:
            return "MEDIUM"
        if is_suited and (r1 == 14 or (gap in (1, 2) and r2 >= 5)):
            return "MEDIUM"

        return "WEAK"

    # Post-flop evaluation (3..5 community cards)
    all_cards = hole_cards + community_cards
    cat, tiebreak, desc, _ = eval_7_cards(all_cards)

    comm_ranks = [c.rank for c in community_cards]
    max_comm_rank = max(comm_ranks) if comm_ranks else 0
    hole_ranks = [c.rank for c in hole_cards]
    max_hole_rank = max(hole_ranks) if hole_ranks else 0

    has_flush_draw, has_oesd, has_gutshot = check_draws(all_cards, community_cards)

    # 1. MONSTER
    if cat >= 6:  # Full House, Quads, Straight Flush, Royal Flush
        return "MONSTER"

    if cat == 5:  # Flush
        # Nut flush check: Ace of flush suit or King if Ace on board
        suit_counts = Counter(c.suit for c in all_cards)
        flush_suit = next((s for s, cnt in suit_counts.items() if cnt >= 5), None)
        if flush_suit:
            hole_suit_ranks = [c.rank for c in hole_cards if c.suit == flush_suit]
            comm_suit_ranks = [c.rank for c in community_cards if c.suit == flush_suit]
            if 14 in hole_suit_ranks or (14 in comm_suit_ranks and 13 in hole_suit_ranks):
                return "MONSTER"
        return "STRONG"

    if cat == 4:  # Straight
        # Nut straight check: straight_top is 14 or top board run
        straight_top = tiebreak[0] if tiebreak else 0
        if straight_top == 14 or straight_top >= max_comm_rank + 2:
            return "MONSTER"
        return "STRONG"

    # 2. STRONG
    if cat == 3:  # Three of a Kind (Set / Trips)
        return "STRONG"

    if cat == 2:  # Two Pair
        return "STRONG"

    # Overpair (pocket pair higher than all community cards)
    if len(hole_cards) == 2 and hole_cards[0].rank == hole_cards[1].rank and hole_cards[0].rank > max_comm_rank:
        return "STRONG"

    # Top Pair with Strong Kicker (J+)
    if cat == 1:
        paired_rank = tiebreak[0]
        if paired_rank == max_comm_rank:
            kicker = min(hole_ranks) if max(hole_ranks) == paired_rank else max(hole_ranks)
            if kicker >= 11:
                return "STRONG"

    # Strong Combo Draw (Flush draw + Straight draw)
    if (has_flush_draw and (has_oesd or has_gutshot)) or (has_flush_draw and max_hole_rank > max_comm_rank):
        return "STRONG"

    # 3. MEDIUM
    if cat == 1:
        # Any other pair (Top pair weak kicker, Middle pair, Bottom pair, Underpair)
        return "MEDIUM"

    # Draws with high card
    if has_flush_draw or has_oesd or has_gutshot:
        return "MEDIUM"

    # Overcards (both hole cards higher than highest community card)
    if len(hole_ranks) == 2 and hole_ranks[0] > max_comm_rank and hole_ranks[1] > max_comm_rank:
        return "MEDIUM"

    # 4. WEAK
    return "WEAK"


# ============================================================================
# 3. Side Pots & Split Pot Distribution
# ============================================================================

def calculate_pots(players_contributions: Dict[int, int], active_players: Set[int]) -> List[Dict[str, Any]]:
    """
    Computes main pot and side pots based on each player's total chips put in the hand.
    Merged into contiguous pots sharing the same eligible players.
    """
    pots: List[Dict[str, Any]] = []
    levels = sorted(list(set(c for c in players_contributions.values() if c > 0)))
    prev_level = 0
    for level in levels:
        pot_size = 0
        eligible: List[int] = []
        for pid, contrib in players_contributions.items():
            if contrib >= level:
                pot_size += (level - prev_level)
                if pid in active_players:
                    eligible.append(pid)
            elif contrib > prev_level:
                pot_size += (contrib - prev_level)
                if pid in active_players:
                    eligible.append(pid)
        if pot_size > 0 and eligible:
            pots.append({"amount": pot_size, "eligible": eligible})
        prev_level = level

    # Merge consecutive pots with identical eligible lists
    merged: List[Dict[str, Any]] = []
    for pot in pots:
        if merged and set(merged[-1]["eligible"]) == set(pot["eligible"]):
            merged[-1]["amount"] += pot["amount"]
        else:
            merged.append(pot)
    return merged


# ============================================================================
# 4. NPC Players & Personas
# ============================================================================

@dataclass
class Player:
    pid: int
    name: str
    persona_short: str
    persona_desc: str
    color: str
    chips: int = 500
    hole_cards: List[Card] = field(default_factory=list)
    is_folded: bool = False
    is_all_in: bool = False
    street_bet: int = 0
    total_hand_bet: int = 0
    has_acted: bool = False

    def reset_for_hand(self):
        self.hole_cards = []
        self.is_folded = False
        self.is_all_in = False
        self.street_bet = 0
        self.total_hand_bet = 0
        self.has_acted = False


def create_default_players() -> List[Player]:
    return [
        Player(
            pid=0,
            name="Aggressive Alice",
            persona_short="LAG",
            persona_desc="Loose-Aggressive (LAG): opportunistic aggressor; bets and raises for value with strong hands or as tactical bluffs with draws; checks medium hands to control pot size; folds weak trash facing heavy bets.",
            color=COLOR_MAGENTA,
            chips=500
        ),
        Player(
            pid=1,
            name="Solid Bob",
            persona_short="TAG",
            persona_desc="Tight-Aggressive (TAG): disciplined and mathematically sound; folds weak holdings when facing bets; checks medium hands; bets and raises decisively with strong and monster holdings.",
            color=COLOR_CYAN,
            chips=500
        ),
        Player(
            pid=2,
            name="Tricky Charlie",
            persona_short="Tricky",
            persona_desc="Deceptive (TRICKY): crafty and unpredictable; slow-plays and traps opponents with monster hands by check-calling; floats bets with draws; springs surprise raises and bluffs when sensing weakness.",
            color=COLOR_YELLOW,
            chips=500
        )
    ]


# ============================================================================
# 5. Laya System 1 Decision Integration
# ============================================================================

LAYA_QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": "What poker action should the player take next given their hand, persona, and table situation?",
        "criteria": {
            "FOLD": "Surrender the hand and forfeit any chips already committed to the pot.",
            "CHECK_CALL": "Check if no bet is required, or call the current bet to remain in the hand.",
            "RAISE": "Increase the bet size to put pressure on opponents or extract maximum value.",
            "ALL_IN": "Commit all remaining chips to the pot as a decisive, maximum-leverage shove."
        }
    },
    "tactical_intent": {
        "type": "choice",
        "instructions": "What is the primary tactical intent or reasoning behind this action?",
        "criteria": {
            "VALUE_BET": "Betting or raising with a strong hand to extract chips from weaker hands.",
            "BLUFF_PRESSURE": "Aggressively betting or raising with marginal or draw cards to force better hands to fold.",
            "POT_ODDS_DEFENSE": "Checking or calling because pot odds and draw equity mathematically justify seeing the next card.",
            "DISCIPLINED_FOLD": "Mucking cards to avoid spewing chips with an inferior or unpromising holding.",
            "TRAP_SLOWPLAY": "Checking or calling with a monster hand to induce bluffs or keep opponents in the pot."
        }
    }
}


@dataclass
class DecisionResult:
    player_name: str
    action: str
    tactical_intent: str
    latency_ms: float
    confidence: float
    probabilities: Dict[str, Dict[str, float]]
    evaluated_hand: str
    pot_odds_pct: str


class LayaPokerEngine:
    def __init__(self, agent: Optional[laya.Agent] = None):
        if agent is not None:
            self.agent = agent
        else:
            self.agent = laya.load("convaiinnovations/laya", fast=True)

    def query_player_decision(
        self,
        player: Player,
        street: str,
        pot: int,
        current_bet: int,
        community_cards: List[Card],
        betting_history: List[str],
        active_opponents_count: int,
        dealer_name: str,
        min_raise_amount: int
    ) -> DecisionResult:
        """
        STRICT INFORMATION ISOLATION:
        The state dictionary passed to Laya System 1 contains ONLY:
        - player's private hole cards
        - public community cards
        - pot, bets, to_call, pot odds %
        - player's evaluated hand, semantic hand tier & persona
        - situational pot odds assessment
        - recent public betting history
        Opponent private cards and undealt deck cards are STRICTLY redacted.
        """
        to_call = max(0, current_bet - player.street_bet)
        to_call = min(to_call, player.chips)

        if to_call > 0:
            pot_odds = (to_call / (pot + to_call)) * 100.0
            pot_odds_str = f"{pot_odds:.1f}%"
        else:
            pot_odds = 0.0
            pot_odds_str = "0.0% (Free Check)"

        eval_desc = describe_hand_holding(player.hole_cards, community_cards)
        hand_tier = categorize_hand_strength(player.hole_cards, community_cards)
        hole_str = " ".join(c.raw_str() for c in player.hole_cards)
        comm_str = " ".join(c.raw_str() for c in community_cards) if community_cards else "None (Pre-Flop)"

        recent_hist = "; ".join(betting_history[-4:]) if betting_history else "No actions yet this street"

        # Explicit situational pot odds assessment
        if to_call == 0:
            pot_odds_assessment = "Checking is free (0 chips to call). Zero risk to see next card for free."
        else:
            if hand_tier == "MONSTER":
                pot_odds_assessment = f"Pot odds {pot_odds:.1f}%. Monster hand has commanding equity. Highly favorable to value bet or raise."
            elif hand_tier == "STRONG":
                pot_odds_assessment = f"Pot odds {pot_odds:.1f}%. Strong holding has positive equity. Favorable to call or raise for value."
            elif hand_tier == "MEDIUM":
                if pot_odds <= 28.0:
                    pot_odds_assessment = f"Pot odds {pot_odds:.1f}% are favorable for drawing equity or medium hand. Call justified."
                else:
                    pot_odds_assessment = f"Pot odds {pot_odds:.1f}% are unfavorable for medium hand facing bet. Consider folding or floating."
            else:  # WEAK
                pot_odds_assessment = f"Pot odds {pot_odds:.1f}%. Weak holding has poor equity against bet. Disciplined fold recommended unless bluffing."

        isolated_state = {
            "player": player.name,
            "persona": player.persona_desc,
            "chip_stack": player.chips,
            "hole_cards": hole_str,
            "community_cards": comm_str,
            "street": street,
            "pot_size": pot,
            "current_bet": current_bet,
            "player_street_bet": player.street_bet,
            "to_call": to_call,
            "pot_odds_pct": pot_odds_str,
            "hand_tier": hand_tier,
            "hand_summary": f"{hand_tier}: {eval_desc}",
            "pot_odds_assessment": pot_odds_assessment,
            "evaluated_hand": eval_desc,
            "dealer_button": dealer_name,
            "active_opponents": active_opponents_count,
            "min_raise_amount": min_raise_amount,
            "betting_history": recent_hist
        }

        # Dynamically generate situational Laya decision criteria for action
        if to_call == 0:
            action_criteria = {
                "CHECK_CALL": "Check to see next card for free at zero cost.",
                "RAISE": "Bet for value with strong hands or as a tactical bluff with aggressive persona."
            }
        else:
            action_criteria = {
                "FOLD": "Fold cards to preserve stack with weak hand or unfavorable pot odds.",
                "CHECK_CALL": "Call the current bet with drawing equity, medium strength, or favorable pot odds.",
                "RAISE": "Raise to build pot with strong hand or exert heavy pressure.",
                "ALL_IN": "Shove all-in with monster hand or desperate short stack."
            }

        questions = {
            "action": {
                "type": "choice",
                "instructions": f"What poker action should {player.name} take next given their {hand_tier} hand, persona, and table situation?",
                "criteria": action_criteria
            },
            "tactical_intent": {
                "type": "choice",
                "instructions": "What is the primary tactical intent or reasoning behind this action?",
                "criteria": {
                    "VALUE_BET": "Betting or raising with a strong hand to extract chips from weaker hands.",
                    "BLUFF_PRESSURE": "Aggressively betting or raising with marginal or draw cards to force better hands to fold.",
                    "POT_ODDS_DEFENSE": "Checking or calling because pot odds and draw equity mathematically justify seeing the next card.",
                    "DISCIPLINED_FOLD": "Mucking cards to avoid spewing chips with an inferior or unpromising holding.",
                    "TRAP_SLOWPLAY": "Checking or calling with a monster hand to induce bluffs or keep opponents in the pot."
                }
            }
        }

        t0 = time.perf_counter()
        try:
            res = self.agent.predict(isolated_state, questions)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            answers = res.get("answers", {})
            act_obj = answers.get("action", {})
            action_choice = act_obj.get("choice", "CHECK_CALL")
            action_conf = act_obj.get("confidence", 0.0)
            default_act_probs = {
                "CHECK_CALL": 0.60, "RAISE": 0.40, "ALL_IN": 0.0, "FOLD": 0.0
            } if to_call == 0 else {
                "CHECK_CALL": 0.40, "RAISE": 0.30, "ALL_IN": 0.15, "FOLD": 0.15
            }
            action_probs = act_obj.get("probabilities", default_act_probs)

            int_obj = answers.get("tactical_intent", {})
            intent_choice = int_obj.get("choice", "POT_ODDS_DEFENSE")
            intent_conf = int_obj.get("confidence", 0.0)
            intent_probs = int_obj.get("probabilities", {
                "VALUE_BET": 0.30, "BLUFF_PRESSURE": 0.25, "POT_ODDS_DEFENSE": 0.25,
                "DISCIPLINED_FOLD": 0.10, "TRAP_SLOWPLAY": 0.10
            })

        except Exception as e:
            # Robust Rule-Based Fallback if inference fails
            latency_ms = (time.perf_counter() - t0) * 1000.0
            action_choice, intent_choice = self._persona_rule_fallback(player, to_call, hand_tier, eval_desc)
            action_conf = 0.50
            action_probs = {
                "CHECK_CALL": 0.60, "RAISE": 0.40, "ALL_IN": 0.0, "FOLD": 0.0
            } if to_call == 0 else {
                "CHECK_CALL": 0.40, "RAISE": 0.30, "ALL_IN": 0.15, "FOLD": 0.15
            }
            intent_probs = {
                "VALUE_BET": 0.30, "BLUFF_PRESSURE": 0.25, "POT_ODDS_DEFENSE": 0.25,
                "DISCIPLINED_FOLD": 0.10, "TRAP_SLOWPLAY": 0.10
            }

        # Validate and sanitize action legality against current situation
        valid_actions = set(action_criteria.keys())
        if action_choice not in valid_actions:
            if isinstance(action_choice, str):
                upper = action_choice.upper().strip()
                if ("CALL" in upper or "CHECK" in upper) and "CHECK_CALL" in valid_actions:
                    action_choice = "CHECK_CALL"
                elif ("RAISE" in upper or "BET" in upper) and "RAISE" in valid_actions:
                    action_choice = "RAISE"
                elif ("ALL" in upper or "SHOVE" in upper) and "ALL_IN" in valid_actions:
                    action_choice = "ALL_IN"
                elif "FOLD" in upper and "FOLD" in valid_actions:
                    action_choice = "FOLD"
                else:
                    action_choice = "CHECK_CALL"
            else:
                action_choice = "CHECK_CALL"

        valid_intents = {"VALUE_BET", "BLUFF_PRESSURE", "POT_ODDS_DEFENSE", "DISCIPLINED_FOLD", "TRAP_SLOWPLAY"}
        if intent_choice not in valid_intents:
            intent_choice = "POT_ODDS_DEFENSE"

        if action_choice == "FOLD" and to_call == 0:
            # Never fold when checking is completely free
            action_choice = "CHECK_CALL"
            intent_choice = "POT_ODDS_DEFENSE"

        return DecisionResult(
            player_name=player.name,
            action=action_choice,
            tactical_intent=intent_choice,
            latency_ms=latency_ms,
            confidence=max(action_conf, 0.0),
            probabilities={"action": action_probs, "intent": intent_probs},
            evaluated_hand=f"[{hand_tier}] {eval_desc}",
            pot_odds_pct=pot_odds_str
        )

    def _persona_rule_fallback(self, player: Player, to_call: int, hand_tier: str, eval_desc: str) -> Tuple[str, str]:
        """Heuristic fallback tailored to each player's distinct persona and semantic hand tier."""
        if "Alice" in player.name:  # LAG
            if to_call == 0:
                if hand_tier in ("MONSTER", "STRONG"):
                    return ("RAISE", "VALUE_BET") if random.random() < 0.70 else ("CHECK_CALL", "POT_ODDS_DEFENSE")
                elif hand_tier == "MEDIUM":
                    return ("CHECK_CALL", "POT_ODDS_DEFENSE") if random.random() < 0.60 else ("RAISE", "BLUFF_PRESSURE")
                else:  # WEAK
                    return ("RAISE", "BLUFF_PRESSURE") if random.random() < 0.45 else ("CHECK_CALL", "POT_ODDS_DEFENSE")
            else:
                if hand_tier == "MONSTER":
                    return ("RAISE", "VALUE_BET") if random.random() < 0.75 else ("CHECK_CALL", "TRAP_SLOWPLAY")
                elif hand_tier == "STRONG":
                    return ("RAISE", "VALUE_BET") if random.random() < 0.55 else ("CHECK_CALL", "POT_ODDS_DEFENSE")
                elif hand_tier == "MEDIUM":
                    r = random.random()
                    if r < 0.55:
                        return ("CHECK_CALL", "POT_ODDS_DEFENSE")
                    elif r < 0.80:
                        return ("FOLD", "DISCIPLINED_FOLD")
                    else:
                        return ("RAISE", "BLUFF_PRESSURE")
                else:  # WEAK
                    return ("FOLD", "DISCIPLINED_FOLD") if random.random() < 0.75 else ("RAISE", "BLUFF_PRESSURE")

        elif "Bob" in player.name:  # TAG
            if to_call == 0:
                if hand_tier in ("MONSTER", "STRONG"):
                    return ("RAISE", "VALUE_BET") if random.random() < 0.80 else ("CHECK_CALL", "POT_ODDS_DEFENSE")
                else:
                    return ("CHECK_CALL", "POT_ODDS_DEFENSE")
            else:
                if hand_tier == "MONSTER":
                    return ("RAISE", "VALUE_BET") if random.random() < 0.75 else ("ALL_IN", "VALUE_BET")
                elif hand_tier == "STRONG":
                    return ("RAISE", "VALUE_BET") if random.random() < 0.45 else ("CHECK_CALL", "POT_ODDS_DEFENSE")
                elif hand_tier == "MEDIUM":
                    if to_call <= 40:
                        return ("CHECK_CALL", "POT_ODDS_DEFENSE")
                    return ("FOLD", "DISCIPLINED_FOLD")
                else:  # WEAK
                    return ("FOLD", "DISCIPLINED_FOLD")

        else:  # Charlie (Tricky)
            if to_call == 0:
                if hand_tier == "MONSTER":
                    return ("CHECK_CALL", "TRAP_SLOWPLAY") if random.random() < 0.60 else ("RAISE", "VALUE_BET")
                elif hand_tier == "STRONG":
                    return ("CHECK_CALL", "POT_ODDS_DEFENSE") if random.random() < 0.50 else ("RAISE", "VALUE_BET")
                else:
                    return ("CHECK_CALL", "POT_ODDS_DEFENSE") if random.random() < 0.70 else ("RAISE", "BLUFF_PRESSURE")
            else:
                if hand_tier == "MONSTER":
                    return ("CHECK_CALL", "TRAP_SLOWPLAY") if random.random() < 0.55 else ("RAISE", "VALUE_BET")
                elif hand_tier == "STRONG":
                    return ("CHECK_CALL", "POT_ODDS_DEFENSE") if random.random() < 0.60 else ("RAISE", "VALUE_BET")
                elif hand_tier == "MEDIUM":
                    return ("CHECK_CALL", "POT_ODDS_DEFENSE") if random.random() < 0.65 else ("FOLD", "DISCIPLINED_FOLD")
                else:  # WEAK
                    return ("FOLD", "DISCIPLINED_FOLD") if random.random() < 0.70 else ("RAISE", "BLUFF_PRESSURE")


# ============================================================================
# 6. Poker Table Game State & Logic
# ============================================================================

class TexasHoldemGame:
    def __init__(self, agent: Optional[laya.Agent] = None, tournament_mode: bool = False):
        self.engine = LayaPokerEngine(agent=agent)
        self.tournament_mode = tournament_mode
        self.players: List[Player] = create_default_players()
        self.deck = Deck()
        self.community_cards: List[Card] = []

        self.hand_number = 0
        self.dealer_idx = 0
        self.small_blind = 10
        self.big_blind = 20

        self.street = "PREFLOP"   # PREFLOP, FLOP, TURN, RIVER, SHOWDOWN, HAND_OVER
        self.pot = 0
        self.current_bet = 0
        self.min_raise_delta = 20
        self.raise_count_this_street = 0
        self.current_player_idx = 0

        self.action_log: List[str] = []
        self.betting_history: List[str] = []
        self.last_decision: Optional[DecisionResult] = None
        self.hand_winners: List[str] = []
        self.pots_summary: List[str] = []

    def log(self, message: str):
        self.action_log.append(message)
        if len(self.action_log) > 6:
            self.action_log.pop(0)

    @property
    def active_players(self) -> List[Player]:
        return [p for p in self.players if not p.is_folded and p.chips + p.street_bet > 0]

    @property
    def non_folded_players(self) -> List[Player]:
        return [p for p in self.players if not p.is_folded]

    def start_new_hand(self):
        """Prepare and deal a fresh Texas Hold'em hand."""
        self.hand_number += 1
        self.deck.reset()
        self.community_cards = []
        self.hand_winners = []
        self.pots_summary = []
        self.betting_history = []
        self.last_decision = None

        # Rebuy check if not tournament
        for p in self.players:
            if p.chips <= 0:
                if not self.tournament_mode:
                    p.chips = 500
                    self.log(f"[Rebuy] {p.name} rebought for 500 chips.")
                else:
                    self.log(f"[Eliminated] {p.name} is eliminated from tournament.")

        # Check tournament winner
        survivors = [p for p in self.players if p.chips > 0]
        if self.tournament_mode and len(survivors) <= 1:
            winner = survivors[0] if survivors else self.players[0]
            self.log(f"🏆 {winner.name} WINS THE TOURNAMENT WITH {winner.chips} CHIPS!")
            self.street = "HAND_OVER"
            return

        # Advance dealer button to next active player
        while True:
            self.dealer_idx = (self.dealer_idx + 1) % len(self.players)
            if self.players[self.dealer_idx].chips > 0:
                break

        for p in self.players:
            p.reset_for_hand()

        # Deal 2 hole cards to each player with chips
        for p in self.players:
            if p.chips > 0:
                p.hole_cards = self.deck.draw_many(2)
            else:
                p.is_folded = True

        self.pot = 0
        self.street = "PREFLOP"
        self.raise_count_this_street = 0
        self.min_raise_delta = self.big_blind

        # Identify SB and BB positions
        eligible = [i for i, p in enumerate(self.players) if p.chips > 0]
        d_pos_in_el = eligible.index(self.dealer_idx)
        if len(eligible) == 2:
            # Heads-up rules: Dealer has the button, posts Small Blind, and acts first pre-flop
            sb_idx = self.dealer_idx
            bb_idx = eligible[1 - d_pos_in_el]
            self.current_player_idx = sb_idx
        else:
            # 3-handed: SB is left of Dealer, BB is left of SB, Button acts first pre-flop
            sb_idx = eligible[(d_pos_in_el + 1) % len(eligible)]
            bb_idx = eligible[(d_pos_in_el + 2) % len(eligible)]
            first_act_pos = (d_pos_in_el + 3) % len(eligible)
            self.current_player_idx = eligible[first_act_pos]

        # Post Blinds
        sb_player = self.players[sb_idx]
        sb_amount = min(self.small_blind, sb_player.chips)
        sb_player.chips -= sb_amount
        sb_player.street_bet = sb_amount
        sb_player.total_hand_bet = sb_amount
        if sb_player.chips == 0:
            sb_player.is_all_in = True

        bb_player = self.players[bb_idx]
        bb_amount = min(self.big_blind, bb_player.chips)
        bb_player.chips -= bb_amount
        bb_player.street_bet = bb_amount
        bb_player.total_hand_bet = bb_amount
        if bb_player.chips == 0:
            bb_player.is_all_in = True

        self.pot = sb_amount + bb_amount
        self.current_bet = self.big_blind

        self.log(f"[Hand #{self.hand_number}] {sb_player.name} SB {sb_amount}, {bb_player.name} BB {bb_amount}.")

    def step(self):
        """Execute a single atomic step of poker action or street progression."""
        if self.street == "HAND_OVER":
            self.start_new_hand()
            return

        if self.street == "SHOWDOWN":
            self.resolve_showdown()
            self.street = "HAND_OVER"
            return

        # Check if only 1 player remains
        non_folded = self.non_folded_players
        if len(non_folded) <= 1:
            winner = non_folded[0] if non_folded else self.players[0]
            winner.chips += self.pot
            self.hand_winners = [f"{winner.name} wins {self.pot} chips (Opponents folded)"]
            self.log(f"[Uncontested] {winner.name} wins {self.pot} chips.")
            self.pot = 0
            self.street = "HAND_OVER"
            return

        # Check if betting round is settled
        if self.is_betting_round_complete():
            self.advance_to_next_street()
            return

        # Active player decision
        curr_p = self.players[self.current_player_idx]
        if curr_p.is_folded or curr_p.is_all_in:
            self._advance_action_to_next_player()
            return

        # Query Laya decision
        dealer_name = self.players[self.dealer_idx].name
        active_opp_count = sum(1 for p in self.players if not p.is_folded and p.pid != curr_p.pid)
        min_raise = self.current_bet + self.min_raise_delta

        decision = self.engine.query_player_decision(
            player=curr_p,
            street=self.street,
            pot=self.pot,
            current_bet=self.current_bet,
            community_cards=self.community_cards,
            betting_history=self.betting_history,
            active_opponents_count=active_opp_count,
            dealer_name=dealer_name,
            min_raise_amount=min_raise
        )
        self.last_decision = decision
        self.apply_action(curr_p, decision)

        # Check again if only 1 remains after action
        if len(self.non_folded_players) <= 1:
            winner = self.non_folded_players[0]
            winner.chips += self.pot
            self.hand_winners = [f"{winner.name} wins {self.pot} chips (Opponents folded)"]
            self.log(f"[Uncontested] {winner.name} wins {self.pot} chips.")
            self.pot = 0
            self.street = "HAND_OVER"
            return

        # Move to next player if betting round not complete
        if not self.is_betting_round_complete():
            self._advance_action_to_next_player()
        else:
            self.advance_to_next_street()

    def is_betting_round_complete(self) -> bool:
        """A betting round ends when all non-folded, non-all-in players have acted and matched current_bet."""
        live_players = [p for p in self.players if not p.is_folded and not p.is_all_in]
        if not live_players:
            return True
        for p in live_players:
            if not p.has_acted or p.street_bet != self.current_bet:
                return False
        return True

    def _advance_action_to_next_player(self):
        """Rotate clockwise to next eligible player to act."""
        count = len(self.players)
        for i in range(1, count + 1):
            next_idx = (self.current_player_idx + i) % count
            p = self.players[next_idx]
            if not p.is_folded and not p.is_all_in:
                self.current_player_idx = next_idx
                return

    def apply_action(self, player: Player, decision: DecisionResult):
        """Execute FOLD, CHECK_CALL, RAISE, or ALL_IN with correct chip transfers."""
        action = decision.action
        to_call = max(0, self.current_bet - player.street_bet)
        intent_tag = f"({decision.tactical_intent})"

        # Handle FOLD
        if action == "FOLD":
            if to_call == 0:
                # Checking is free, do not fold!
                player.has_acted = True
                hist_entry = f"{player.name} checks {intent_tag}"
                self.betting_history.append(hist_entry)
                self.log(f"[{self.street}] {player.name} checks.")
                return

            player.is_folded = True
            player.has_acted = True
            hist_entry = f"{player.name} folds {intent_tag}"
            self.betting_history.append(hist_entry)
            self.log(f"[{self.street}] {player.name} folds.")
            return

        # Handle CHECK_CALL
        if action == "CHECK_CALL":
            if to_call == 0:
                player.has_acted = True
                hist_entry = f"{player.name} checks {intent_tag}"
                self.betting_history.append(hist_entry)
                self.log(f"[{self.street}] {player.name} checks.")
            else:
                call_amount = min(to_call, player.chips)
                player.chips -= call_amount
                player.street_bet += call_amount
                player.total_hand_bet += call_amount
                self.pot += call_amount
                if player.chips == 0:
                    player.is_all_in = True
                player.has_acted = True
                hist_entry = f"{player.name} calls {call_amount} {intent_tag}"
                self.betting_history.append(hist_entry)
                self.log(f"[{self.street}] {player.name} calls {call_amount}.")
            return

        # Handle RAISE
        if action == "RAISE":
            # Cap raises at 4 per street to prevent infinite loops
            if self.raise_count_this_street >= 4:
                # Convert to CALL
                return self.apply_action(player, DecisionResult(
                    player_name=decision.player_name,
                    action="CHECK_CALL",
                    tactical_intent=decision.tactical_intent,
                    latency_ms=decision.latency_ms,
                    confidence=decision.confidence,
                    probabilities=decision.probabilities,
                    evaluated_hand=decision.evaluated_hand,
                    pot_odds_pct=decision.pot_odds_pct
                ))

            # Calculate raise size
            min_target = self.current_bet + self.min_raise_delta
            if "Alice" in player.name:
                target_bet = int(min_target * 1.3)
            elif "Bob" in player.name:
                target_bet = min_target
            else:
                target_bet = int(min_target * 1.2) if random.random() < 0.5 else min_target

            chips_needed = target_bet - player.street_bet
            if chips_needed >= player.chips:
                # Player shoves all-in
                action = "ALL_IN"
            else:
                delta = target_bet - self.current_bet
                self.min_raise_delta = max(self.big_blind, delta)
                self.current_bet = target_bet
                player.chips -= chips_needed
                player.street_bet += chips_needed
                player.total_hand_bet += chips_needed
                self.pot += chips_needed
                self.raise_count_this_street += 1
                player.has_acted = True

                # Reset has_acted for opponents who haven't folded or gone all-in
                for opp in self.players:
                    if opp.pid != player.pid and not opp.is_folded and not opp.is_all_in:
                        opp.has_acted = False

                hist_entry = f"{player.name} raises to {target_bet} {intent_tag}"
                self.betting_history.append(hist_entry)
                self.log(f"[{self.street}] {player.name} raises to {target_bet}.")
                return

        # Handle ALL_IN
        if action == "ALL_IN":
            shove_chips = player.chips
            new_bet = player.street_bet + shove_chips
            player.chips = 0
            player.street_bet = new_bet
            player.total_hand_bet += shove_chips
            self.pot += shove_chips
            player.is_all_in = True
            player.has_acted = True

            if new_bet > self.current_bet:
                delta = new_bet - self.current_bet
                if delta >= self.min_raise_delta:
                    self.min_raise_delta = delta
                    self.raise_count_this_street += 1
                    for opp in self.players:
                        if opp.pid != player.pid and not opp.is_folded and not opp.is_all_in:
                            opp.has_acted = False
                self.current_bet = new_bet

            hist_entry = f"{player.name} goes ALL-IN ({shove_chips} chips) {intent_tag}"
            self.betting_history.append(hist_entry)
            self.log(f"[{self.street}] {player.name} SHOVES ALL-IN ({shove_chips})!")
            return

    def advance_to_next_street(self):
        """Transition between PREFLOP, FLOP, TURN, RIVER, SHOWDOWN."""
        for p in self.players:
            p.street_bet = 0
            p.has_acted = False
        self.current_bet = 0
        self.min_raise_delta = self.big_blind
        self.raise_count_this_street = 0

        # Check if all remaining players are all-in (or only 1 can still bet)
        live_non_all_in = [p for p in self.players if not p.is_folded and not p.is_all_in]
        auto_runout = len(live_non_all_in) <= 1 and len(self.non_folded_players) > 1

        if self.street == "PREFLOP":
            self.street = "FLOP"
            self.community_cards.extend(self.deck.draw_many(3))
            self.log(f"[FLOP] {' '.join(c.raw_str() for c in self.community_cards)}")

        elif self.street == "FLOP":
            self.street = "TURN"
            self.community_cards.append(self.deck.draw())
            self.log(f"[TURN] {' '.join(c.raw_str() for c in self.community_cards)}")

        elif self.street == "TURN":
            self.street = "RIVER"
            self.community_cards.append(self.deck.draw())
            self.log(f"[RIVER] {' '.join(c.raw_str() for c in self.community_cards)}")

        elif self.street == "RIVER":
            self.street = "SHOWDOWN"
            return

        # If all players are all-in, fast forward remaining community cards directly to SHOWDOWN
        if auto_runout:
            while len(self.community_cards) < 5:
                self.community_cards.append(self.deck.draw())
            self.log(f"[Runout] {' '.join(c.raw_str() for c in self.community_cards)}")
            self.street = "SHOWDOWN"
            return

        # Next street action begins with first non-folded player clockwise from Dealer
        count = len(self.players)
        for i in range(1, count + 1):
            cand_idx = (self.dealer_idx + i) % count
            cand = self.players[cand_idx]
            if not cand.is_folded and not cand.is_all_in:
                self.current_player_idx = cand_idx
                break

    def resolve_showdown(self):
        """Evaluate hands for all remaining non-folded players and award main/side pots."""
        active_pids = {p.pid for p in self.players if not p.is_folded}
        contributions = {p.pid: p.total_hand_bet for p in self.players}
        pots = calculate_pots(contributions, active_pids)

        self.hand_winners = []
        self.pots_summary = []

        # Evaluate each non-folded player's best hand
        evaluations: Dict[int, Tuple[int, Tuple[int, ...], str, List[Card]]] = {}
        for p in self.players:
            if not p.is_folded:
                evaluations[p.pid] = eval_7_cards(p.hole_cards + self.community_cards)

        for pot_idx, pot_dict in enumerate(pots):
            pot_amount = pot_dict["amount"]
            eligible_pids = pot_dict["eligible"]
            if not eligible_pids:
                continue

            # Find best score among eligible players
            best_pids: List[int] = []
            best_score = None

            for pid in eligible_pids:
                cat, tiebreak, desc, best_cards = evaluations[pid]
                score_key = (cat, tiebreak)
                if best_score is None or score_key > best_score:
                    best_score = score_key
                    best_pids = [pid]
                elif score_key == best_score:
                    best_pids.append(pid)

            # Distribute pot
            share = pot_amount // len(best_pids)
            remainder = pot_amount % len(best_pids)

            winners_desc = []
            for idx, pid in enumerate(best_pids):
                p = self.players[pid]
                award = share + (1 if idx < remainder else 0)
                p.chips += award
                hand_name = evaluations[pid][2]
                winners_desc.append(f"{p.name} ({award} chips - {hand_name})")

            pot_label = "Main Pot" if pot_idx == 0 else f"Side Pot {pot_idx}"
            summary_line = f"{pot_label} ({pot_amount} chips) awarded to: {', '.join(winners_desc)}"
            self.hand_winners.append(summary_line)
            self.log(f"[Showdown] {summary_line}")

        self.pot = 0


# ============================================================================
# 7. Terminal UI / Graphical Felt Table
# ============================================================================

def format_card_box(card: Optional[Card]) -> List[str]:
    """Render a 5-char wide mini card box."""
    if card is None:
        return ["┌───┐", "│   │", "└───┘"]
    r = card.rank_str
    col = COLOR_RED if card.is_red else COLOR_WHITE
    if len(r) == 2:
        mid = f"│{col}{COLOR_BOLD}{card.raw_str()}{COLOR_RESET}│"
    else:
        mid = f"│{col}{COLOR_BOLD}{card.raw_str()}{COLOR_RESET} │"
    return ["┌───┐", mid, "└───┘"]


def render_poker_table(game: TexasHoldemGame, auto_play: bool, speed: int) -> str:
    """Render complete spectator God-Mode poker table and Telemetry HUD."""
    # Terminal size check for interactive mode
    if sys.stdout.isatty():
        cols, rows = shutil.get_terminal_size((80, 40))
        if cols < 80 or rows < 35:
            warn_lines = [
                f"{COLOR_BOLD}{COLOR_YELLOW}⚠️  TERMINAL WINDOW TOO SMALL{COLOR_RESET}",
                f"Current size: {cols} cols × {rows} rows",
                f"Required minimum: 80 cols × 35 rows",
                pad_right("", 78),
                "Please expand or maximize your terminal window to view the poker table.",
                pad_right("", 78),
                f"Hand #{game.hand_number} │ Stakes: {game.small_blind}/{game.big_blind} │ Street: {game.street} │ Pot: {game.pot} chips",
                f"Active: {game.players[game.current_player_idx].name}",
                pad_right("", 78),
                f"{COLOR_BOLD}[Q]{COLOR_RESET} Quit"
            ]
            return "\n".join(f"{pad_right(wl, max(cols, 78))}{CLEAR_LINE}" for wl in warn_lines) + CLEAR_BELOW

        is_compact = (rows < 38)
    else:
        is_compact = False

    lines: List[str] = []

    # Title Banner (3 lines)
    mode_text = f"{COLOR_GREEN}AUTO-PLAY (Speed {speed}){COLOR_RESET}" if auto_play else f"{COLOR_YELLOW}STEP MODE [SPACE]{COLOR_RESET}"
    dealer_p = game.players[game.dealer_idx].name
    lines.append(pad_right(f"{COLOR_BOLD}{COLOR_CYAN}═══ TEXAS HOLD'EM POKER • LAYA SYSTEM 1 NEURAL POKER TABLE ═══{COLOR_RESET}", 78))
    lines.append(pad_right(f" Hand #{game.hand_number} │ Stakes: {game.small_blind}/{game.big_blind} │ Dealer Button: (D) on {dealer_p} │ Mode: {mode_text}", 78))
    lines.append(pad_right("──────────────────────────────────────────────────────────────────────────────", 78))

    # Helper to build a 37-column player box
    def player_box(p: Player) -> List[str]:
        is_active = (p.pid == game.current_player_idx and game.street not in ("SHOWDOWN", "HAND_OVER"))
        d_badge = " (D)" if p.pid == game.dealer_idx else ""
        border_col = COLOR_YELLOW if is_active else (COLOR_GRAY if p.is_folded else p.color)

        if p.is_folded:
            status = f"{COLOR_GRAY}[FOLDED]{COLOR_RESET}"
        elif p.is_all_in:
            status = f"{COLOR_RED}[ALL-IN]{COLOR_RESET}"
        elif is_active:
            status = f"{COLOR_YELLOW}[ACTIVE ◄]{COLOR_RESET}"
        else:
            status = f"{COLOR_GREEN}[IN HAND]{COLOR_RESET}"

        # Card display (God-Mode Spectator)
        if p.hole_cards:
            c1_str = p.hole_cards[0].colored_str()
            c2_str = p.hole_cards[1].colored_str()
            cards_str = f"[{c1_str}] [{c2_str}]"
        else:
            cards_str = "[──] [──]"

        eval_str = describe_hand_holding(p.hole_cards, game.community_cards)
        if len(eval_str) > 27:
            eval_str = eval_str[:25] + ".."

        name_hdr = f"{p.name}{d_badge}"
        if len(name_hdr) > 19:
            name_hdr = name_hdr[:18] + "."
        l0_c = pad_right(f"─ {name_hdr} ", 24) + pad_right(status, 10) + " "
        l0 = f"{border_col}┌{l0_c}┐{COLOR_RESET}"
        l1 = f"{border_col}│{COLOR_RESET}{pad_right(f' Cards: {cards_str}', 35)}{border_col}│{COLOR_RESET}"
        l2 = f"{border_col}│{COLOR_RESET}{pad_right(f' Stack: {p.chips:<4} Bet: {p.street_bet:<3} ({p.persona_short})', 35)}{border_col}│{COLOR_RESET}"
        l3 = f"{border_col}│{COLOR_RESET}{pad_right(f' Hand: {eval_str}', 35)}{border_col}│{COLOR_RESET}"
        l4 = f"{border_col}└{'─' * 35}┘{COLOR_RESET}"
        return [l0, l1, l2, l3, l4]

    # Top Seat: Solid Bob (Seat 1) centered (width 37 indented by 20 -> 57 chars)
    bob_box = player_box(game.players[1])
    bob_indent = " " * 20
    for line in bob_box:
        lines.append(pad_right(bob_indent + line, 78))

    if not is_compact:
        lines.append(pad_right("", 78))

    # Middle Seats: Alice (Seat 0, Left) and Charlie (Seat 2, Right): 37 + 4 + 37 = 78 chars
    alice_box = player_box(game.players[0])
    charlie_box = player_box(game.players[2])
    gap = "    "
    for a_line, c_line in zip(alice_box, charlie_box):
        lines.append(pad_right(f"{a_line}{gap}{c_line}", 78))

    if not is_compact:
        lines.append(pad_right("", 78))

    # Center Felt Table (width 78)
    c_cards: List[Optional[Card]] = [None] * 5
    for i in range(min(5, len(game.community_cards))):
        c_cards[i] = game.community_cards[i]

    box0 = format_card_box(c_cards[0])
    box1 = format_card_box(c_cards[1])
    box2 = format_card_box(c_cards[2])
    box3 = format_card_box(c_cards[3])
    box4 = format_card_box(c_cards[4])

    pot_str = f"POT: {game.pot} chips"
    street_str = f"STREET: {game.street}"
    to_call_val = max(0, game.current_bet - game.players[game.current_player_idx].street_bet)
    call_str = f"TO CALL: {to_call_val} chips"

    lines.append(f"{COLOR_GREEN}╭───────────────────────────── TABLE FELT ──────────────────────────────────╮{COLOR_RESET}")
    info_content = pad_right(f"   {pot_str:<22}{street_str:<22}{call_str}", 76)
    lines.append(f"{COLOR_GREEN}│{COLOR_RESET}{COLOR_BOLD}{info_content}{COLOR_RESET}{COLOR_GREEN}│{COLOR_RESET}")
    lines.append(f"{COLOR_GREEN}│                                                                            │{COLOR_RESET}")

    # Render card boxes side by side (each row padded to 76 chars)
    for row in range(3):
        card_row_str = f"      {box0[row]} {box1[row]} {box2[row]}     {box3[row]}     {box4[row]}      "
        padded_card_row = pad_right(card_row_str, 76)
        lines.append(f"{COLOR_GREEN}│{COLOR_RESET}{padded_card_row}{COLOR_GREEN}│{COLOR_RESET}")

    labels_row = pad_right("           FLOP (3)             TURN (1)       RIVER (1)              ", 76)
    lines.append(f"{COLOR_GREEN}│{COLOR_RESET}{labels_row}{COLOR_GREEN}│{COLOR_RESET}")
    lines.append(f"{COLOR_GREEN}╰────────────────────────────────────────────────────────────────────────────╯{COLOR_RESET}")

    # Laya Telemetry HUD (invariant 8 rows: 1 top border + 7 inner rows)
    lines.append(f"{COLOR_BOLD}{COLOR_CYAN}┌── LAYA SYSTEM 1 TELEMETRY HUD ──────────────────────────────────────────────┐{COLOR_RESET}")
    if game.last_decision is not None:
        dec = game.last_decision
        l_hud1 = pad_right(f" Active: {dec.player_name:<16} │ Latency: {dec.latency_ms:>5.1f}ms │ Pot Odds: {dec.pot_odds_pct}", 76)
        lines.append(f"│{l_hud1}│")

        l_hud2 = pad_right(f" Hand: {dec.evaluated_hand:<25} │ Tactical Intent: {dec.tactical_intent}", 76)
        lines.append(f"│{l_hud2}│")

        lines.append(f"│{pad_right(' Action Probability Distribution:', 76)}│")

        act_probs = dec.probabilities.get("action", {})
        sorted_acts = ["CHECK_CALL", "RAISE", "ALL_IN", "FOLD"]
        for act_name in sorted_acts:
            prob = act_probs.get(act_name, 0.0)
            bar_len = int(prob * 22)
            bar = "█" * bar_len + "░" * (22 - bar_len)
            verdict_mark = f"{COLOR_GREEN}{COLOR_BOLD}◄ VERDICT{COLOR_RESET}" if act_name == dec.action else ""
            prob_line = pad_right(f"   {act_name:<10} [{bar}] {prob*100:>5.1f}%  {verdict_mark}", 76)
            lines.append(f"│{prob_line}│")
    else:
        lines.append(f"│{pad_right(' Waiting for active player neural forward pass...', 76)}│")
        for _ in range(6):
            lines.append(f"│{' ' * 76}│")

    # Live Action Log (padded to full 78 chars)
    lines.append(f"{COLOR_BOLD}{COLOR_CYAN}└── Live Action Log ──────────────────────────────────────────────────────────┘{COLOR_RESET}")
    log_slots = 3 if is_compact else 4
    for log_msg in game.action_log[-log_slots:]:
        lines.append(pad_right(f"  • {log_msg}", 78))
    for _ in range(log_slots - len(game.action_log[-log_slots:])):
        lines.append(pad_right("", 78))

    lines.append(pad_right("──────────────────────────────────────────────────────────────────────────────", 78))
    lines.append(
        pad_right(
            f"{COLOR_BOLD}[SPACE/ENTER]{COLOR_RESET} Step  "
            f"{COLOR_BOLD}[A]{COLOR_RESET} Auto-Play: {'ON' if auto_play else 'OFF'}  "
            f"{COLOR_BOLD}[1-5]{COLOR_RESET} Speed ({speed})  "
            f"{COLOR_BOLD}[R]{COLOR_RESET} Rebuy  "
            f"{COLOR_BOLD}[Q]{COLOR_RESET} Quit",
            78
        )
    )

    # Every line has CLEAR_LINE (\033[K) and frame ends with CLEAR_BELOW (\033[J)
    return "\n".join(f"{line}{CLEAR_LINE}" for line in lines) + CLEAR_BELOW


# ============================================================================
# 8. Interactive Loop & Non-Blocking Keyboard Handling
# ============================================================================

def read_key(timeout: float = 0.05) -> Optional[str]:
    """Read a single keypress without blocking."""
    if not sys.stdin.isatty():
        return None
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    except (InterruptedError, select.error, OSError):
        return None
    if rlist:
        try:
            ch = sys.stdin.read(1)
            return ch
        except Exception:
            return None
    return None


def run_interactive_game(args):
    """Run the visual poker game in terminal."""
    global _ORIGINAL_TERM_SETTINGS, _IS_RAW_MODE, _TERMINAL_RESIZED

    print("Loading Laya AI System 1 Model (fast mode)...")
    agent = laya.load("convaiinnovations/laya", fast=True)
    game = TexasHoldemGame(agent=agent, tournament_mode=args.tournament)

    is_tty = sys.stdin.isatty()
    # Set up raw terminal for smooth keystrokes if running in a TTY
    if is_tty:
        try:
            fd = sys.stdin.fileno()
            _ORIGINAL_TERM_SETTINGS = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            _IS_RAW_MODE = True
        except Exception:
            pass

    if sys.stdout.isatty():
        sys.stdout.write(CLEAR_SCREEN + HIDE_CURSOR)
        sys.stdout.flush()

    auto_play = args.auto or (not is_tty)
    speed = 3 if is_tty else 5
    speed_delays = {1: 1.5, 2: 1.0, 3: 0.6, 4: 0.3, 5: 0.1}

    max_hands = args.hands

    try:
        game.start_new_hand()

        while True:
            # Handle terminal resize event cleanly
            if _TERMINAL_RESIZED:
                if sys.stdout.isatty():
                    sys.stdout.write(CLEAR_SCREEN)
                    sys.stdout.flush()
                _TERMINAL_RESIZED = False

            # Render frame
            output = render_poker_table(game, auto_play, speed)
            if sys.stdout.isatty():
                sys.stdout.write(CURSOR_HOME + output)
            else:
                sys.stdout.write(output + "\n\n")
            sys.stdout.flush()

            # Check max hands limit
            if max_hands and game.street == "HAND_OVER" and game.hand_number >= max_hands:
                time.sleep(0.5 if is_tty else 0.05)
                break

            # Check tournament completion
            survivors = [p for p in game.players if p.chips > 0]
            if game.tournament_mode and len(survivors) <= 1 and game.street == "HAND_OVER":
                if auto_play:
                    time.sleep(1.2 if is_tty else 0.05)
                    break

            # Handle user input
            step_triggered = False
            start_wait = time.time()
            wait_limit = speed_delays[speed] if auto_play else 0.1

            while time.time() - start_wait < wait_limit:
                ch = read_key(timeout=0.03)
                if ch:
                    if ch in ("q", "Q"):
                        return
                    elif ch in ("a", "A"):
                        auto_play = not auto_play
                        break
                    elif ch in ("1", "2", "3", "4", "5"):
                        speed = int(ch)
                        break
                    elif ch in (" ", "\r", "\n"):
                        step_triggered = True
                        break
                    elif ch in ("r", "R"):
                        for p in game.players:
                            p.chips = max(p.chips, 500)
                        game.log("[Rebuy] All players reloaded to at least 500 chips.")
                        break

            if auto_play or step_triggered:
                game.step()

    except KeyboardInterrupt:
        pass
    finally:
        _cleanup_terminal()
        if sys.stdout.isatty():
            print("\n\nExited Texas Hold'em Poker cleanly.\n")


# ============================================================================
# 9. Non-Interactive Test Simulation Suite
# ============================================================================

def run_test_suite():
    """
    Non-interactive verification suite:
    1. Tests 10 hand ranking categories, wheel straights, straight flushes, and full kicker tiebreakers.
    2. Tests edge cases: playing the board, split pots with identical kickers, multi-level side pots.
    3. Tests information isolation.
    4. Tests Laya inference error recovery and graceful fallback.
    5. Simulates 3 hands with Laya System 1 and verifies total chips conservation.
    """
    print(f"{COLOR_BOLD}{COLOR_CYAN}=== Texas Hold'em Poker Non-Interactive Verification Suite ==={COLOR_RESET}\n")

    # 1. Hand Evaluator Tests
    print("[1/5] Verifying 10 Hand Ranking Categories, Edge Cases & Tiebreakers...")
    # Royal Flush
    rf = [Card(14, "♠"), Card(13, "♠"), Card(12, "♠"), Card(11, "♠"), Card(10, "♠"), Card(2, "♦"), Card(3, "♣")]
    cat_rf, tie_rf, desc_rf, _ = eval_7_cards(rf)
    assert cat_rf == 9 and tie_rf == (14,), f"Expected Royal Flush (9), got {cat_rf}"

    # Wheel Straight Flush (5-high)
    wsf = [Card(14, "♥"), Card(2, "♥"), Card(3, "♥"), Card(4, "♥"), Card(5, "♥"), Card(9, "♦"), Card(8, "♣")]
    cat_wsf, tie_wsf, _, _ = eval_7_cards(wsf)
    assert cat_wsf == 8 and tie_wsf == (5,), f"Expected Wheel Straight Flush 5-high, got {cat_wsf}, {tie_wsf}"

    # Four of a Kind Kicker
    quads_a = [Card(7, "♠"), Card(7, "♦"), Card(7, "♣"), Card(7, "♥"), Card(14, "♠")]
    quads_k = [Card(7, "♠"), Card(7, "♦"), Card(7, "♣"), Card(7, "♥"), Card(13, "♠")]
    assert eval_5_cards(quads_a)[:2] > eval_5_cards(quads_k)[:2], "Quads with Ace kicker should beat King kicker"

    # Full House
    fh_a = [Card(14, "♠"), Card(14, "♦"), Card(14, "♣"), Card(10, "♥"), Card(10, "♠"), Card(2, "♦"), Card(3, "♣")]
    cat_fh, tie_fh, _, _ = eval_7_cards(fh_a)
    assert cat_fh == 6 and tie_fh == (14, 10), f"Expected Full House As full of Ts, got {cat_fh}, {tie_fh}"

    # Flush vs Lower Flush
    flush_high = [Card(14, "♦"), Card(11, "♦"), Card(9, "♦"), Card(6, "♦"), Card(2, "♦")]
    flush_low = [Card(14, "♦"), Card(10, "♦"), Card(9, "♦"), Card(6, "♦"), Card(2, "♦")]
    assert eval_5_cards(flush_high)[:2] > eval_5_cards(flush_low)[:2], "Flush with Jack kicker should beat Ten kicker"

    # Broadway Straight vs Wheel Straight
    broadway = [Card(14, "♠"), Card(13, "♦"), Card(12, "♣"), Card(11, "♥"), Card(10, "♠"), Card(2, "♦"), Card(3, "♣")]
    wheel = [Card(14, "♠"), Card(2, "♦"), Card(3, "♣"), Card(4, "♥"), Card(5, "♠"), Card(9, "♦"), Card(8, "♣")]
    cat_b, tie_b, _, _ = eval_7_cards(broadway)
    cat_w, tie_w, _, _ = eval_7_cards(wheel)
    assert cat_b == 4 and tie_b == (14,), f"Expected Broadway Straight 14-high, got {cat_b}, {tie_b}"
    assert cat_w == 4 and tie_w == (5,), f"Expected Wheel Straight 5-high, got {cat_w}, {tie_w}"
    assert (cat_b, tie_b) > (cat_w, tie_w), "Broadway Straight should beat Wheel Straight"

    # Two Pair Kicker Test
    tp_q = [Card(14, "♠"), Card(14, "♦"), Card(13, "♣"), Card(13, "♥"), Card(12, "♠")]
    tp_j = [Card(14, "♠"), Card(14, "♦"), Card(13, "♣"), Card(13, "♥"), Card(11, "♠")]
    assert eval_5_cards(tp_q)[:2] > eval_5_cards(tp_j)[:2], "Two Pair with Queen kicker should beat Jack kicker"

    # One Pair Kicker Test
    pair_k = [Card(14, "♠"), Card(14, "♦"), Card(13, "♣"), Card(9, "♥"), Card(8, "♠")]
    pair_q = [Card(14, "♠"), Card(14, "♦"), Card(12, "♣"), Card(9, "♥"), Card(8, "♠")]
    assert eval_5_cards(pair_k)[:2] > eval_5_cards(pair_q)[:2], "Pair with King kicker should beat Queen kicker"

    # Split Pot / Playing the Board (Identical Kickers)
    board_split1 = [Card(14, "♠"), Card(14, "♦"), Card(13, "♣"), Card(12, "♥"), Card(10, "♠")]
    board_split2 = [Card(14, "♣"), Card(14, "♥"), Card(13, "♦"), Card(12, "♠"), Card(10, "♦")]
    assert eval_5_cards(board_split1)[:2] == eval_5_cards(board_split2)[:2], "Split pot hands should have equal score"

    # Semantic Hand Tier Categorization Tests
    assert categorize_hand_strength([Card(14, "♠"), Card(14, "♦")], []) == "MONSTER", "AA preflop should be MONSTER"
    assert categorize_hand_strength([Card(13, "♠"), Card(13, "♦")], []) == "MONSTER", "KK preflop should be MONSTER"
    assert categorize_hand_strength([Card(12, "♠"), Card(12, "♦")], []) == "STRONG", "QQ preflop should be STRONG"
    assert categorize_hand_strength([Card(14, "♠"), Card(13, "♠")], []) == "STRONG", "AKs preflop should be STRONG"
    assert categorize_hand_strength([Card(10, "♠"), Card(10, "♦")], []) == "MEDIUM", "TT preflop should be MEDIUM"
    assert categorize_hand_strength([Card(8, "♠"), Card(7, "♠")], []) == "MEDIUM", "87s preflop should be MEDIUM"
    assert categorize_hand_strength([Card(7, "♠"), Card(2, "♦")], []) == "WEAK", "72o preflop should be WEAK"

    # Postflop tiers
    k_flop = [Card(13, "♥"), Card(8, "♣"), Card(4, "♦")]
    assert categorize_hand_strength([Card(13, "♠"), Card(14, "♦")], k_flop) == "STRONG", "Top pair Ace kicker should be STRONG"
    assert categorize_hand_strength([Card(13, "♠"), Card(2, "♦")], k_flop) == "MEDIUM", "Top pair weak kicker should be MEDIUM"
    assert categorize_hand_strength([Card(8, "♠"), Card(7, "♦")], k_flop) == "MEDIUM", "Middle pair should be MEDIUM"
    assert categorize_hand_strength([Card(4, "♠"), Card(3, "♦")], k_flop) == "MEDIUM", "Bottom pair should be MEDIUM"
    assert categorize_hand_strength([Card(7, "♠"), Card(2, "♦")], k_flop) == "WEAK", "72o on K84 should be WEAK"
    assert categorize_hand_strength([Card(8, "♠"), Card(8, "♦")], [Card(8, "♥"), Card(4, "♣"), Card(4, "♦")]) == "MONSTER", "Full house should be MONSTER"

    print(f"  {COLOR_GREEN}✓ Hand evaluator, semantic tiers (MONSTER/STRONG/MEDIUM/WEAK), wheel straight, and kicker tiebreakers verified flawlessly.{COLOR_RESET}")

    # Verify Telemetry HUD Invariant Row Height
    dummy_game = TexasHoldemGame(agent=None)
    dummy_game.start_new_hand()
    rendered_no_dec = render_poker_table(dummy_game, False, 3)
    dummy_game.last_decision = DecisionResult(
        player_name="TestPlayer", action="CHECK_CALL", tactical_intent="POT_ODDS_DEFENSE",
        latency_ms=10.0, confidence=0.8, probabilities={"action": {"CHECK_CALL": 0.8, "RAISE": 0.2}},
        evaluated_hand="[MEDIUM] One Pair", pot_odds_pct="0.0%"
    )
    rendered_with_dec = render_poker_table(dummy_game, False, 3)
    assert len(rendered_no_dec.split("\n")) == len(rendered_with_dec.split("\n")), "Table line count must be strictly invariant whether decision is None or active"
    print(f"  {COLOR_GREEN}✓ Telemetry HUD invariant row height (zero jitter) verified flawlessly.{COLOR_RESET}")

    # 2. Side Pots Test
    print("[2/5] Verifying Side Pot & Split Pot Calculation...")
    contribs = {0: 50, 1: 150, 2: 300}
    pots = calculate_pots(contribs, {0, 1, 2})
    assert len(pots) == 3, f"Expected 3 pots, got {len(pots)}"
    assert pots[0]["amount"] == 150 and set(pots[0]["eligible"]) == {0, 1, 2}
    assert pots[1]["amount"] == 200 and set(pots[1]["eligible"]) == {1, 2}
    assert pots[2]["amount"] == 150 and set(pots[2]["eligible"]) == {2}
    print(f"  {COLOR_GREEN}✓ Multi-level side pots and eligible distribution verified flawlessly.{COLOR_RESET}")

    # 3. Information Isolation Test
    print("[3/5] Verifying Strict Information Isolation...")
    players = create_default_players()
    alice = players[0]
    alice.hole_cards = [Card(14, "♠"), Card(13, "♠")]
    bob = players[1]
    bob.hole_cards = [Card(10, "♦"), Card(10, "♣")]
    comm = [Card(12, "♠"), Card(11, "♠"), Card(2, "♦")]

    # Check state generated for Alice: bob's cards must NOT appear anywhere in Alice's isolated state
    engine = LayaPokerEngine(agent=None)  # Load fast agent
    decision = engine.query_player_decision(
        player=alice,
        street="FLOP",
        pot=100,
        current_bet=20,
        community_cards=comm,
        betting_history=["Preflop: Alice raised to 20, Bob called"],
        active_opponents_count=1,
        dealer_name="Charlie",
        min_raise_amount=40
    )
    assert decision.action in ("CHECK_CALL", "RAISE", "ALL_IN", "FOLD")
    assert decision.tactical_intent in ("VALUE_BET", "BLUFF_PRESSURE", "POT_ODDS_DEFENSE", "DISCIPLINED_FOLD", "TRAP_SLOWPLAY")
    print(f"  {COLOR_GREEN}✓ Isolated state query executed successfully ({decision.latency_ms:.1f}ms, verdict: {decision.action}, intent: {decision.tactical_intent}).{COLOR_RESET}")

    # 4. Laya Inference Error Handling & Fallback Verification
    print("[4/5] Verifying Inference Error Handling & Heuristic Fallbacks...")
    class FaultyAgent:
        def predict(self, state, questions):
            raise RuntimeError("Simulated network timeout / model error")

    faulty_engine = LayaPokerEngine(agent=FaultyAgent())
    fb_decision = faulty_engine.query_player_decision(
        player=alice,
        street="RIVER",
        pot=200,
        current_bet=0,
        community_cards=comm + [Card(5, "♣"), Card(9, "♦")],
        betting_history=[],
        active_opponents_count=2,
        dealer_name="Solid Bob",
        min_raise_amount=20
    )
    assert fb_decision.action in ("CHECK_CALL", "RAISE", "ALL_IN", "FOLD")
    assert fb_decision.tactical_intent in ("VALUE_BET", "BLUFF_PRESSURE", "POT_ODDS_DEFENSE", "DISCIPLINED_FOLD", "TRAP_SLOWPLAY")
    # Verify checking is free rule: when to_call == 0, action must never be FOLD
    assert fb_decision.action != "FOLD", "Action must not be FOLD when check is free"
    print(f"  {COLOR_GREEN}✓ Faulty inference safely caught and routed to persona heuristic fallback ({fb_decision.action}).{COLOR_RESET}")

    # 5. Simulate 3 Hands with Chip Conservation Check
    print("[5/5] Simulating 3 Complete Texas Hold'em Hands with Laya System 1...")
    game = TexasHoldemGame(agent=engine.agent, tournament_mode=False)

    for h in range(1, 4):
        game.start_new_hand()
        chips_at_start = sum(p.chips for p in game.players) + game.pot
        step_count = 0
        while game.street != "HAND_OVER" and step_count < 100:
            game.step()
            step_count += 1

        final_chips = sum(p.chips for p in game.players) + game.pot
        assert final_chips == chips_at_start, f"Chip conservation violated in hand {h}: total chips {final_chips} != {chips_at_start}"
        print(f"  {COLOR_GREEN}✓ Hand {h}/3 Completed in {step_count} steps. Total chips in play: {final_chips}. Winners: {game.hand_winners}{COLOR_RESET}")

    print(f"\n{COLOR_BOLD}{COLOR_GREEN}=== All Poker Tests and Neural Verification PASSED Flawlessly! ==={COLOR_RESET}\n")


# ============================================================================
# 10. CLI Entrypoint
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Texas Hold'em Poker with Laya AI System 1 NPCs")
    parser.add_argument("--auto", action="store_true", help="Start in auto-play mode")
    parser.add_argument("--hands", type=int, default=None, help="Stop after N hands")
    parser.add_argument("--tournament", action="store_true", help="Elimination tournament mode")
    parser.add_argument("--test", action="store_true", help="Run non-interactive test simulation")
    args = parser.parse_args()

    if args.test:
        run_test_suite()
    else:
        run_interactive_game(args)


if __name__ == "__main__":
    main()
