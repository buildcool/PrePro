"""Entry point of the frozen engine (PyInstaller): the same CLI as `prepro`, used by the desktop app."""

import multiprocessing


def main() -> None:
    multiprocessing.freeze_support()
    from prepro.cli import app

    app()


if __name__ == "__main__":
    main()
