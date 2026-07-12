"""Put the repo root on sys.path so `import mini_store` works when pytest runs from anywhere."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
