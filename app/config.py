"""Central config -- reads everything from the environment, with sane local
defaults so `docker-compose up` + this app just works without extra setup.
"""

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://ops_tower:ops_tower@localhost:5432/ops_tower",
)

# How far back to look when checking whether an incoming order is a
# duplicate of one already on file. Configurable because "duplicate" is a
# business decision (same request re-submitted in the last few minutes vs.
# a legitimately recurring order a week later), not a fixed constant.
DUPLICATE_WINDOW_MINUTES = int(os.getenv("DUPLICATE_WINDOW_MINUTES", "1440"))  # 24h

ALLOWED_PRIORITIES = ("low", "normal", "high", "urgent")
