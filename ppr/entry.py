"""The `ppr` command.

An installed ppr (`uv tool install git+…`) has only the search and data
commands (`ppr/client_cli.py`). A checkout has every command (`ppr/cli.py`),
which needs the pipeline's dependencies; an editable install of a checkout
without them still searches, and says how to run the rest.
"""

import sys

from dotenv import load_dotenv

from ppr import client_cli, layout


def _command(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not layout.is_checkout():
        client_cli.main(argv)
        return
    load_dotenv(layout.ROOT / ".env")
    try:
        from ppr import cli
    except ModuleNotFoundError as exc:
        command = _command(argv)
        if command is None or command in client_cli.CLIENT_COMMANDS:
            client_cli.main(argv)
            return
        raise SystemExit(f"`ppr {command}` needs the repository environment ({exc.name} is not installed): "
                         f"run `uv run ppr {command} …` inside the checkout")
    cli.main(argv)


if __name__ == "__main__":
    main()
