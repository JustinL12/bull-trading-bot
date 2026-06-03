"""CLI wrapper: post a needs-attention alert to Discord.

Usage:
    python scripts/post_attention.py --title "TITLE" --description "DETAILS" [--level warning|critical]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notify import post_attention


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--level", default="warning", choices=["warning", "critical"])
    args = parser.parse_args()
    post_attention(args.title, args.description, level=args.level)
    print(f"Attention alert sent: [{args.level.upper()}] {args.title}")


if __name__ == "__main__":
    main()
