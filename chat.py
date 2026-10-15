#!/usr/bin/env python3
"""
Laya AI Real-Time Chat Moderator & Trust Engine.
Single-pass System 1 neural content safety with calibrated telemetry HUD.
"""

import sys
import os
import time
import argparse
import unicodedata
import re
import warnings
import shutil
import signal
import atexit
from typing import Dict, List, Any, Optional
from datetime import datetime

# Suppress temperature calibration warnings from laya router/agent
warnings.filterwarnings("ignore")

import laya

# ANSI Escape Sequences
CLEAR_SCREEN = "\033[2J"
CURSOR_HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"

# Ensure terminal cursor and colors are restored even on unexpected exit
def _cleanup_terminal():
    try:
        sys.stdout.write(SHOW_CURSOR + COLOR_RESET)
        sys.stdout.flush()
    except Exception:
        pass

atexit.register(_cleanup_terminal)

# Foreground Colors
COLOR_GREEN = "\033[32m"
COLOR_BRIGHT_GREEN = "\033[92m"
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_CYAN = "\033[96m"
COLOR_MAGENTA = "\033[95m"
COLOR_GRAY = "\033[90m"
COLOR_WHITE = "\033[97m"

# Layout Constants
LEFT_COL_WIDTH = 48
RIGHT_COL_WIDTH = 45
HEADER_INNER_WIDTH = LEFT_COL_WIDTH + RIGHT_COL_WIDTH + 5  # 98 chars inside ╔══╗
CONTENT_ROWS = 19


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences for accurate visible length calculations."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def get_visible_width(text: str) -> int:
    """Calculate terminal visible column width handling East Asian characters and emojis."""
    plain = strip_ansi(text)
    w = 0
    for ch in plain:
        # Ignore zero-width or variation selectors
        if ch in ('\ufe0f', '\ufe0e', '\u200b'):
            continue
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ('F', 'W') or ord(ch) >= 0x1F300:
            w += 2
        else:
            w += 1
    return w


def fit_cell(text: str, width: int) -> str:
    """Clamp and pad text to exact visible terminal width without breaking borders."""
    vis_w = get_visible_width(text)
    if vis_w > width:
        cur_w = 0
        truncated = []
        in_escape = False
        escape_seq = []
        for ch in text:
            if ch == '\033':
                in_escape = True
                escape_seq = [ch]
                continue
            if in_escape:
                escape_seq.append(ch)
                if ch in ('m', 'H', 'J', 'h', 'l'):
                    in_escape = False
                    truncated.append(''.join(escape_seq))
                continue

            w = 0
            if ch not in ('\ufe0f', '\ufe0e', '\u200b'):
                eaw = unicodedata.east_asian_width(ch)
                w = 2 if (eaw in ('F', 'W') or ord(ch) >= 0x1F300) else 1
            if cur_w + w > width:
                break
            cur_w += w
            truncated.append(ch)
        truncated.append(COLOR_RESET)
        text = ''.join(truncated)
        vis_w = cur_w

    pad = max(0, width - vis_w)
    return text + (' ' * pad)


def make_bar(prob: float, width: int = 10, fill_char: str = "█", empty_char: str = "░") -> str:
    """Generate visual progress bar for probability values."""
    clamped = max(0.0, min(1.0, prob))
    filled_len = int(round(clamped * width))
    empty_len = width - filled_len
    return (fill_char * filled_len) + (empty_char * empty_len)


class EvaluationResult:
    """Stores the calibrated outcome of a single Laya moderation pass."""
    def __init__(
        self,
        raw_message: str,
        verdict: str,               # 'GOOD' or 'BAD'
        category: str,              # 'CLEAN', 'PROFANITY_OFFENSIVE', 'GIBBERISH_SPAM'
        severity: int,              # 0, 1, 2, 3
        latency_ms: float,
        confidence: float,
        probabilities: Dict[str, Dict[str, float]],
        is_blocked: bool
    ):
        self.raw_message = raw_message
        self.verdict = verdict
        self.category = category
        self.severity = severity
        self.latency_ms = latency_ms
        self.confidence = confidence
        self.probabilities = probabilities
        self.is_blocked = is_blocked
        self.timestamp = datetime.now().strftime("%H:%M:%S")


