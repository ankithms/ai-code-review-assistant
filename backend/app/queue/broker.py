import os

import dramatiq
from dotenv import load_dotenv
from dramatiq.brokers.redis import RedisBroker

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")
REDIS_MAINTENANCE_CHANCE = int(
    os.getenv("DRAMATIQ_REDIS_MAINTENANCE_CHANCE", "100000")
)

if not REDIS_URL:
    raise RuntimeError("REDIS_URL is not configured")

if not 0 <= REDIS_MAINTENANCE_CHANCE <= 1_000_000:
    raise RuntimeError(
        "DRAMATIQ_REDIS_MAINTENANCE_CHANCE must be between 0 and 1000000"
    )

redis_broker = RedisBroker(
    url=REDIS_URL,
    maintenance_chance=REDIS_MAINTENANCE_CHANCE,
)
dramatiq.set_broker(redis_broker)
