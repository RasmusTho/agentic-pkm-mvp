"""Entry point for python -m app.dispatcher"""

import sys

from app.dispatcher.cli import main

if __name__ == "__main__":
    sys.exit(main())
