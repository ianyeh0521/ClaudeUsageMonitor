#!/usr/bin/env python3
"""
Claude Usage Monitor
Floating Windows widget showing Claude Code 5h/7d rate limit utilisation.
Requires: Claude Code installed and logged in (credentials at ~/.claude/.credentials.json)
"""
import tkinter as tk
import json
import threading
import time
import urllib.request
import urllib.error
import sys
import ctypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ─── Config ───────────────────────────────────────────────────────────────────
CREDS_PATH    = Path.home() / ".claude" / ".credentials.json"
PROJECTS_PATH = Path.home() / ".claude" / "projects"
POS_PATH      = Path.home() / ".claude" / "claude_monitor_pos.json"
USAGE_URL     = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL     = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID     = "22422756-60c9-4084-8eb7-27705fd5cf9a"
REFRESH_SECS  = 60

# Price per 1 million tokens: (input, output, cache_write, cache_read) USD
PRICING = {
    "claude-opus":   (15.00, 75.00, 18.75, 1.50),
    "claude-sonnet": ( 3.00, 15.00,  3.75, 0.30),
    "claude-haiku":  ( 0.80,  4.00,  1.00, 0.08),
}

WIN_W   = 240
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# ─── Colour palette (Catppuccin Mocha) ────────────────────────────────────────
C = {
    "bg":     "#1e1e2e",
    "title":  "#313244",
    "fg":     "#cdd6f4",
    "dim":    "#6c7086",
    "green":  "#a6e3a1",
    "yellow": "#f9e2af",
    "red":    "#f38ba8",
    "bar_bg": "#45475a",
    "sep":    "#585b70",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def bar_color(pct: float) -> str:
    if pct < 60:
        return C["green"]
    if pct < 80:
        return C["yellow"]
    return C["red"]


def fmt_remaining(iso_str: Optional[str]) -> str:
    if not iso_str:
        return ""
    try:
        target = datetime.fromisoformat(iso_str)
        secs = int((target - datetime.now(timezone.utc)).total_seconds())
        if secs <= 0:
            return "resetting..."
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}d {h}h" if d else f"{h}h {m}m"
    except Exception:
        return "?"


def get_price(model: str) -> Tuple[float, float, float, float]:
    for key, price in PRICING.items():
        if key in model.lower():
            return price
    return PRICING["claude-sonnet"]


