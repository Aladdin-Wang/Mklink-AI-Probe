"""CLI adapter for the shared peripheral catalog and capture service."""

import json


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "peripherals", help="Shared chip/register/field catalog"
    )
    parser.add_argument(
        "action", choices=["targets", "select", "list", "read", "capture"]
    )
    parser.add_argument("names", nargs="*")
    parser.add_argument("--project-root", default=None)
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument("--chip")
    selectors.add_argument("--target-id")
    selectors.add_argument("--svd")
    parser.add_argument("--query", default="")
    parser.add_argument("--port")
    parser.add_argument("--probe", help="Shared backend probe ID or local alias")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--period", type=float, default=0.01)


def run_offline_targets(args):
    from .peripheral_watch import list_svd_targets

    if args.probe or args.port:
        raise SystemExit('targets is offline; select a local --project-root, not a probe/port')
    print(json.dumps(list_svd_targets(args.project_root or '.', args.query), ensure_ascii=False))
