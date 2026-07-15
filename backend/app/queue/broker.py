import os

import dramatiq
from dotenv import load_dotenv
from dramatiq.brokers.redis import RedisBroker

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")

if not REDIS_URL:
    raise RuntimeError("REDIS_URL is not configured")

redis_broker = RedisBroker(url=REDIS_URL)
dramatiq.set_broker(redis_broker)
