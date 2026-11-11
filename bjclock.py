"""Offline Beijing taskbar clock. Python standard library only, Windows only."""
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sys
import traceback

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'config.json'
TITLE = 'BJClock.Offline.UTC8'
u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32', use_last_error=True)

def bind(dll, name, result, *args):
    f = getattr(dll, name)
    f.restype, f.argtypes = result, list(args)
    return f

find = bind(u, 'FindWindowW', W.HWND, W.LPCWSTR, W.LPCWSTR)
rect_api = bind(u, 'GetWindowRect', W.BOOL, W.HWND, C.POINTER(W.RECT))
getlong = bind(u, 'GetWindowLongPtrW', C.c_ssize_t, W.HWND, C.c_int)
setlong = bind(u, 'SetWindowLongPtrW', C.c_ssize_t, W.HWND, C.c_int, C.c_ssize_t)
setpos = bind(u, 'SetWindowPos', W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
ancestor = bind(u, 'GetAncestor', W.HWND, W.HWND, W.UINT)
dpi_api = bind(u, 'GetDpiForWindow', W.UINT, W.HWND)
create_event = bind(k, 'CreateEventW', W.HANDLE, C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR)
open_event = bind(k, 'OpenEventW', W.HANDLE, W.DWORD, W.BOOL, W.LPCWSTR)
signal = bind(k, 'SetEvent', W.BOOL, W.HANDLE)
wait = bind(k, 'WaitForSingleObject', W.DWORD, W.HANDLE, W.DWORD)
close = bind(k, 'CloseHandle', W.BOOL, W.HANDLE)
mutex_api = bind(k, 'CreateMutexW', W.HANDLE, C.c_void_p, W.BOOL, W.LPCWSTR)
EVENT = 'Local\\BJClock.Stop.' + os.environ.get('USERNAME', 'user')
MUTEX = EVENT + '.Instance'
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
enum_children = bind(u, 'EnumChildWindows', W.BOOL, W.HWND, CALLBACK, W.LPARAM)
class_api = bind(u, 'GetClassNameW', C.c_int, W.HWND, W.LPWSTR, C.c_int)

def rectangle(hwnd):
    r = W.RECT()
    if not hwnd or not rect_api(hwnd, C.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)

def taskbar_info():
    hwnd = find('Shell_TrayWnd', None)
    children = []
    @CALLBACK
    def visit(child, unused):
        name = C.create_unicode_buffer(256)
        class_api(child, name, 256)
        children.append((name.value, rectangle(child)))
        return True
    if hwnd:
        enum_children(hwnd, visit, 0)
    return hwnd, rectangle(hwnd), children

def stop():
    event = open_event(2, False, EVENT)
    if event:
        signal(event)
        close(event)

def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--mode', choices=['left', 'above'])
    parser.add_argument('--x-offset', type=int)
    parser.add_argument('--y-offset', type=int)
    args = parser.parse_args()
    if args.stop:
        stop()
        return
    try:
        awareness = bind(u, 'SetProcessDpiAwarenessContext', W.BOOL, C.c_void_p)
        awareness(C.c_void_p(-4))
    except AttributeError:
        u.SetProcessDPIAware()
    if args.diagnose:
        hwnd, r, children = taskbar_info()
        print(json.dumps({'taskbar': r, 'dpi': dpi_api(hwnd) if hwnd else None,
                          'children': children}, ensure_ascii=False))
        return
    mutex = mutex_api(None, False, MUTEX)
    if C.get_last_error() == 183:
        close(mutex)
        return
    event = create_event(None, True, False, EVENT)
    import tkinter as tk
    from tkinter import font as tkfont
    root = tk.Tk()
    root.withdraw()
    root.title(TITLE)
    root.overrideredirect(True)
    root.wm_attributes('-toolwindow', True)
    root.wm_attributes('-topmost', True)
    key = '#010203'
    root.configure(bg=key)
    root.wm_attributes('-transparentcolor', key)
    families = set(tkfont.families(root))
    family = 'Segoe UI Variable Display' if 'Segoe UI Variable Display' in families else 'Segoe UI'
    face = tkfont.Font(family=family, size=-12)
    label = tk.Label(root, text='', font=face, fg='white', bg=key,
                     borderwidth=0, highlightthickness=0, padx=2, pady=0,
                     justify='center', takefocus=False)
    label.pack(fill='both', expand=True)
    root.update_idletasks()
    hwnd = ancestor(root.winfo_id(), 2)
    # Layered + transparent passes mouse input to other processes beneath us.
    # Toolwindow suppresses Alt-Tab/taskbar; NoActivate preserves keyboard focus.
    style = (getlong(hwnd, -20) | 0x80000 | 0x20 | 0x80 | 0x08000000) & ~0x40000
    setlong(hwnd, -20, style)
    defaults = dict(mode='left', x_offset=0, y_offset=0, gap=8, color='auto')
    config_stamp = None
    config = defaults.copy()
    previous = None
    shown = False

    def tick():
        nonlocal config_stamp, config, previous, shown
        if wait(event, 0) == 0:
            root.destroy()
            return
        try:
            stamp = CONFIG.stat().st_mtime_ns
            if stamp != config_stamp:
                new = defaults | json.loads(CONFIG.read_text(encoding='utf-8-sig'))
                if new['mode'] not in ('left', 'above'):
                    raise ValueError('mode must be left or above')
                for field in ('x_offset', 'y_offset', 'gap'):
                    new[field] = int(new[field])
                if new['color'] != 'auto':
                    root.winfo_rgb(new['color'])
                config, config_stamp = new, stamp
                (BASE / 'config-error.txt').unlink(missing_ok=True)
        except Exception as exc:
            message = str(exc)
            error_path = BASE / 'config-error.txt'
            if not error_path.exists() or error_path.read_text(encoding='utf-8') != message:
                error_path.write_text(message, encoding='utf-8')
        effective = config.copy()
        for field in ('mode', 'x_offset', 'y_offset'):
            value = getattr(args, field)
            if value is not None:
                effective[field] = value
        tb, r, children = taskbar_info()
        if not r:
            root.withdraw()
            shown = False
            root.after(1000, tick)
            return
        dpi = dpi_api(tb) or 96
        scale = dpi / 96
        face.configure(size=-round(9 * dpi / 72))
        bj = datetime.now(timezone.utc) + timedelta(hours=8)
        text = f'BJ {bj:%H:%M}\n{bj:%m-%d} 周' + '一二三四五六日'[bj.weekday()]
        color = effective['color']
        if color == 'auto':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as reg:
                    light = winreg.QueryValueEx(reg, 'SystemUsesLightTheme')[0]
                color = '#202020' if light else '#ffffff'
            except OSError:
                color = '#ffffff'
        label.configure(text=text, fg=color)
        w = max(face.measure('11-28 周三'), face.measure('BJ 23:59')) + round(8 * scale)
        h = face.metrics('linespace') * 2 + round(2 * scale)
        # All native rectangles are physical pixels under per-monitor DPI awareness.
        tray = next((box for name, box in children if name == 'TrayNotifyWnd' and box and box[2] > box[0]), None)
        clock = next((box for name, box in children if 'Clock' in name and box and box[2] > box[0]), None)
        gap = round(effective['gap'] * scale)
        if effective['mode'] == 'above':
            anchor = clock or (r[2] - round(120 * scale), r[1], r[2] - round(12 * scale), r[3])
            x = (anchor[0] + anchor[2] - w) // 2
            y = r[1] - h - gap
        else:
            # Keep notification icons usable: use the free space just left of tray.
            x = (tray[0] if tray else r[2] - round(240 * scale)) - w - gap
            y = r[1] + (r[3] - r[1] - h) // 2
        x += round(effective['x_offset'] * scale)
        y += round(effective['y_offset'] * scale)
        state = (x, y, w, h, dpi, r, color, effective['mode'])
        if state != previous or not shown:
            # Pin Tk's requested size too, or its geometry manager shrinks the
            # native window back to the label's natural size on the next idle.
            root.geometry(f'{w}x{h}+{x}+{y}')
            root.update_idletasks()
            # SWP_NOACTIVATE | SWP_SHOWWINDOW; do not call Tk deiconify (can focus).
            setpos(hwnd, W.HWND(-1), x, y, w, h, 0x10 | 0x40)
            shown = True
            status = dict(pid=os.getpid(), hwnd=hwnd, rect=[x,y,x+w,y+h], dpi=dpi,
                          font=family, font_pt=9, mode=effective['mode'], taskbar=r,
                          tray=tray, clock=clock, exstyle=hex(getlong(hwnd,-20)),
                          text=text, python=sys.executable)
            (BASE / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
            previous = state
        # Reassert without activation, in case Explorer recreated/reordered its taskbar.
        setpos(hwnd, W.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        root.after(1000, tick)
    tick()
    try:
        root.mainloop()
    finally:
        close(event)
        close(mutex)

if __name__ == '__main__':
    try:
        run()
    except Exception:
        (BASE / 'error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
