import argparse
import json
import sys
from pathlib import Path

from .checker import check
from .loader import load_scenario
from .paths import DEFAULT_SCENARIO, ROOT
from .report import report
from .solve import solve
from .whatif import load_patch, run_whatif


def _find(name: str, folder: str) -> Path:
    """A path as typed, else the same name inside the project's folder."""
    p = Path(name)
    return p if p.exists() else ROOT / folder / p.name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clinic-planner")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check", help="list every rule a fully placed plan breaks")
    p.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO), help="scenario YAML (default: the project's scenarios/current.yaml)")
    p = sub.add_parser("solve", help="place open sessions, or explain why that is impossible")
    p.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO), help="scenario YAML (default: the project's scenarios/current.yaml)")
    p.add_argument("--json", help="write the solved plan to this JSON file")
    p.add_argument("--time", type=float, default=30.0, help="solver time limit in seconds")
    p = sub.add_parser("whatif", help="apply patch file(s) to a scenario and show what changes")
    p.add_argument("scenario")
    p.add_argument("patches", nargs="+", help="patch YAML files, applied in order")
    p.add_argument("--time", type=float, default=30.0)
    p = sub.add_parser("serve", help="local web UI")
    p.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO), help="scenario YAML (default: the project's scenarios/current.yaml)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="do not open the page automatically")
    p = sub.add_parser("report", help="room grid, people, idle time and utilisation")
    p.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO), help="scenario YAML (default: the project's scenarios/current.yaml)")
    args = parser.parse_args(argv)

    if args.command == "check":
        result = check(load_scenario(args.scenario))
        print(result.text())
        return 1 if result.errors else 0
    if args.command == "whatif":
        text = _find(args.scenario, "scenarios").read_text()
        output, ok = run_whatif(text, [load_patch(_find(x, "patches")) for x in args.patches], args.time)
        print(output)
        return 0 if ok else 1
    if args.command == "serve":
        return _serve(args)
    if args.command == "report":
        print(report(load_scenario(args.scenario)))
        return 0
    if args.command == "solve":
        return _solve(args)
    return 2


def _serve(args) -> int:
    import socket
    import threading
    import webbrowser

    import uvicorn

    from .web import create_app

    with socket.socket() as probe:
        if probe.connect_ex((args.host, args.port)) == 0:
            print(f"Port {args.port} is already in use by another program. Try --port {args.port + 1}.")
            return 1
    url = f"http://{args.host}:{args.port}"
    print(f"Planner running at {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    uvicorn.run(create_app(args.scenario), host=args.host, port=args.port, log_level="warning")
    return 0


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
