"""
CampusHunter — 第二课堂自动抢课助手
A Flet-based desktop application to monitor and auto-register for university activities.
"""

import flet as ft
import requests
import urllib3
import threading
import time
import json
import os
import sys
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────── Constants ────────────────────────────

BASE_URL = "https://qcbldekt.bit.edu.cn"

# ── Token loading from external file ──

def _get_app_dir() -> str:
    """Return the directory where the executable (or script) lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

TOKEN_FILE = os.path.join(_get_app_dir(), "token.txt")
TOKEN_PLACEHOLDER = "请在此粘贴你的Bearer Token"

def load_token() -> str:
    """Read the Bearer token from token.txt. Create a placeholder file if missing."""
    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(TOKEN_PLACEHOLDER)
        return ""
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        token = f.read().strip()
    if not token or token == TOKEN_PLACEHOLDER:
        return ""
    return token

_TOKEN = load_token()

HEADERS = {
    "Host": "qcbldekt.bit.edu.cn",
    "Connection": "keep-alive",
    "Authorization": _TOKEN if _TOKEN else "",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
        "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
        "MiniProgramEnv/Windows WindowsWechat/WMPF "
        "WindowsWechat(0x63090b13) XWEB/11275"
    ),
    "Content-Type": "application/json",
    "Referer": "https://servicewechat.com/wx2149021480f24a19/270/page-frame.html",
}

DEFAULT_TEMPLATE_ID = "2GNFjVv2S7xYnoWeIxGsJGP1Fu2zSs28R6mZI7Fc2kU"

# Time format used by the real API (no seconds)
API_TIME_FMT = "%Y-%m-%d %H:%M"

# ──────────────────────────── API Layer ────────────────────────────


def api_get(endpoint: str, params: dict | None = None, debug_label: str = "") -> dict | None:
    """Send a GET request and return parsed JSON, or None on failure."""
    try:
        resp = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=HEADERS,
            params=params,
            timeout=10,
            verify=False,
        )
        if debug_label:
            print(f"=== RAW {debug_label} RESPONSE ===", resp.text[:2000])
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        return {"_error": f"网络请求失败: {exc}"}
    except json.JSONDecodeError:
        return {"_error": "返回数据解析失败（非JSON）"}


def api_post(endpoint: str, payload: dict) -> dict | None:
    """Send a POST request and return parsed JSON, or None on failure."""
    try:
        resp = requests.post(
            f"{BASE_URL}{endpoint}",
            headers=HEADERS,
            json=payload,
            timeout=10,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        return {"_error": f"网络请求失败: {exc}"}
    except json.JSONDecodeError:
        return {"_error": "返回数据解析失败（非JSON）"}


def fetch_user_info() -> dict:
    return api_get("/api/user/info") or {}


def fetch_scores() -> dict:
    result = api_get("/api/transcript/score", debug_label="SCORE") or {}
    return result


def fetch_courses(page: int = 1, limit: int = 20) -> dict:
    result = api_get("/api/course/list", {"page": page, "limit": limit}, debug_label="COURSE") or {}
    return result


def apply_course(course_id: int) -> dict:
    payload = {"course_id": course_id, "template_id": DEFAULT_TEMPLATE_ID}
    return api_post("/api/course/apply", payload) or {}


def parse_api_time(time_str: str) -> datetime | None:
    """Parse an API time string like '2026-03-02 14:35' into a datetime."""
    if not time_str:
        return None
    for fmt in (API_TIME_FMT, "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(time_str)
    except ValueError:
        return None


# ──────────────────────────── Sniper Engine ────────────────────────


class SniperEngine:
    """Background thread that watches courses and fires apply at the right time."""

    def __init__(self, log_callback):
        self._watched: dict[int, dict] = {}  # course_id -> course dict
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._log = log_callback  # callable(str)

    def add(self, course: dict):
        cid = course.get("id")
        with self._lock:
            self._watched[cid] = course
        self._log(f"[监控] 已添加活动 {cid}: {course.get('title', '未知')}")

    def remove(self, course_id: int):
        with self._lock:
            if course_id in self._watched:
                del self._watched[course_id]
        self._log(f"[监控] 已移除活动 {course_id}")

    def is_watched(self, course_id: int) -> bool:
        with self._lock:
            return course_id in self._watched

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            now = datetime.now()
            to_fire: list[dict] = []

            with self._lock:
                for cid, course in list(self._watched.items()):
                    sign_start = course.get("sign_start_time", "")
                    start_dt = parse_api_time(sign_start)
                    if start_dt is None or now >= start_dt:
                        to_fire.append(course)

            for course in to_fire:
                cid = course.get("id")
                self._log(f"[抢课] 正在尝试报名活动 {cid}...")
                result = apply_course(cid)
                if result and "_error" not in result:
                    msg = result.get("message") or result.get("msg") or "请求已发送"
                    code = result.get("code", "")
                    if code == 200 or code == 0 or "成功" in str(msg):
                        self._log(f"[成功] 抢课成功! 活动 {cid}: {msg}")
                    else:
                        self._log(f"[结果] 活动 {cid}: code={code}, {msg}")
                    with self._lock:
                        self._watched.pop(cid, None)
                elif result and "_error" in result:
                    err = result["_error"]
                    if "Token" in err or "401" in err or "Unauthenticated" in err:
                        self._log(f"[失败] Token已过期或无效: {err}")
                    else:
                        self._log(f"[失败] 活动 {cid}: {err}")
                else:
                    self._log(f"[失败] 活动 {cid}: 未收到响应")

            time.sleep(0.5)


# ──────────────────────────── Flet Application ─────────────────────


def main(page: ft.Page):
    # ── Monokai Pro Color Palette ──
    BG_DEEP = "#2D2A2E"
    BG_CARD = "#403E41"
    BORDER = "#525053"
    TEXT_PRIMARY = "#FCFCFA"
    TEXT_SECONDARY = "#939293"
    TEXT_MUTED = "#727072"
    ACCENT_GREEN = "#A9DC76"
    ACCENT_ROSE = "#FF6188"
    ACCENT_AMBER = "#FFD866"
    ACCENT_BLUE = "#78DCE8"
    ACCENT_PURPLE = "#AB9DF2"
    PILL_BG = "#525053"
    PILL_TEXT = "#FCFCFA"

    # ── Page settings ──
    page.title = "第二课堂自动抢课助手"
    page.window.width = 1120
    page.window.height = 740
    page.padding = 0
    page.bgcolor = BG_DEEP
    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(
        color_scheme_seed=ACCENT_AMBER,
        font_family="Microsoft YaHei",
    )
    page.fonts = {
        "Microsoft YaHei": "https://db.onlinewebfonts.com/t/48eec17e5e1a927ee91e24eb89a09dff.ttf",
    }

    # ── Token check ──
    if not _TOKEN:
        token_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Token 未配置", size=18, weight=ft.FontWeight.BOLD, color=ACCENT_ROSE),
            content=ft.Column(
                [
                    ft.Text(
                        "请打开与本程序同目录下的 token.txt 文件,\n"
                        "粘贴你的 Bearer Token (包含 'Bearer ' 前缀),\n"
                        "然后重新启动本程序。",
                        size=14, color=TEXT_SECONDARY,
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        f"文件位置: {TOKEN_FILE}",
                        size=12, color=TEXT_MUTED, selectable=True,
                    ),
                ],
                tight=True,
            ),
            actions=[
                ft.TextButton("知道了", on_click=lambda e: page.window.close()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(token_dialog)
        token_dialog.open = True
        page.update()
        return  # Stop here — no point making API calls without a token

    # ── State ──
    courses_data: list[dict] = []
    log_lines: list[str] = []

    # ── Log callback ──
    def append_log(msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        log_lines.append(f"[{ts}] {msg}")
        if len(log_lines) > 200:
            log_lines.pop(0)
        log_field.value = "\n".join(log_lines)
        try:
            page.update()
        except Exception:
            pass

    sniper = SniperEngine(log_callback=append_log)
    sniper.start()

    # ── UI helper factories ──
    def _label(text, size=13, color=TEXT_SECONDARY, weight=None):
        return ft.Text(text, size=size, color=color, weight=weight)

    def _value(text, size=14, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600):
        return ft.Text(str(text), size=size, color=color, weight=weight)

    def _pill(text, icon=None, icon_color=PILL_TEXT, bg=PILL_BG, text_color=PILL_TEXT, size=11):
        """Modern pill-style tag."""
        row_items = []
        if icon:
            row_items.append(ft.Icon(icon, size=12, color=icon_color))
        row_items.append(ft.Text(text, size=size, color=text_color, weight=ft.FontWeight.W_500))
        return ft.Container(
            content=ft.Row(row_items, spacing=4, tight=True),
            bgcolor=bg,
            border_radius=16,
            padding=ft.Padding(left=10, top=4, right=10, bottom=4),
        )

    def _section_header(title, icon, color=ACCENT_BLUE):
        return ft.Row([
            ft.Icon(icon, color=color, size=16),
            _label(title, size=15, color=color, weight=ft.FontWeight.W_600),
        ], spacing=6)

    # ── Snackbar helper ──
    def show_snack(msg: str, error=False):
        page.snack_bar = ft.SnackBar(
            ft.Text(msg, color=TEXT_PRIMARY),
            bgcolor=ACCENT_ROSE if error else ACCENT_GREEN,
            duration=3000,
        )
        page.snack_bar.open = True
        page.update()

    # ═══════════════════  LEFT PANEL — User Info & Score  ═══════════════════

    avatar_icon = ft.Icon(ft.Icons.ACCOUNT_CIRCLE, size=52, color=ACCENT_BLUE)
    username_text = _value("加载中...", size=17, weight=ft.FontWeight.BOLD)
    user_detail_col = ft.Column(spacing=4)

    user_card = ft.Container(
        content=ft.Column(
            [
                _section_header("用户信息", ft.Icons.PERSON, ACCENT_BLUE),
                ft.Divider(height=1, color=BORDER),
                ft.Row(
                    [avatar_icon, ft.Column([username_text], spacing=2)],
                    spacing=12,
                    alignment=ft.MainAxisAlignment.START,
                ),
                user_detail_col,
            ],
            spacing=10,
        ),
        bgcolor=BG_CARD,
        border_radius=12,
        padding=18,
        border=ft.border.all(1, BORDER),
    )

    # Score card — total + compact 2-column breakdown
    score_total_text = ft.Text(
        "累计基础分: --", size=32, weight=ft.FontWeight.BOLD, color=ACCENT_AMBER,
    )
    score_breakdown_row = ft.Row(wrap=True, spacing=4, run_spacing=4)

    score_card = ft.Container(
        content=ft.Column(
            [
                _section_header("成绩单", ft.Icons.SCHOOL_OUTLINED, ACCENT_GREEN),
                ft.Divider(height=1, color=BORDER),
                ft.Container(
                    content=score_total_text,
                    alignment=ft.alignment.center,
                    padding=ft.Padding(left=0, top=6, right=0, bottom=2),
                ),
                score_breakdown_row,
            ],
            spacing=8,
        ),
        bgcolor=BG_CARD,
        border_radius=12,
        padding=18,
        border=ft.border.all(1, BORDER),
    )

    status_indicator = ft.Container(
        content=ft.Row(
            [
                ft.Container(width=8, height=8, border_radius=4, bgcolor=ACCENT_GREEN),
                _label("抢课引擎运行中", size=12, color=ACCENT_GREEN),
            ],
            spacing=8,
        ),
        bgcolor=BG_DEEP,
        border_radius=8,
        padding=ft.Padding(left=12, top=8, right=12, bottom=8),
        border=ft.border.all(1, ACCENT_GREEN + "40"),
    )

    left_panel = ft.Container(
        content=ft.Column(
            [user_card, score_card, ft.Container(expand=True), status_indicator],
            spacing=14,
            expand=True,
        ),
        width=340,
        padding=ft.Padding(left=16, top=16, right=8, bottom=16),
        bgcolor=BG_DEEP,
    )

    # ═══════════════════  RIGHT PANEL — Activity List  ═══════════════════

    activity_list = ft.ListView(spacing=10, expand=True, auto_scroll=False)

    refresh_btn = ft.ElevatedButton(
        text="刷新列表",
        icon=ft.Icons.REFRESH,
        bgcolor=ACCENT_GREEN,
        color="#ffffff",
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        height=38,
    )

    page_label = _value("第 1 页", size=13, color=TEXT_MUTED)
    prev_btn = ft.IconButton(ft.Icons.CHEVRON_LEFT, icon_color=TEXT_MUTED, icon_size=20, disabled=True)
    next_btn = ft.IconButton(ft.Icons.CHEVRON_RIGHT, icon_color=TEXT_MUTED, icon_size=20)
    current_page = [1]

    log_field = ft.TextField(
        label="运行日志",
        multiline=True,
        min_lines=5,
        max_lines=5,
        read_only=True,
        value="",
        text_size=12,
        label_style=ft.TextStyle(color=ACCENT_BLUE, size=13),
        border_color=BORDER,
        focused_border_color=ACCENT_BLUE,
        color=TEXT_SECONDARY,
        bgcolor=BG_DEEP,
        border_radius=10,
    )

    # ── Build a course card ──
    def build_course_card(course: dict) -> ft.Container:
        cid = course.get("id", 0)
        title = course.get("title", "未知活动")
        time_place = course.get("time_place", "时间地点待定")
        score = course.get("score", "—")
        sign_start = course.get("sign_start_time", "")
        sign_end = course.get("sign_end_time", "")
        sign_status = course.get("sign_status_label", "")
        max_slots = course.get("max", 0)
        apply_count = course.get("course_apply_count", 0)

        transcript_idx = course.get("transcript_index") or {}
        dimension = transcript_idx.get("transcript_name", "未知维度")

        try:
            surplus = int(max_slots) - int(apply_count)
        except (ValueError, TypeError):
            surplus = 0
        if surplus < 0:
            surplus = 0

        is_full = surplus <= 0

        # Toggle
        toggle = ft.Switch(
            value=sniper.is_watched(cid),
            active_color=ACCENT_AMBER,
            active_track_color=ACCENT_AMBER + "44",
            inactive_thumb_color=TEXT_MUTED,
            inactive_track_color=BORDER,
            disabled=is_full,
        )

        def on_toggle(e):
            if toggle.value:
                sniper.add(course)
            else:
                sniper.remove(cid)

        toggle.on_change = on_toggle

        # Status badge
        if sign_status == "进行中":
            status_badge = ft.Container(
                content=ft.Text(sign_status, size=11, color="#2D2A2E", weight=ft.FontWeight.W_600),
                bgcolor=ACCENT_GREEN, border_radius=12,
                padding=ft.Padding(left=10, top=3, right=10, bottom=3),
            )
        elif sign_status == "名额已满":
            status_badge = ft.Container(
                content=ft.Text(sign_status, size=11, color="#ffffff", weight=ft.FontWeight.W_600),
                bgcolor=ACCENT_ROSE, border_radius=12,
                padding=ft.Padding(left=10, top=3, right=10, bottom=3),
            )
        elif sign_status:
            status_badge = ft.Container(
                content=ft.Text(sign_status, size=11, color=TEXT_SECONDARY, weight=ft.FontWeight.W_500),
                bgcolor=PILL_BG, border_radius=12,
                padding=ft.Padding(left=10, top=3, right=10, bottom=3),
            )
        else:
            status_badge = ft.Container()

        # Surplus display
        if is_full:
            surplus_text, surplus_color = "名额已满", ACCENT_ROSE
        elif surplus <= 5:
            surplus_text, surplus_color = f"剩余 {surplus} / {max_slots}", ACCENT_AMBER
        else:
            surplus_text, surplus_color = f"剩余 {surplus} / {max_slots}", ACCENT_GREEN

        # Registration time
        reg_time = ""
        if sign_start and sign_end:
            reg_time = f"{sign_start} ~ {sign_end}"
        elif sign_start:
            reg_time = sign_start

        card = ft.Container(
            content=ft.Column(
                [
                    # Title + Status
                    ft.Row([
                        ft.Container(
                            content=ft.Text(
                                title, size=15, weight=ft.FontWeight.W_600,
                                color=TEXT_PRIMARY, max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            expand=True,
                        ),
                        status_badge,
                    ]),
                    # Pill tags
                    ft.Row([
                        _pill(dimension, icon=ft.Icons.CATEGORY_OUTLINED,
                              icon_color=ACCENT_BLUE, bg=ACCENT_BLUE + "22",
                              text_color=ACCENT_BLUE),
                        _pill(f"可获 {score} 分", icon=ft.Icons.STAR_OUTLINE,
                              icon_color=ACCENT_AMBER, bg=ACCENT_AMBER + "22",
                              text_color=ACCENT_AMBER),
                    ], spacing=8),
                    # Time & Place
                    ft.Row([
                        ft.Icon(ft.Icons.SCHEDULE, size=13, color=TEXT_MUTED),
                        ft.Text(time_place, size=12, color=TEXT_SECONDARY,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    ], spacing=6),
                    # Registration time
                    ft.Row([
                        ft.Icon(ft.Icons.DATE_RANGE, size=13, color=TEXT_MUTED),
                        _label(f"报名: {reg_time}" if reg_time else "报名时间待定", size=12),
                    ], spacing=6) if reg_time else ft.Container(),
                    # Surplus + Toggle
                    ft.Container(
                        content=ft.Row([
                            ft.Row([
                                ft.Icon(ft.Icons.EVENT_SEAT, size=14, color=surplus_color),
                                ft.Text(surplus_text, size=13, color=surplus_color, weight=ft.FontWeight.W_600),
                            ], spacing=5),
                            ft.Row([
                                _label("自动抢", size=12, color=ACCENT_AMBER if not is_full else TEXT_MUTED),
                                toggle,
                            ], spacing=4),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=ft.Padding(left=0, top=4, right=0, bottom=0),
                    ),
                ],
                spacing=7,
            ),
            bgcolor=BG_CARD,
            border_radius=12,
            padding=ft.Padding(left=16, top=14, right=16, bottom=14),
            border=ft.border.all(1, BORDER),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_IN_OUT),
            on_hover=lambda e: _card_hover(e, card),
        )
        return card

    def _card_hover(e, card):
        card.border = ft.border.all(1, ACCENT_BLUE if e.data == "true" else BORDER)
        card.update()

    # ── Refresh logic ──
    def do_refresh(pg: int = 1):
        append_log("正在刷新活动列表...")
        refresh_btn.disabled = True
        try:
            page.update()
        except Exception:
            pass

        result = fetch_courses(page=pg, limit=20)
        refresh_btn.disabled = False

        if result and "_error" in result:
            append_log(f"刷新失败: {result['_error']}")
            show_snack(result["_error"], error=True)
            page.update()
            return

        data_obj = result.get("data", {})
        items = data_obj.get("items", []) if isinstance(data_obj, dict) else (data_obj if isinstance(data_obj, list) else [])

        filtered = [item for item in items if item.get("sign_status_label", "") != "已结束"]

        courses_data.clear()
        courses_data.extend(filtered)

        activity_list.controls.clear()
        if not filtered:
            activity_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.INBOX_OUTLINED, size=48, color=TEXT_MUTED),
                            _label("暂无可报名活动", size=14, color=TEXT_MUTED),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    alignment=ft.alignment.center,
                    padding=40,
                )
            )
        else:
            for c in filtered:
                activity_list.controls.append(build_course_card(c))

        current_page[0] = pg
        page_label.value = f"第 {pg} 页"
        prev_btn.disabled = pg <= 1
        append_log(f"刷新完成, 共 {len(items)} 条, 显示 {len(filtered)} 条 (第{pg}页)")
        page.update()

    def on_refresh(e):
        threading.Thread(target=do_refresh, args=(1,), daemon=True).start()

    def on_prev(e):
        if current_page[0] > 1:
            threading.Thread(target=do_refresh, args=(current_page[0] - 1,), daemon=True).start()

    def on_next(e):
        threading.Thread(target=do_refresh, args=(current_page[0] + 1,), daemon=True).start()

    refresh_btn.on_click = on_refresh
    prev_btn.on_click = on_prev
    next_btn.on_click = on_next

    header_row = ft.Row(
        [
            ft.Row([
                ft.Icon(ft.Icons.LIST_ALT, color=ACCENT_BLUE, size=18),
                _label("活动列表", size=15, color=ACCENT_BLUE, weight=ft.FontWeight.W_600),
            ], spacing=6),
            ft.Row([prev_btn, page_label, next_btn, refresh_btn], spacing=4),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )

    right_panel = ft.Container(
        content=ft.Column(
            [header_row, ft.Divider(height=1, color=BORDER), activity_list, log_field],
            spacing=12,
            expand=True,
        ),
        expand=True,
        padding=ft.Padding(left=8, top=16, right=16, bottom=16),
        bgcolor=BG_DEEP,
    )

    # ═══════════════════  LAYOUT  ═══════════════════

    divider_vert = ft.Container(width=1, bgcolor=BORDER, height=float("inf"))

    page.add(
        ft.Row([left_panel, divider_vert, right_panel], expand=True, spacing=0)
    )

    # ── Load user info in background ──
    def load_user_info():
        append_log("正在获取用户信息...")
        info = fetch_user_info()
        if info and "_error" in info:
            username_text.value = "获取失败"
            append_log(f"获取用户信息失败: {info['_error']}")
            page.update()
            return

        data = info.get("data") or info.get("result") or info
        if isinstance(data, dict):
            name = data.get("name") or data.get("username") or data.get("realname") or "未知用户"
            username_text.value = name
            detail_map = {
                "学号": data.get("student_id") or data.get("number") or data.get("sn"),
                "学院": data.get("college") or data.get("department"),
                "班级": data.get("class_name") or data.get("class"),
                "手机": data.get("phone") or data.get("mobile"),
            }
            user_detail_col.controls.clear()
            for k, v in detail_map.items():
                if v:
                    user_detail_col.controls.append(
                        ft.Row(
                            [_label(f"{k}:", size=12, color=TEXT_MUTED), _value(str(v), size=12)],
                            spacing=8,
                        )
                    )
            append_log(f"用户信息加载成功: {name}")
        else:
            username_text.value = "未知用户"
            append_log("用户信息格式异常")
        page.update()

    # ── Load scores — total + compact 2-column breakdown ──
    def load_scores():
        append_log("正在获取成绩单...")
        result = fetch_scores()
        score_breakdown_row.controls.clear()

        if result and "_error" in result:
            score_total_text.value = "累计基础分: --"
            score_total_text.color = ACCENT_ROSE
            append_log(f"获取成绩单失败: {result['_error']}")
            page.update()
            return

        try:
            data_obj = result.get("data")
            leader_scores = []
            if isinstance(data_obj, dict):
                leader_scores = data_obj.get("leaderScore", [])

            if not leader_scores:
                score_total_text.value = "累计基础分: --"
                score_total_text.color = ACCENT_ROSE
                append_log("成绩单为空或未找到 leaderScore")
            else:
                total_score = sum(float(item.get("score", 0)) for item in leader_scores)
                score_total_text.value = f"累计基础分: {total_score:.0f}"
                score_total_text.color = ACCENT_AMBER

                # Compact 2-column breakdown
                for item in leader_scores:
                    name = item.get("name", "未知")
                    val = float(item.get("score", 0))
                    dot_color = ACCENT_GREEN if val >= 15 else (ACCENT_AMBER if val >= 5 else ACCENT_ROSE)
                    score_breakdown_row.controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Container(width=6, height=6, border_radius=3, bgcolor=dot_color),
                                    ft.Text(f"{name}:", size=12, color=TEXT_SECONDARY),
                                    ft.Text(f"{val:.0f}", size=12, color=TEXT_PRIMARY, weight=ft.FontWeight.W_600),
                                ],
                                spacing=5,
                                tight=True,
                            ),
                            width=145,
                            padding=ft.Padding(left=4, top=3, right=4, bottom=3),
                        )
                    )

                append_log(f"成绩单加载成功, 累计基础分: {total_score:.0f}")

        except Exception as exc:
            score_total_text.value = "累计基础分: --"
            score_total_text.color = ACCENT_ROSE
            raw_str = json.dumps(result, ensure_ascii=False, default=str)
            append_log(f"[错误] 分数解析异常: {exc}")
            append_log(f"[原始数据] {raw_str[:500]}")

        page.update()

    # Fire off initial loads
    threading.Thread(target=load_user_info, daemon=True).start()
    threading.Thread(target=load_scores, daemon=True).start()
    threading.Thread(target=do_refresh, args=(1,), daemon=True).start()

    append_log("第二课堂自动抢课助手已启动, 欢迎使用!")


# ──────────────────────────── Entry Point ──────────────────────────

if __name__ == "__main__":
    ft.app(target=main)