def calc_today_cost() -> float:
    today = datetime.now().date()
    total: float = 0.0
    seen: set = set()
    try:
        for jf in PROJECTS_PATH.rglob("*.jsonl"):
            try:
                if datetime.fromtimestamp(jf.stat().st_mtime).date() != today:
                    continue
                with open(jf, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        try:
                            d = json.loads(line)
                            if d.get("type") != "assistant":
                                continue
                            uid = d.get("uuid")
                            if uid in seen:
                                continue
                            seen.add(uid)
                            msg = d.get("message", {})
                            u   = msg.get("usage", {})
                            p   = get_price(msg.get("model", ""))
                            total += (
                                u.get("input_tokens", 0)                * p[0] +
                                u.get("output_tokens", 0)               * p[1] +
                                u.get("cache_creation_input_tokens", 0) * p[2] +
                                u.get("cache_read_input_tokens", 0)     * p[3]
                            ) / 1_000_000
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass
    return total


# ─── Auth ─────────────────────────────────────────────────────────────────────
class Auth:
    """Thread-safe OAuth token manager with automatic refresh."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _load(self) -> dict:
        with open(CREDS_PATH, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, creds: dict) -> None:
        with open(CREDS_PATH, "w", encoding="utf-8") as f:
            json.dump(creds, f, indent=2)

    def get_token(self) -> str:
        with self._lock:
            creds = self._load()
            oauth = creds.get("claudeAiOauth", {})
            if time.time() * 1000 < oauth.get("expiresAt", 0) - 60_000:
                return oauth["accessToken"]
            body = json.dumps({
                "grant_type":    "refresh_token",
                "refresh_token": oauth["refreshToken"],
                "client_id":     CLIENT_ID,
            }).encode()
            req = urllib.request.Request(
                TOKEN_URL, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
            oauth["accessToken"]  = data["access_token"]
            oauth["refreshToken"] = data.get("refresh_token", oauth["refreshToken"])
            oauth["expiresAt"]    = (
                int(time.time() * 1000) + data.get("expires_in", 3600) * 1000
            )
            creds["claudeAiOauth"] = oauth
            self._save(creds)
            return oauth["accessToken"]


def fetch_usage(token: str) -> dict:
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization":  f"Bearer {token}",
            "Content-Type":   "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent":     "claude-usage-monitor/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


# ─── Progress bar widget ──────────────────────────────────────────────────────
class Bar(tk.Canvas):
    H = 11  # bar height in pixels

    def __init__(self, parent: tk.Widget, **kw) -> None:
        super().__init__(
            parent, height=self.H,
            bg=C["bg"], highlightthickness=0, **kw,
        )
        self._pct = 0.0
        self.bind("<Configure>", lambda _: self.draw(self._pct))

    def _pill(self, x1: int, y1: int, x2: int, y2: int, color: str) -> None:
        """Draw a pill/stadium shape (rectangle with fully rounded ends)."""
        r = (y2 - y1) // 2
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="")
        self.create_oval(x1,       y1, x1 + 2*r, y2, fill=color, outline="")
        self.create_oval(x2 - 2*r, y1, x2,       y2, fill=color, outline="")

    def draw(self, pct: float) -> None:
        pct = max(0.0, min(100.0, pct))
        self._pct = pct
        w = self.winfo_width()
        h = self.H
        if w <= 1:
            return
        self.delete("all")
        self._pill(0, 0, w, h, C["bar_bg"])
        fw = int(w * pct / 100)
        if fw >= h:
            self._pill(0, 0, fw, h, bar_color(pct))
        elif fw > 0:
            # Too narrow for pill — draw a left-edge circle
            self.create_oval(0, 0, h, h, fill=bar_color(pct), outline="")


# ─── Main application ─────────────────────────────────────────────────────────
class App:
    def __init__(self) -> None:
        self._topmost     = True
        self._auth        = Auth()
        self._spinning    = False
        self._spin_i      = 0
        self._visible     = True
        self._save_pos_id = None
        self._build()
        if HAS_TRAY:
            self._setup_tray()
        self._refresh()
        threading.Thread(target=self._bg_loop, daemon=True).start()

    # ── Window ────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
        root.configure(bg=C["bg"])
        root.minsize(200, 150)

        # Restore saved position, or default to top-right corner
        if not self._load_pos(root):
            root.update_idletasks()
            sw = root.winfo_screenwidth()
            root.geometry(f"+{sw - WIN_W - 20}+20")

        root.bind("<Configure>", self._on_configure)
        self.root = root

        # ── Title bar ────────────────────────────────────────────────────────
        tbar = tk.Frame(root, bg=C["title"], cursor="fleur")
        tbar.pack(fill="x")
        tbar.bind("<Button-1>",        self._drag_start)
        tbar.bind("<B1-Motion>",       self._drag_move)
        tbar.bind("<Double-Button-1>", self._reset_position)

        title_lbl = tk.Label(
            tbar, text="  ◉  Claude Monitor",
            bg=C["title"], fg=C["fg"],
            font=("Segoe UI", 9, "bold"), pady=6,
        )
        title_lbl.pack(side="left")
        title_lbl.bind("<Button-1>",        self._drag_start)
        title_lbl.bind("<B1-Motion>",       self._drag_move)
        title_lbl.bind("<Double-Button-1>", self._reset_position)

        # Close ✕  (hide to tray when tray is available, otherwise exit)
        btn_x = tk.Label(
            tbar, text=" ✕ ", bg=C["title"], fg=C["dim"],
            font=("Segoe UI", 9), cursor="hand2", pady=6,
        )
        btn_x.pack(side="right")
        close_cmd = self._hide if HAS_TRAY else root.destroy
        btn_x.bind("<Button-1>", lambda _: close_cmd())
        btn_x.bind("<Enter>",    lambda _: btn_x.config(fg=C["red"]))
        btn_x.bind("<Leave>",    lambda _: btn_x.config(fg=C["dim"]))

        # Pin 📌
        self.btn_pin = tk.Label(
            tbar, text=" 📌 ", bg=C["title"], fg=C["fg"],
            font=("Segoe UI", 9), cursor="hand2", pady=6,
        )
        self.btn_pin.pack(side="right")
        self.btn_pin.bind("<Button-1>", self._toggle_pin)
        self.btn_pin.bind("<Enter>",    lambda _: self.btn_pin.config(bg=C["bar_bg"]))
        self.btn_pin.bind("<Leave>",    lambda _: self.btn_pin.config(bg=C["title"]))

        # ── Body ─────────────────────────────────────────────────────────────
        body = tk.Frame(root, bg=C["bg"], padx=12, pady=8)
        body.pack(fill="both", expand=True)

        # 5h row
        tk.Label(body, text="5h Session Limit",
                 bg=C["bg"], fg=C["fg"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")

        row5 = tk.Frame(body, bg=C["bg"])
        row5.pack(fill="x", pady=(3, 0))
        self.pct5h = tk.Label(row5, text="  0%", width=5,
                              bg=C["bg"], fg=C["dim"],
                              font=("Segoe UI", 8, "bold"), anchor="e")
        self.pct5h.pack(side="right")
        self.bar5h = Bar(row5)
        self.bar5h.pack(side="left", fill="x", expand=True, pady=1)

        self.rst5h = tk.Label(body, text="",
                              bg=C["bg"], fg=C["dim"],
                              font=("Segoe UI", 7))
        self.rst5h.pack(anchor="w", pady=(1, 4))

        tk.Frame(body, bg=C["sep"], height=1).pack(fill="x")

        # 7d row
        tk.Label(body, text="7d Weekly Limit",
                 bg=C["bg"], fg=C["fg"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(6, 0))

        row7 = tk.Frame(body, bg=C["bg"])
        row7.pack(fill="x", pady=(3, 0))
        self.pct7d = tk.Label(row7, text="  0%", width=5,
                              bg=C["bg"], fg=C["dim"],
                              font=("Segoe UI", 8, "bold"), anchor="e")
        self.pct7d.pack(side="right")
        self.bar7d = Bar(row7)
        self.bar7d.pack(side="left", fill="x", expand=True, pady=1)

        self.rst7d = tk.Label(body, text="",
                              bg=C["bg"], fg=C["dim"],
                              font=("Segoe UI", 7))
        self.rst7d.pack(anchor="w", pady=(1, 4))

        tk.Frame(body, bg=C["sep"], height=1).pack(fill="x")

        # Bottom row: cost + last-updated
        bot = tk.Frame(body, bg=C["bg"], pady=5)
        bot.pack(fill="x")

        self.lbl_cost = tk.Label(bot, text="Today:  --",
                                 bg=C["bg"], fg=C["fg"],
                                 font=("Segoe UI", 8))
        self.lbl_cost.pack(side="left")

        self.lbl_time = tk.Label(bot, text="",
                                 bg=C["bg"], fg=C["dim"],
                                 font=("Segoe UI", 7), cursor="hand2")
        self.lbl_time.pack(side="right")
        self.lbl_time.bind("<Button-1>", lambda _: self._refresh())
        self.lbl_time.bind("<Enter>",    lambda _: self.lbl_time.config(fg=C["fg"]))
        self.lbl_time.bind("<Leave>",    lambda _: self.lbl_time.config(fg=C["dim"]))

        # Error label (hidden until an error occurs)
        self.lbl_err = tk.Label(body, text="",
                                bg=C["bg"], fg=C["red"],
                                font=("Segoe UI", 7),
                                wraplength=WIN_W - 24, justify="left", anchor="w")

        # ── Resize handles (edges + corners, placed last to stay on top) ────
        G = 6
        for cursor, place_kw, direction in [
            ("size_we",    {"x": 0,    "y": 0, "width": G,    "relheight": 1},                  "w"),
            ("size_we",    {"relx": 1, "y": 0, "width": G,    "relheight": 1, "anchor": "ne"},  "e"),
            ("size_ns",    {"x": 0,    "rely": 1, "relwidth": 1, "height": G, "anchor": "sw"},  "s"),
            ("size_ne_sw", {"x": 0,    "rely": 1, "width": G*2, "height": G*2, "anchor": "sw"}, "sw"),
            ("size_nw_se", {"relx": 1, "rely": 1, "width": G*2, "height": G*2, "anchor": "se"}, "se"),
        ]:
            f = tk.Frame(root, bg=C["bg"], cursor=cursor)
            f.place(**place_kw)
            f.bind("<Button-1>",  lambda e, d=direction: self._resize_start(e, d))
            f.bind("<B1-Motion>", lambda e, d=direction: self._resize_move(e, d))

    # ── Position memory ───────────────────────────────────────────────────────
    def _load_pos(self, root: tk.Tk) -> bool:
        try:
            pos = json.loads(POS_PATH.read_text())
            root.geometry(f"{pos['w']}x{pos['h']}+{pos['x']}+{pos['y']}")
            return True
        except Exception:
            return False

    def _save_pos(self) -> None:
        try:
            pos = {
                "x": self.root.winfo_x(), "y": self.root.winfo_y(),
                "w": self.root.winfo_width(), "h": self.root.winfo_height(),
            }
            POS_PATH.write_text(json.dumps(pos))
        except Exception:
            pass

    def _on_configure(self, _) -> None:
        if not self._visible:
            return
        if self._save_pos_id:
            self.root.after_cancel(self._save_pos_id)
        self._save_pos_id = self.root.after(500, self._save_pos)

    # ── System tray ───────────────────────────────────────────────────────────
    def _setup_tray(self) -> None:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.ellipse([2, 2, 62, 62], fill="#a6e3a1")
        d.ellipse([14, 14, 50, 50], fill="#1e1e2e")

        menu = pystray.Menu(
            pystray.MenuItem("顯示", self._tray_show, default=True),
            pystray.MenuItem("結束", self._tray_exit),
        )
        self._tray = pystray.Icon("ClaudeMonitor", img, "Claude Monitor", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _hide(self) -> None:
        self._visible = False
        self.root.withdraw()

    def _tray_show(self, icon=None, item=None) -> None:
        self._visible = True
        self.root.after(0, self.root.deiconify)

    def _tray_exit(self, icon=None, item=None) -> None:
        self._tray.stop()
        self.root.after(0, self.root.destroy)

    # ── Spinner ───────────────────────────────────────────────────────────────
    def _spin_start(self) -> None:
        self._spinning = True
        self._spin_i   = 0
        self._spin_step()

    def _spin_step(self) -> None:
        if not self._spinning:
            return
        self.lbl_time.config(text=SPINNER[self._spin_i % len(SPINNER)], fg=C["dim"])
        self._spin_i += 1
        self.root.after(100, self._spin_step)

    def _spin_stop(self) -> None:
        self._spinning = False

    # ── Drag & position ───────────────────────────────────────────────────────
    def _drag_start(self, e: tk.Event) -> None:
        self._drag_off_x = e.x_root - self.root.winfo_x()
        self._drag_off_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e: tk.Event) -> None:
        x = e.x_root - self._drag_off_x
        y = e.y_root - self._drag_off_y
        self.root.geometry(f"+{x}+{y}")

    def _reset_position(self, _=None) -> None:
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{sw - WIN_W - 20}+20")

    # ── Resize ────────────────────────────────────────────────────────────────
    def _resize_start(self, e: tk.Event, direction: str) -> None:
        self._res_x0  = e.x_root
        self._res_y0  = e.y_root
        self._res_w0  = self.root.winfo_width()
        self._res_h0  = self.root.winfo_height()
        self._res_wx0 = self.root.winfo_x()
        self._res_wy0 = self.root.winfo_y()

    def _resize_move(self, e: tk.Event, direction: str) -> None:
        dx = e.x_root - self._res_x0
        dy = e.y_root - self._res_y0
        w  = self._res_w0
        h  = self._res_h0
        wx = self._res_wx0
        wy = self._res_wy0

        if "e" in direction:
            w = max(200, self._res_w0 + dx)
        if "w" in direction:
            w = max(200, self._res_w0 - dx)
            wx = self._res_wx0 + self._res_w0 - w
        if "s" in direction:
            h = max(150, self._res_h0 + dy)

        self.root.geometry(f"{w}x{h}+{wx}+{wy}")

    # ── Pin toggle ────────────────────────────────────────────────────────────
    def _toggle_pin(self, _=None) -> None:
        self._topmost = not self._topmost
        self.root.attributes("-topmost", self._topmost)
        self.btn_pin.config(fg=C["fg"] if self._topmost else C["dim"])

    # ── UI updates ────────────────────────────────────────────────────────────
    def _set_row(
        self,
        bar: Bar,
        lbl_pct: tk.Label,
        lbl_rst: tk.Label,
        data: Optional[dict],
    ) -> None:
        pct = data.get("utilization", 0) if data else 0
        rst = data.get("resets_at")      if data else None
        bar.draw(pct)
        lbl_pct.config(text=f"{pct:.0f}%", fg=bar_color(pct))
        if pct > 0:
            remaining = fmt_remaining(rst)
            lbl_rst.config(
                text=f"resets in {remaining}" if remaining else "",
                fg=C["dim"],
            )
        else:
            lbl_rst.config(text="")

    def _update_ui(
        self, five: Optional[dict], seven: Optional[dict], cost: float
    ) -> None:
        self._spin_stop()
        self._set_row(self.bar5h, self.pct5h, self.rst5h, five)
        self._set_row(self.bar7d, self.pct7d, self.rst7d, seven)
        self.lbl_cost.config(text=f"Today:  ${cost:.3f}")
        self.lbl_time.config(
            text="↺ " + datetime.now().strftime("%H:%M:%S"),
            fg=C["dim"],
        )
        self.lbl_err.pack_forget()

    def _show_error(self, msg: str) -> None:
        self._spin_stop()
        self.lbl_time.config(text="↺ --:--:--", fg=C["dim"])
        self.lbl_err.config(text=f"⚠  {msg}")
        self.lbl_err.pack(fill="x", pady=(2, 0))

    # ── Refresh logic ─────────────────────────────────────────────────────────
    def _do_fetch(self) -> None:
        """Run one fetch cycle and schedule a UI update. Raises on any error."""
        token = self._auth.get_token()
        data  = fetch_usage(token)
        cost  = calc_today_cost()
        self.root.after(
            0, self._update_ui,
            data.get("five_hour"),
            data.get("seven_day"),
            cost,
        )

    def _refresh(self) -> None:
        """Manual refresh triggered by the user — runs in a short-lived thread."""
        self.root.after(0, self._spin_start)

        def task() -> None:
            try:
                self._do_fetch()
            except urllib.error.HTTPError as ex:
                msg = "Rate limited (429)" if ex.code == 429 else f"HTTP {ex.code}"
                self.root.after(0, self._show_error, msg)
            except FileNotFoundError:
                self.root.after(0, self._show_error, "Login to Claude Code first")
            except Exception as ex:
                self.root.after(0, self._show_error, str(ex))

        threading.Thread(target=task, daemon=True).start()

    def _bg_loop(self) -> None:
        """Periodic background refresh with exponential backoff on 429."""
        delay = REFRESH_SECS
        while True:
            time.sleep(delay)
            self.root.after(0, self._spin_start)
            try:
                self._do_fetch()
                delay = REFRESH_SECS          # success → reset to normal interval
            except urllib.error.HTTPError as ex:
                if ex.code == 429:
                    delay = min(delay * 2, 3600)  # double up to 1 hour
                    self.root.after(
                        0, self._show_error,
                        f"Rate limited — retry in {delay}s",
                    )
                else:
                    delay = REFRESH_SECS
                    self.root.after(0, self._show_error, f"HTTP {ex.code}")
            except FileNotFoundError:
                delay = REFRESH_SECS
                self.root.after(0, self._show_error, "Login to Claude Code first")
            except Exception as ex:
                delay = REFRESH_SECS
                self.root.after(0, self._show_error, str(ex))

    def run(self) -> None:
        self.root.mainloop()


# ─── Single-instance guard ────────────────────────────────────────────────────
def ensure_single_instance() -> None:
    """Exit immediately if another instance is already running (Windows only)."""
    if sys.platform != "win32":
        return
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "ClaudeMonitor_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        sys.exit(0)


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_single_instance()
    App().run()
