import argparse
import sys

from .checker import check
from .loader import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="list every rule a fully placed plan breaks")
    p.add_argument("scenario", help="path to a scenario YAML file")
    args = parser.parse_args(argv)

    if args.command == "check":
        report = check(load_scenario(args.scenario))
        print(report.text())
        return 1 if report.errors else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
