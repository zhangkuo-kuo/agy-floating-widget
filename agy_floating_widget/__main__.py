"""CLI / module entry point for agy-floating-widget."""

import tkinter as tk
import traceback

from .config import CRASH_LOG_FILE, PID_FILE
from .platform_utils import enable_dpi_awareness, ensure_single_instance, remove_pid_file
from .ui import FloatingWidget


def main():
    enable_dpi_awareness()
    try:
        ensure_single_instance(PID_FILE)
        root = tk.Tk()
        FloatingWidget(root)
        root.mainloop()
    except Exception:
        with open(CRASH_LOG_FILE, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    finally:
        remove_pid_file(PID_FILE)


if __name__ == "__main__":
    main()
