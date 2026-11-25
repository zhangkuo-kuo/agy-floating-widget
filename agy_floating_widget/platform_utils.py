"""Cross-platform helpers for Windows and Linux."""

import json
import os
import re
import signal
import subprocess
import sys


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_ui_fonts():
    """Return (sans_family, mono_family) tuned for the current OS."""
    if sys.platform == "win32":
        return ("Segoe UI", "Consolas")
    if sys.platform == "darwin":
        return ("SF Pro Text", "Menlo")
    return ("DejaVu Sans", "DejaVu Sans Mono")


def enforce_window_topmost(root):
    try:
        if sys.platform == "win32":
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0013)
        root.lift()
        root.attributes("-topmost", True)
    except Exception:
        pass


def bind_mouse_wheel(widget, callback):
    """Bind scroll wheel across Windows (<MouseWheel>) and Linux (<Button-4>/<Button-5>)."""
    def _on_wheel(event):
        delta = getattr(event, "delta", 0)
        if delta:
            steps = -1 if delta > 0 else 1
            return callback(steps)
        return None

    widget.bind("<MouseWheel>", _on_wheel)
    widget.bind("<Button-4>", lambda e: callback(-1))
    widget.bind("<Button-5>", lambda e: callback(1))


def discover_ls_processes():
    """Return list of dicts: [{'cmdline': str, 'ports': [int, ...]}] for Antigravity language_server."""
    procs = _discover_via_psutil()
    if procs is not None:
        return procs
    if sys.platform == "win32":
        return _discover_windows_powershell()
    return _discover_posix_fallback()


def _discover_via_psutil():
    try:
        import psutil
    except ImportError:
        return None

    results = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline_list = proc.info.get("cmdline") or []
            cl = " ".join(cmdline_list)
            if "language_server" not in name and "language_server" not in cl.lower():
                continue
            if "--csrf_token" not in cl:
                continue
            ports = []
            for conn in proc.net_connections(kind="inet"):
                if getattr(conn, "status", "") == psutil.CONN_LISTEN and conn.laddr:
                    ports.append(conn.laddr.port)
            if ports:
                results.append({"cmdline": cl, "ports": sorted(set(ports))})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return results


def _discover_windows_powershell():
    try:
        cmd = (
            "$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -like '*language_server*' -and $_.CommandLine -like '*--csrf_token*' }; "
            "$res = @(); foreach ($p in $procs) { "
            "  $cl = $p.CommandLine; $targetPid = $p.ProcessId; "
            "  $ports = (Get-NetTCPConnection -OwningProcess $targetPid -State Listen -ErrorAction SilentlyContinue).LocalPort; "
            "  if ($ports) { $res += [PSCustomObject]@{ Cl=$cl; Ports=@($ports) } } "
            "}; $res | ConvertTo-Json -Depth 3"
        )
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", cmd],
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        items = json.loads(raw) if raw.strip() else []
        if isinstance(items, dict):
            items = [items]
        out = []
        for item in items:
            ports = item.get("Ports") or []
            if isinstance(ports, int):
                ports = [ports]
            out.append({"cmdline": item.get("Cl") or "", "ports": [int(p) for p in ports]})
        return out
    except Exception:
        return []


def _discover_posix_fallback():
    """Fallback process/port discovery on Linux/macOS without psutil."""
    candidates = {}
    if os.path.isdir("/proc"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as f:
                    cl = f.read().replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
                if "language_server" in cl.lower() and "--csrf_token" in cl:
                    candidates[int(entry)] = cl
            except Exception:
                continue
    else:
        try:
            raw = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
            for line in raw.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    cl = parts[1]
                    if "language_server" in cl.lower() and "--csrf_token" in cl:
                        candidates[int(parts[0])] = cl
        except Exception:
            pass

    if not candidates:
        return []

    pid_ports = _posix_listening_ports(set(candidates.keys()))
    results = []
    for pid, cl in candidates.items():
        ports = sorted(pid_ports.get(pid, set()))
        if ports:
            results.append({"cmdline": cl, "ports": ports})
    return results


def _posix_listening_ports(target_pids):
    pid_ports = {pid: set() for pid in target_pids}
    # Try `ss -tlpn` first (standard on modern Linux)
    try:
        raw = subprocess.check_output(["ss", "-tlpn"], text=True, stderr=subprocess.DEVNULL)
        for line in raw.splitlines():
            m_pid = re.search(r"pid=(\d+)", line)
            if not m_pid:
                continue
            pid = int(m_pid.group(1))
            if pid not in pid_ports:
                continue
            m_port = re.search(r":(\d+)\s", line)
            if m_port:
                pid_ports[pid].add(int(m_port.group(1)))
        if any(pid_ports.values()):
            return pid_ports
    except Exception:
        pass

    # Fallback to `lsof`
    try:
        raw = subprocess.check_output(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in raw.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 9 and cols[1].isdigit():
                pid = int(cols[1])
                if pid in pid_ports:
                    m_port = re.search(r":(\d+)$", cols[8])
                    if m_port:
                        pid_ports[pid].add(int(m_port.group(1)))
    except Exception:
        pass
    return pid_ports


def ensure_single_instance(pid_file: str):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                _terminate_previous_widget(old_pid)
        except Exception:
            pass
    try:
        with open(pid_file, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _terminate_previous_widget(old_pid: int):
    markers = ("agy_floating_widget", "agy-widget", "antigravity_floating_widget")
    try:
        import psutil
        if psutil.pid_exists(old_pid):
            p = psutil.Process(old_pid)
            cl = " ".join(p.cmdline())
            if any(m in cl for m in markers):
                p.terminate()
                try:
                    p.wait(timeout=1.5)
                except psutil.TimeoutExpired:
                    p.kill()
        return
    except ImportError:
        pass
    except Exception:
        return

    # POSIX fallback without psutil
    if sys.platform != "win32":
        try:
            cmdline_path = f"/proc/{old_pid}/cmdline"
            cl = ""
            if os.path.exists(cmdline_path):
                with open(cmdline_path, "rb") as f:
                    cl = f.read().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
            else:
                cl = subprocess.check_output(["ps", "-p", str(old_pid), "-o", "args="], text=True)
            if any(m in cl for m in markers):
                os.kill(old_pid, signal.SIGTERM)
        except Exception:
            pass


def remove_pid_file(pid_file: str):
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass
