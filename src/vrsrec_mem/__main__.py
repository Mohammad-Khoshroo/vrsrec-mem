"""Allow ``python -m vrsrec_mem``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
