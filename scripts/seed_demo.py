"""Seed the deterministic demo corpus and baseline policy into MongoDB."""
import asyncio

from app.config import Settings
from app.demo.generator import Dataset
from app.demo.scenarios import seed
from app.persistence.mongo import connect, init_indexes


async def main() -> None:
    settings = Settings.from_env()
    client, db = connect(settings)
    try:
        await init_indexes(db)
        result = await seed(db, Dataset(settings.dataset_dir))
        print(f"Seed complete: {result['historical_records']:,} historical records; "
              f"{result['stream_total']:,} live stream records available.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
