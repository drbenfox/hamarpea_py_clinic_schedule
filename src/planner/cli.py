import argparse
import json
import sys
from pathlib import Path

from .checker import check
from .loader import load_scenario
from .report import report
from .solve import solve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planner")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="list every rule a fully placed plan breaks")
    p.add_argument("scenario", help="path to a scenario YAML file")
    p = sub.add_parser("solve", help="place open sessions, or explain why that is impossible")
    p.add_argument("scenario")
    p.add_argument("--json", help="write the solved plan to this JSON file")
    p.add_argument("--time", type=float, default=30.0, help="solver time limit in seconds")
    p = sub.add_parser("report", help="room grid, people, idle time and utilisation")
    p.add_argument("scenario")
    args = parser.parse_args(argv)

    if args.command == "check":
        result = check(load_scenario(args.scenario))
        print(result.text())
        return 1 if result.errors else 0
    if args.command == "report":
        print(report(load_scenario(args.scenario)))
        return 0
    if args.command == "solve":
        return _solve(args)
    return 2


def _solve(args) -> int:
    result = solve(load_scenario(args.scenario), args.time)
    if result.status == "infeasible":
        print("INFEASIBLE. These cannot all hold together; relax or unlock any one to make progress:")
        for line in result.core:
            print(f"  - {line}")
        return 1
    if result.status != "solved":
        print(f"No answer within {args.time:.0f}s. Try --time with a larger value.")
        return 1
    sc = result.scenario
    print(f"SOLVED (objective {result.objective}; lower is better)")
    if result.free:
        print("Placed by the solver:")
        for s in sc.sessions:
            if s.id in result.free:
                print(f"  - {s.id}: {s.day} {s.start}-{s.end} in {', '.join(s.rooms.primary)}")
    else:
        print("Nothing was left open; the plan as written is feasible.")
    print()
    print(check(sc).text())
    if args.json:
        data = {"objective": result.objective, "sessions": sc.model_dump(mode="json")["sessions"]}
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(data, indent=2))
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
