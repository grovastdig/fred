"""
scripts/morning_run.py
======================
Manual trigger for the morning brief.
Useful for testing or when you want a brief outside scheduled time.

Usage:
    python scripts/morning_run.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def main():
    print("🌅 Triggering morning brief...")

    from alerts.morning_brief import MorningBriefGenerator
    generator = MorningBriefGenerator()
    await generator.generate_and_send()

    print("✅ Morning brief sent to your phone.")


if __name__ == "__main__":
    asyncio.run(main())
