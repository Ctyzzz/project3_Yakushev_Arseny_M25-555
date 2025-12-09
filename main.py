from __future__ import annotations

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    from valutatrade_hub.cli.interface import run_cli
    run_cli()


if __name__ == "__main__":
    main()
