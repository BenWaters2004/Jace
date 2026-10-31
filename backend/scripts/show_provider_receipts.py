"""Local-only, read-only inspection of model adapter invocation receipts.

Run on Jace Core host, using the same Python environment/configuration as Core:
    python backend/scripts/show_provider_receipts.py --limit 25

Do not expose this as an unauthenticated web route; future API needs ownership.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jace.database import SessionLocal, close_database
from jace.model_gateway.receipts import ModelInvocationReceipt


async def inspect(limit: int) -> None:
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(ModelInvocationReceipt))
        rows = (await session.execute(
            select(ModelInvocationReceipt)
            .order_by(ModelInvocationReceipt.created_at.desc())
            .limit(limit)
        )).scalars().all()
    print(f"C5B.1 adapter invocation receipts: {total or 0} persisted")
    print("Amounts are Jace estimates, not verified provider bills.")
    for row in rows:
        tokens = (f"{row.input_tokens}/{row.output_tokens}"
                  if row.input_tokens is not None and row.output_tokens is not None
                  else "unavailable")
        usd = (f"${row.estimated_cost_usd:.8f} est."
               if row.estimated_cost_usd is not None else "unpriced")
        changed = " [privacy rerouted]" if row.route_changed else ""
        print(f"{row.created_at.isoformat()} {row.provider_id}:{row.model} "
              f"{row.capability}/{row.operation} {row.status} "
              f"{row.latency_ms:.0f}ms tokens(in/out)={tokens} {usd}{changed}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error('--limit must be from 1 through 100')
    async def run() -> None:
        try:
            await inspect(args.limit)
        finally:
            await close_database()
    asyncio.run(run())


if __name__ == '__main__':
    main()