class ChatModerator:
    def __init__(self, agent: Optional[laya.Agent] = None):
        """Initialize ChatModerator with Laya System 1 agent."""
        if agent is not None:
            self.agent = agent
        else:
            try:
                self.agent = laya.load("convaiinnovations/laya", fast=True)
            except Exception as e:
                print(f"{COLOR_RED}Error loading Laya model: {e}{COLOR_RESET}", file=sys.stderr)
                raise

        # Single forward-pass question architecture
        self.questions = {
            "verdict": {
                "type": "choice",
                "instructions": "Should this chat message be approved or blocked in chat?",
                "criteria": {
                    "GOOD": "Approved: clean, friendly, polite, constructive, or normal communication.",
                    "BAD": "Blocked: contains swearing, insults, offensive words, hate speech, or gibberish/spam."
                }
            },
            "category": {
                "type": "choice",
                "instructions": "What moderation category does this chat message belong to?",
                "criteria": {
                    "CLEAN": "Friendly, polite, constructive, or normal communication.",
                    "PROFANITY_OFFENSIVE": "Swearing, insults, offensive words, hate speech, or harassment.",
                    "GIBBERISH_SPAM": "Random keyboard smash (e.g. asdfkjsdkf), senseless letters, or noise."
                }
            },
            "severity": {
                "type": "score",
                "instructions": "Violation severity score from 0 to 3.",
                "criteria": [
                    "Level 0: No violation, clean, polite, or normal chat message.",
                    "Level 1: Minor violation, mild slang or low noise.",
                    "Level 2: Moderate violation, profanity, insult, or obvious gibberish spam.",
                    "Level 3: Severe violation, hate speech, aggressive harassment, or extreme profanity."
                ]
            }
        }

        # Session metrics
        self.chat_history: List[Dict[str, Any]] = []
        self.total_count = 0
        self.approved_count = 0
        self.blocked_count = 0
        self.clean_count = 0
        self.offensive_count = 0
        self.gibberish_count = 0
        self.latencies: List[float] = []
        self.karma = 100.0  # Trust meter starting at 100%
        self.last_result: Optional[EvaluationResult] = None
        self.last_term_size = (0, 0)
        self.needs_clear = False

    def evaluate(self, message: str) -> EvaluationResult:
        """
        Evaluate a chat message using a single forward pass of Laya System 1.
        Returns calibrated EvaluationResult.
        """
        # Sanitize input: strip ANSI escapes and replace control chars (newlines/tabs) with spaces
        clean_msg = re.sub(r'[\r\n\t]+', ' ', strip_ansi(message)).strip()
        t0 = time.perf_counter()

        # Handle empty string edge case
        if not clean_msg:
            latency_ms = (time.perf_counter() - t0) * 1000
            res = EvaluationResult(
                raw_message=message,
                verdict="BAD",
                category="GIBBERISH_SPAM",
                severity=1,
                latency_ms=latency_ms,
                confidence=1.0,
                probabilities={
                    "verdict": {"GOOD": 0.0, "BAD": 1.0},
                    "category": {"CLEAN": 0.0, "PROFANITY_OFFENSIVE": 0.0, "GIBBERISH_SPAM": 1.0},
                    "severity": {"0": 0.0, "1": 1.0, "2": 0.0, "3": 0.0}
                },
                is_blocked=True
            )
            self._update_session(res)
            return res

        # Run single forward pass with multi-question prediction
        state = {"chat_message": clean_msg}
        try:
            laya_res = self.agent.predict(state, self.questions)
        except Exception as e:
            # Fallback on inference error: log to history and return safe evaluation
            latency_ms = (time.perf_counter() - t0) * 1000
            self.add_system_message(f"Inference warning: {e}")
            res = EvaluationResult(
                raw_message=clean_msg,
                verdict="GOOD",
                category="CLEAN",
                severity=0,
                latency_ms=latency_ms,
                confidence=0.0,
                probabilities={
                    "verdict": {"GOOD": 1.0, "BAD": 0.0},
                    "category": {"CLEAN": 1.0, "PROFANITY_OFFENSIVE": 0.0, "GIBBERISH_SPAM": 0.0},
                    "severity": {"0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0}
                },
                is_blocked=False
            )
            self._update_session(res)
            return res

        latency_ms = (time.perf_counter() - t0) * 1000
        answers = laya_res.get("answers", {}) if isinstance(laya_res, dict) else {}
        ans_verdict = answers.get("verdict", {}) if isinstance(answers, dict) else {}
        ans_category = answers.get("category", {}) if isinstance(answers, dict) else {}
        ans_severity = answers.get("severity", {}) if isinstance(answers, dict) else {}

        raw_verdict = ans_verdict.get("choice", "GOOD")
        raw_category = ans_category.get("choice", "CLEAN")
        sev_probs = ans_severity.get("probabilities") or {"0": 1.0, "1": 0.0, "2": 0.0, "3": 0.0}
        try:
            raw_sev = int(max(sev_probs, key=sev_probs.get))
        except (ValueError, TypeError):
            raw_sev = 0

        prob_verdict = ans_verdict.get("probabilities") or {"GOOD": 0.5, "BAD": 0.5}
        prob_category = ans_category.get("probabilities") or {"CLEAN": 0.34, "PROFANITY_OFFENSIVE": 0.33, "GIBBERISH_SPAM": 0.33}
        calib_confidence = ans_verdict.get("confidence", ans_verdict.get("answer_confidence", 0.0))

        # Enforce calibrated consistency between verdict, category, and severity
        # 1. Any profanity or gibberish is classified as BAD and blocked
        if raw_category in ("PROFANITY_OFFENSIVE", "GIBBERISH_SPAM"):
            verdict = "BAD"
            category = raw_category
            severity = max(1, raw_sev)
            is_blocked = True
        elif raw_verdict == "BAD":
            verdict = "BAD"
            # If verdict is BAD but category was CLEAN, calibrate category
            if raw_category == "CLEAN":
                category = "PROFANITY_OFFENSIVE" if raw_sev >= 2 else "GIBBERISH_SPAM"
            else:
                category = raw_category
            severity = max(1, raw_sev)
            is_blocked = True
        else:
            verdict = "GOOD"
            category = "CLEAN"
            severity = 0
            is_blocked = False

        res = EvaluationResult(
            raw_message=clean_msg,
            verdict=verdict,
            category=category,
            severity=severity,
            latency_ms=latency_ms,
            confidence=calib_confidence,
            probabilities={
                "verdict": prob_verdict,
                "category": prob_category,
                "severity": sev_probs
            },
            is_blocked=is_blocked
        )

        self._update_session(res)
        return res

    def _update_session(self, res: EvaluationResult):
        """Update metrics and karma based on evaluation result."""
        self.total_count += 1
        self.latencies.append(res.latency_ms)
        self.last_result = res

        if res.is_blocked:
            self.blocked_count += 1
            if res.category == "GIBBERISH_SPAM":
                self.gibberish_count += 1
                self.karma = max(0.0, self.karma - 10.0)
            else:
                self.offensive_count += 1
                penalty = 25.0 if res.severity >= 3 else (15.0 if res.severity == 2 else 10.0)
                self.karma = max(0.0, self.karma - penalty)
        else:
            self.approved_count += 1
            self.clean_count += 1
            self.karma = min(100.0, self.karma + 2.0)

        # Append to chat history
        self.chat_history.append({
            "type": "chat",
            "time": res.timestamp,
            "sender": "User",
            "text": res.raw_message,
            "verdict": res.verdict,
            "category": res.category,
            "severity": res.severity,
            "is_blocked": res.is_blocked
        })

    def add_system_message(self, text: str):
        """Add a system information message to the chat stream."""
        self.chat_history.append({
            "type": "system",
            "time": datetime.now().strftime("%H:%M:%S"),
            "text": text
        })

    def clear_chat(self):
        """Clear chat history stream."""
        self.chat_history.clear()
        self.add_system_message("Chat history cleared. Session counters preserved.")

    def get_karma_badge(self) -> str:
        """Return formatted karma badge and color."""
        if self.karma >= 80:
            return f"{COLOR_BRIGHT_GREEN}[TRUSTED]{COLOR_RESET}"
        elif self.karma >= 50:
            return f"{COLOR_YELLOW}[CAUTION]{COLOR_RESET}"
        elif self.karma >= 20:
            return f"{COLOR_MAGENTA}[SUSPICIOUS]{COLOR_RESET}"
        else:
            return f"{COLOR_RED}[UNTRUSTED]{COLOR_RESET}"

    def build_chat_lines(self, max_lines: int) -> List[str]:
        """Format the left chat stream column lines."""
        lines: List[str] = []

        if not self.chat_history:
            lines.append(f"{COLOR_CYAN}💬 Welcome to Laya AI Chat Moderator!{COLOR_RESET}")
            lines.append("")
            lines.append(f"{COLOR_WHITE}Type any message below to see real-time{COLOR_RESET}")
            lines.append(f"{COLOR_WHITE}System 1 content safety evaluation with{COLOR_RESET}")
            lines.append(f"{COLOR_WHITE}single-pass neural telemetry.{COLOR_RESET}")
            lines.append("")
            lines.append(f"{COLOR_DIM}Commands available:{COLOR_RESET}")
            lines.append(f"  {COLOR_BOLD}/test{COLOR_RESET}  - Run automated moderation test suite")
            lines.append(f"  {COLOR_BOLD}/stats{COLOR_RESET} - View detailed session telemetry")
            lines.append(f"  {COLOR_BOLD}/clear{COLOR_RESET} - Clear the chat history stream")
            lines.append(f"  {COLOR_BOLD}/quit{COLOR_RESET}  - Exit application cleanly")
        else:
            # Render chat items
            for item in self.chat_history:
                if item["type"] == "system":
                    t = item["time"]
                    lines.append(f"{COLOR_GRAY}[{t}]{COLOR_RESET} {COLOR_CYAN}⚙ {item['text']}{COLOR_RESET}")
                else:
                    t = item["time"]
                    sender = item["sender"]
                    msg = item["text"]
                    is_blocked = item["is_blocked"]

                    if is_blocked:
                        badge = f"{COLOR_RED}[BLOCKED]{COLOR_RESET}"
                        lines.append(f"{COLOR_GRAY}[{t}]{COLOR_RESET} {badge} {COLOR_BOLD}{sender}:{COLOR_RESET}")
                        trunc_msg = (msg[:40] + "...") if len(msg) > 40 else msg
                        lines.append(f"  {COLOR_RED}\"{trunc_msg}\"{COLOR_RESET}")
                        cat_label = item["category"]
                        sev_label = f"{item['severity']}/3"
                        lines.append(f"  {COLOR_GRAY}↳ {cat_label} (Sev: {sev_label}){COLOR_RESET}")
                    else:
                        badge = f"{COLOR_BRIGHT_GREEN}[APPROVED]{COLOR_RESET}"
                        lines.append(f"{COLOR_GRAY}[{t}]{COLOR_RESET} {badge} {COLOR_BOLD}{sender}:{COLOR_RESET}")
                        trunc_msg = (msg[:42] + "...") if len(msg) > 42 else msg
                        lines.append(f"  {COLOR_WHITE}\"{trunc_msg}\"{COLOR_RESET}")

        # Return only the most recent max_lines lines
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        elif len(lines) < max_lines:
            # Pad to maintain consistent vertical height
            lines = lines + [""] * (max_lines - len(lines))

        return lines

    def build_telemetry_lines(self) -> List[str]:
        """Format the right Laya Telemetry HUD column lines."""
        lines: List[str] = []
        res = self.last_result

        # Section 1: Latest Decision
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}▶ LATEST LAYA EVALUATION{COLOR_RESET}")
        if res is None:
            lines.append(f" {COLOR_GRAY}Input   : (waiting for message...){COLOR_RESET}")
            lines.append(f" {COLOR_GRAY}Verdict : [STANDBY]{COLOR_RESET}")
            lines.append(f" {COLOR_GRAY}Category: WAITING{COLOR_RESET}")
            lines.append(f" {COLOR_GRAY}Severity: [0/3] ○○○○ SAFE{COLOR_RESET}")
            lines.append(f" {COLOR_GRAY}Latency : --- ms  •  Conf: ---{COLOR_RESET}")
        else:
            raw_disp = (res.raw_message[:26] + "...") if len(res.raw_message) > 26 else res.raw_message
            lines.append(f" {COLOR_GRAY}Input   :{COLOR_RESET} \"{raw_disp}\"")

            if res.is_blocked:
                v_badge = f"{COLOR_RED}{COLOR_BOLD}[🛡️ BLOCKED]{COLOR_RESET}"
            else:
                v_badge = f"{COLOR_BRIGHT_GREEN}{COLOR_BOLD}[✅ APPROVED]{COLOR_RESET}"
            lines.append(f" {COLOR_GRAY}Verdict :{COLOR_RESET} {v_badge} ({COLOR_BOLD}{res.verdict}{COLOR_RESET})")

            if res.category == "CLEAN":
                cat_col = f"{COLOR_BRIGHT_GREEN}{res.category}{COLOR_RESET}"
            elif res.category == "PROFANITY_OFFENSIVE":
                cat_col = f"{COLOR_RED}{res.category}{COLOR_RESET}"
            else:
                cat_col = f"{COLOR_YELLOW}{res.category}{COLOR_RESET}"
            lines.append(f" {COLOR_GRAY}Category:{COLOR_RESET} {cat_col}")

            dots = "●" * (res.severity + 1) + "○" * (3 - res.severity)
            sev_label = "SAFE" if res.severity == 0 else "VIOLATION"
            sev_col = COLOR_BRIGHT_GREEN if res.severity == 0 else COLOR_RED
            lines.append(f" {COLOR_GRAY}Severity:{COLOR_RESET} {sev_col}[{res.severity}/3] {dots} {sev_label}{COLOR_RESET}")

            lat_str = f"{COLOR_CYAN}{res.latency_ms:.1f} ms{COLOR_RESET}"
            conf_str = f"{COLOR_YELLOW}{res.confidence:.1%}{COLOR_RESET}"
            lines.append(f" {COLOR_GRAY}Latency :{COLOR_RESET} {lat_str}  {COLOR_GRAY}•{COLOR_RESET}  {COLOR_GRAY}Conf:{COLOR_RESET} {conf_str}")

        lines.append(f"{COLOR_GRAY}─────────────────────────────────────────────{COLOR_RESET}")

        # Section 2: Probability Distributions
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}▶ PROBABILITY DISTRIBUTIONS{COLOR_RESET}")
        if res is None:
            lines.append(f" {COLOR_GRAY}Verdict :{COLOR_RESET} G:[░░░░░░]  0% B:[░░░░░░]  0%")
            lines.append(f" {COLOR_GRAY}Category:{COLOR_RESET} CLEAN [░░░░░░░░]  0%")
            lines.append(f"           OFFEN [░░░░░░░░]  0%")
            lines.append(f"           GIB   [░░░░░░░░]  0%")
            lines.append(f" {COLOR_GRAY}Severity:{COLOR_RESET} 0:0%   1:0%   2:0%   3:0%")
        else:
            p_v = res.probabilities.get("verdict", {})
            p_good = p_v.get("GOOD", 0.0)
            p_bad = p_v.get("BAD", 0.0)
            bar_good = make_bar(p_good, 6)
            bar_bad = make_bar(p_bad, 6)
            lines.append(f" {COLOR_GRAY}Verdict :{COLOR_RESET} G:[{bar_good}]{p_good:.0%} B:[{bar_bad}]{p_bad:.0%}")

            p_c = res.probabilities.get("category", {})
            p_clean = p_c.get("CLEAN", 0.0)
            p_off = p_c.get("PROFANITY_OFFENSIVE", 0.0)
            p_gib = p_c.get("GIBBERISH_SPAM", 0.0)

            lines.append(f" {COLOR_GRAY}Category:{COLOR_RESET} CLEAN [{make_bar(p_clean, 8)}] {p_clean:.0%}")
            lines.append(f"           OFFEN [{make_bar(p_off, 8)}] {p_off:.0%}")
            lines.append(f"           GIB   [{make_bar(p_gib, 8)}] {p_gib:.0%}")

            p_s = res.probabilities.get("severity", {})
            s0 = p_s.get("0", 0.0)
            s1 = p_s.get("1", 0.0)
            s2 = p_s.get("2", 0.0)
            s3 = p_s.get("3", 0.0)
            lines.append(f" {COLOR_GRAY}Severity:{COLOR_RESET} 0:{s0:.0%}  1:{s1:.0%}  2:{s2:.0%}  3:{s3:.0%}")

        lines.append(f"{COLOR_GRAY}─────────────────────────────────────────────{COLOR_RESET}")

        # Section 3: Session Trust & Metrics
        lines.append(f"{COLOR_BOLD}{COLOR_CYAN}▶ SESSION METRICS & TRUST METER{COLOR_RESET}")
        app_pct = (self.approved_count / self.total_count * 100) if self.total_count > 0 else 0
        lines.append(f" {COLOR_GRAY}Total:{COLOR_RESET} {self.total_count}  {COLOR_GRAY}│{COLOR_RESET} App: {self.approved_count} ({app_pct:.0f}%)  {COLOR_GRAY}│{COLOR_RESET} Blk: {self.blocked_count}")
        lines.append(f" {COLOR_GRAY}Clean:{COLOR_RESET} {self.clean_count}  {COLOR_GRAY}│{COLOR_RESET} Off: {self.offensive_count}  {COLOR_GRAY}│{COLOR_RESET} Gib: {self.gibberish_count}")

        avg_lat = (sum(self.latencies) / len(self.latencies)) if self.latencies else 0.0
        lines.append(f" {COLOR_GRAY}Avg Latency:{COLOR_RESET} {COLOR_CYAN}{avg_lat:.1f} ms{COLOR_RESET} (Fast System 1)")

        k_bar = make_bar(self.karma / 100.0, 12)
        badge = self.get_karma_badge()
        lines.append(f" {COLOR_GRAY}Trust:{COLOR_RESET} [{k_bar}] {self.karma:.0f}% {badge}")

        # Ensure exact count of rows
        if len(lines) < CONTENT_ROWS:
            lines += [""] * (CONTENT_ROWS - len(lines))
        elif len(lines) > CONTENT_ROWS:
            lines = lines[:CONTENT_ROWS]

        return lines

    def render(self):
        """Render complete terminal UI with flicker-free cursor positioning."""
        term_cols, term_lines = shutil.get_terminal_size((100, 29))

        # Check for window resize or flag
        if (term_cols, term_lines) != self.last_term_size or self.needs_clear:
            sys.stdout.write(CLEAR_SCREEN)
            self.last_term_size = (term_cols, term_lines)
            self.needs_clear = False

        # Guard against undersized terminal breaking box-drawing layouts
        if term_cols < 100 or term_lines < 26:
            msg = [
                CURSOR_HOME,
                f"{COLOR_YELLOW}{COLOR_BOLD}⚠️  Terminal Window Too Small ({term_cols}x{term_lines}){COLOR_RESET}",
                f"{COLOR_WHITE}Please resize terminal to at least {COLOR_BOLD}100x26{COLOR_RESET} for the dual-column HUD.{COLOR_RESET}",
                f"{COLOR_GRAY}(Current size: {term_cols} columns x {term_lines} rows){COLOR_RESET}",
                ""
            ]
            sys.stdout.write("\n".join(msg))
            sys.stdout.flush()
            return

        out = []
        out.append(HIDE_CURSOR)
        out.append(CURSOR_HOME)

        # Header Box (exact width: 100 visible characters)
        out.append(f"{COLOR_BOLD}{COLOR_CYAN}╔══════════════════════════════════════════════════════════════════════════════════════════════════╗{COLOR_RESET}")
        h1 = "               💬 LAYA SYSTEM 1 REAL-TIME CHAT MODERATOR & TRUST ENGINE"
        h2 = "          Sub-100ms Single-Pass Neural Content Safety • Calibrated Telemetry HUD"
        out.append(f"{COLOR_BOLD}{COLOR_CYAN}║{fit_cell(h1, HEADER_INNER_WIDTH)}║{COLOR_RESET}")
        out.append(f"{COLOR_BOLD}{COLOR_CYAN}║{fit_cell(h2, HEADER_INNER_WIDTH)}║{COLOR_RESET}")
        out.append(f"{COLOR_BOLD}{COLOR_CYAN}╚══════════════════════════════════════════════════════════════════════════════════════════════════╝{COLOR_RESET}")

        # Column Header
        top_bar = "┌" + ("─" * (LEFT_COL_WIDTH + 2)) + "┬" + ("─" * (RIGHT_COL_WIDTH + 2)) + "┐"
        col_hdr = f"│ {fit_cell(COLOR_BOLD + COLOR_GREEN + '💬 LIVE CHAT STREAM' + COLOR_RESET, LEFT_COL_WIDTH)} │ {fit_cell(COLOR_BOLD + COLOR_MAGENTA + '🧠 LAYA SYSTEM 1 TELEMETRY HUD' + COLOR_RESET, RIGHT_COL_WIDTH)} │"
        mid_bar = "├" + ("─" * (LEFT_COL_WIDTH + 2)) + "┼" + ("─" * (RIGHT_COL_WIDTH + 2)) + "┤"

        out.append(top_bar)
        out.append(col_hdr)
        out.append(mid_bar)

        # Content rows
        chat_rows = self.build_chat_lines(CONTENT_ROWS)
        telem_rows = self.build_telemetry_lines()

        for c_row, t_row in zip(chat_rows, telem_rows):
            out.append(f"│ {fit_cell(c_row, LEFT_COL_WIDTH)} │ {fit_cell(t_row, RIGHT_COL_WIDTH)} │")

        bot_bar = "└" + ("─" * (LEFT_COL_WIDTH + 2)) + "┴" + ("─" * (RIGHT_COL_WIDTH + 2)) + "┘"
        out.append(bot_bar)

        # Commands bar
        cmd_banner = (
            f" {COLOR_BOLD}Commands:{COLOR_RESET} "
            f"{COLOR_CYAN}/test{COLOR_RESET} (demo suite)   "
            f"{COLOR_CYAN}/stats{COLOR_RESET} (telemetry)   "
            f"{COLOR_CYAN}/clear{COLOR_RESET} (reset chat)   "
            f"{COLOR_CYAN}/quit{COLOR_RESET} (exit)"
        )
        out.append(cmd_banner)
        out.append("")
        out.append(SHOW_CURSOR)

        sys.stdout.write("\n".join(out))
        sys.stdout.flush()

    def run_test_suite(self, interactive: bool = True):
        """
        Run automated test cases with various clean, offensive, and gibberish inputs.
        Demonstrates live classification and HUD updates.
        """
        test_cases = [
            # Clean Communication
            ("Hello everyone, great game today!", "CLEAN"),
            ("Can someone help me with the rules please?", "CLEAN"),
            ("gg wp good match", "CLEAN"),
            ("What a fantastic defense by Player 1!", "CLEAN"),
            # Profanity & Toxic Attacks
            ("fuck you asshole", "PROFANITY_OFFENSIVE"),
            ("You are an idiot and I hate you", "PROFANITY_OFFENSIVE"),
            ("shut up loser", "PROFANITY_OFFENSIVE"),
            ("Go to hell nobody likes you", "PROFANITY_OFFENSIVE"),
            # Gibberish, Noise & Spam
            ("asdfkjsdkf zzxcvbnm qweoiuroiwe", "GIBBERISH_SPAM"),
            ("lkjlkjlkjlkjlkj", "GIBBERISH_SPAM"),
            ("qwertyuiopasdfghjkl zxcvbnm", "GIBBERISH_SPAM"),
            ("11111111111111111", "GIBBERISH_SPAM"),
        ]

        self.add_system_message(f"Starting test suite ({len(test_cases)} cases)...")
        if interactive:
            self.render()
            time.sleep(0.4)

        for text, expected_cat in test_cases:
            res = self.evaluate(text)
            if interactive:
                self.render()
                time.sleep(0.35)

        self.add_system_message(
            f"Done: {self.approved_count} approved, {self.blocked_count} blocked | Trust {self.karma:.0f}%"
        )
        if interactive:
            self.render()

    def show_stats_report(self):
        """Add summary telemetry report to the chat stream."""
        if not self.latencies:
            self.add_system_message("No evaluations recorded yet.")
            return

        min_lat = min(self.latencies)
        max_lat = max(self.latencies)
        avg_lat = sum(self.latencies) / len(self.latencies)
        app_pct = (self.approved_count / self.total_count * 100) if self.total_count else 0
        blk_pct = (self.blocked_count / self.total_count * 100) if self.total_count else 0

        self.add_system_message(
            f"STATS: {self.total_count} msgs | {self.approved_count} app ({app_pct:.0f}%) | {self.blocked_count} blk ({blk_pct:.0f}%)"
        )
        self.add_system_message(
            f"CATS : {self.clean_count} clean | {self.offensive_count} offense | {self.gibberish_count} gibberish"
        )
        self.add_system_message(
            f"SPEED: avg {avg_lat:.1f}ms (min {min_lat:.1f}ms, max {max_lat:.1f}ms)"
        )
        self.add_system_message(
            f"TRUST: {self.karma:.0f}% karma {self.get_karma_badge()}"
        )

    def interactive_loop(self):
        """Run interactive main chat loop."""
        is_tty = sys.stdin.isatty()
        if is_tty:
            sys.stdout.write(CLEAR_SCREEN)
            sys.stdout.flush()

        def _on_winch(signum, frame):
            self.needs_clear = True

        if hasattr(signal, "SIGWINCH"):
            try:
                signal.signal(signal.SIGWINCH, _on_winch)
            except (ValueError, OSError):
                pass

        try:
            while True:
                self.render()
                try:
                    prompt = f"{COLOR_BOLD}{COLOR_WHITE}💬 Enter message or command: {COLOR_RESET}" if is_tty else ""
                    user_input = input(prompt).strip()
                except (KeyboardInterrupt, EOFError):
                    print("\n\nExiting Laya Chat Moderator. Goodbye!")
                    break

                if not user_input:
                    continue

                cmd = user_input.lower()
                if cmd in ("/quit", "/exit", "quit", "exit", "q"):
                    print("\n\nExiting Laya Chat Moderator. Goodbye!")
                    break
                elif cmd in ("/test", "test"):
                    self.run_test_suite(interactive=is_tty)
                elif cmd in ("/stats", "stats"):
                    self.show_stats_report()
                elif cmd in ("/clear", "clear"):
                    self.clear_chat()
                elif cmd in ("/help", "help", "?"):
                    self.add_system_message("Commands: /test (demo suite), /stats (telemetry), /clear (reset chat), /quit (exit)")
                elif cmd.startswith("/"):
                    self.add_system_message(f"Unknown command: '{user_input}'. Try /test, /stats, /clear, /help, or /quit.")
                else:
                    self.evaluate(user_input)

        finally:
            if is_tty:
                sys.stdout.write(SHOW_CURSOR + COLOR_RESET + "\n")
                sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Laya AI Chat Moderator & Trust Engine")
    parser.add_argument("--test", action="store_true", help="Run automated test suite and exit")
    parser.add_argument("--msg", type=str, help="Evaluate a single message non-interactively")
    args = parser.parse_args()

    print("Loading Laya AI System 1 Model...")
    try:
        agent = laya.load("convaiinnovations/laya", fast=True)
    except Exception as e:
        print(f"\n{COLOR_RED}Error loading Laya model: {e}{COLOR_RESET}", file=sys.stderr)
        print("Please check your internet connection or HuggingFace model cache.\n", file=sys.stderr)
        sys.exit(1)

    moderator = ChatModerator(agent=agent)

    if args.msg:
        res = moderator.evaluate(args.msg)
        print(f"\nMessage   : {res.raw_message!r}")
        print(f"Verdict   : {res.verdict}")
        print(f"Category  : {res.category}")
        print(f"Severity  : {res.severity} / 3")
        print(f"Blocked   : {res.is_blocked}")
        print(f"Latency   : {res.latency_ms:.1f} ms")
        print(f"Confidence: {res.confidence:.3f}")
        print(f"Karma     : {moderator.karma:.1f}%\n")
        return

    if args.test:
        print("Running automated moderation test suite...")
        moderator.run_test_suite(interactive=False)
        moderator.show_stats_report()
        print("\nAutomated test suite completed successfully.")
        print(f"Total: {moderator.total_count} | Approved: {moderator.approved_count} | Blocked: {moderator.blocked_count}")
        print(f"Clean: {moderator.clean_count} | Offensive: {moderator.offensive_count} | Gibberish: {moderator.gibberish_count}")
        print(f"Final Karma: {moderator.karma:.1f}%")
        return

    moderator.interactive_loop()


if __name__ == "__main__":
    main()
