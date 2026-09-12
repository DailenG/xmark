import argparse
import asyncio
import sys

from xmark.api import XBookmarkClient, XAPIError
from xmark.tui import main as run_tui


async def get_count(refresh: bool = False) -> int:
    async with XBookmarkClient() as client:
        try:
            collection = await client.fetch_bookmarks(use_cache=not refresh)
            return collection.count
        except XAPIError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 0


async def refresh_cache() -> bool:
    async with XBookmarkClient() as client:
        try:
            await client.fetch_bookmarks(use_cache=False)
            return True
        except XAPIError as e:
            print(f"Error: {e}", file=sys.stderr)
            return False


def main():
    parser = argparse.ArgumentParser(description="Xmark - Browse X (Twitter) bookmarks")
    parser.add_argument("--count", action="store_true", help="Print bookmark count and exit")
    parser.add_argument("--refresh", action="store_true", help="Force cache refresh")
    args = parser.parse_args()

    if args.count:
        count = asyncio.run(get_count(refresh=args.refresh))
        print(count)
        return 0
    elif args.refresh:
        success = asyncio.run(refresh_cache())
        return 0 if success else 1
    else:
        run_tui()
        return 0


if __name__ == "__main__":
    sys.exit(main())