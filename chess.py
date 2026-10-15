#!/usr/bin/env python3
"""
Backwards-compatibility stub for checkers.py.
Note: chess.py has been renamed to checkers.py.
"""

import sys

# Print a user-visible notice
print("\033[93m[Notice] chess.py has been renamed to checkers.py. Delegating to checkers.py...\033[0m", file=sys.stderr)

from checkers import CheckersGame, main

if __name__ == "__main__":
    main()
