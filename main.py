"""NeuraFlow RC Car Bridge — entry point."""

from backend import log, start_backend, stop_backend
from gui import App


def main() -> None:
    log("info", "NeuraFlow RC Car Bridge starting...")
    start_backend()
    try:
        App().mainloop()
    finally:
        stop_backend()


if __name__ == "__main__":
    main()
