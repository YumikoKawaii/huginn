#!/usr/bin/env python3
"""
huginn — unified CLI entrypoint.

Usage:
    .venv/bin/python huginn.py crawl    # run the ECS crawler (priority → discovery → upload)
    .venv/bin/python huginn.py bot      # run the ECS bot (long-running traffic simulator)
"""

import argparse
import sys


def cmd_crawl(_args):
    from crawler.runner import main
    main()


def cmd_bot(_args):
    import asyncio
    from bot.runner import main
    asyncio.run(main())


def main():
    parser = argparse.ArgumentParser(
        prog="huginn",
        description="Huginn manga crawler and traffic bot",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    sub.add_parser("crawl", help="Run the crawler (priority sync → discovery → download → upload)")
    sub.add_parser("bot",   help="Run the traffic bot (long-running, 20 CCU)")

    args = parser.parse_args()

    dispatch = {"crawl": cmd_crawl, "bot": cmd_bot}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
