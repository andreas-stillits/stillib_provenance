from __future__ import annotations

from argparse import ArgumentParser

from .scaffold import init_config


def main(argv: list[str] | None = None) -> None:
    """
    Command line interface for stillib_provenance.
    """

    parser = ArgumentParser(
        prog="stillib_provenance",
        description="A CLI tool for initializing a config.py template file.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands.")

    init_parser = subparsers.add_parser(
        "init", help="Initialize a new config.py template file."
    )
    init_parser.add_argument(
        "path",
        nargs="?",
        default="config.py",
        help="Path to the destination config.py file. Defaults to 'config.py' in the current directory.",
    )

    args = parser.parse_args(argv)

    # call init_config if the init command is invoked
    if args.command == "init":
        init_config(args.path)

    return


if __name__ == "__main__":
    raise SystemExit(main())
