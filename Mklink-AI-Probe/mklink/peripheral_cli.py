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
    parser.add_argument("--project-root", default=".")
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument("--chip")
    selectors.add_argument("--target-id")
    selectors.add_argument("--svd")
    parser.add_argument("--query", default="")
    parser.add_argument("--port")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--period", type=float, default=0.01)


def run(args):
    from .peripheral_watch import (
        discover_svd_targets,
        load_catalog,
        save_catalog_selection,
        read_item,
        capture_items,
    )

    try:
        if args.action == "targets":
            result = {
                "targets": [
                    t.public()
                    for t in discover_svd_targets(args.project_root)
                    if args.query.casefold() in t.target.casefold()
                ]
            }
        else:
            catalog = load_catalog(
                args.project_root,
                target_id=args.target_id,
                chip=args.chip,
                svd=args.svd,
            )
            if catalog is None:
                raise ValueError("Select a chip with peripherals select first")
            if args.action == "select":
                save_catalog_selection(args.project_root, catalog)
                result = catalog.public(args.query)
            elif args.action == "list":
                result = catalog.public(args.query)
            else:
                items = [catalog.resolve(n) for n in args.names]
                if not items:
                    raise ValueError("Specify register or field names")
                from .device import connect

                with connect(port=args.port, project_root=args.project_root) as device:
                    if args.action == "read":
                        result = {
                            "values": {i.name: read_item(device, i) for i in items}
                        }
                    else:
                        result = capture_items(
                            device, items, duration=args.duration, period=args.period
                        )
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
