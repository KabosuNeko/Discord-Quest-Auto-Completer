#!/usr/bin/env python3
"""
Discord Quest Auto-Completer - KabosuNeko

Usage:
  python direct_run.py                         # Interactive — enter tokens in terminal
  python direct_run.py --file tokens.txt       # Run tokens from file (one token per line)
  python direct_run.py --poll 90               # Set polling interval (seconds)
  python direct_run.py --once                  # Run once and exit (no loop)
"""

import sys
import os
import time
import random
import re
import base64
import json
import signal
import argparse
import threading
from datetime import datetime
from typing import Optional

try:
    import requests
except ImportError:
    print("󰅖 Missing 'requests' library. Run: pip install requests")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

API_BASE = "https://discord.com/api/v9"
REQUEST_TIMEOUT = 30
HEARTBEAT_INTERVAL = 20
MAX_FAILURES = 10
MAX_STALLS = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "discord/1.0.9175 Chrome/128.0.6613.186 "
    "Electron/32.2.7 Safari/537.36"
)
SUPPORTED_TASKS = [
    "WATCH_VIDEO",
    "PLAY_ON_DESKTOP",
    "STREAM_ON_DESKTOP",
    "PLAY_ACTIVITY",
    "WATCH_VIDEO_ON_MOBILE",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  COLORS & UI
# ═══════════════════════════════════════════════════════════════════════════════

class C:
    """ANSI color codes for terminal output."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"


def log(msg: str, level: str = "info", username: str = "system"):
    ts = datetime.now().strftime("%H:%M:%S")
    level_styles = {
        "info":     f"{C.BLUE}INFO{C.RESET}",
        "ok":       f"{C.GREEN}{C.BOLD} OK {C.RESET}",
        "warn":     f"{C.YELLOW}WARN{C.RESET}",
        "error":    f"{C.RED}{C.BOLD} ERR{C.RESET}",
        "progress": f"{C.MAGENTA}PROG{C.RESET}",
        "quest":    f"{C.CYAN}{C.BOLD}QEST{C.RESET}",
    }
    styled = level_styles.get(level, f"{C.DIM}{level.upper():>4}{C.RESET}")
    user_tag = f"{C.DIM}{username}{C.RESET}" if username != "system" else f"{C.CYAN}system{C.RESET}"
    print(f"  {C.DIM}{ts}{C.RESET}  {styled}  [{user_tag}]  {msg}")


# ═══════════════════════════════════════════════════════════════════════════════
#  DISCORD CLIENT EMULATION
# ═══════════════════════════════════════════════════════════════════════════════

def _get(d, *keys):
    """Safe multi-key dict lookup."""
    if d is None:
        return None
    for k in keys:
        if k in d:
            return d[k]
    return None


def parse_timestamp(value) -> Optional[float]:
    """Parse an ISO timestamp into epoch seconds; None when missing or invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


def response_completed(body: dict, task_type: str, seconds_needed: float) -> bool:
    """True when a quest API response confirms the task is done."""
    if body.get("completed_at"):
        return True
    progress = body.get("progress") or {}
    return (progress.get(task_type) or {}).get("value", 0) >= seconds_needed


def fetch_latest_build_number() -> int:
    """Scrape discord.com to get latest client build number."""
    FALLBACK = 504649
    try:
        r = requests.get("https://discord.com/app", headers={"User-Agent": USER_AGENT}, timeout=15)
        if r.status_code != 200:
            return FALLBACK
        scripts = re.findall(r'/assets/([a-f0-9]+)\.js', r.text)
        if not scripts:
            scripts_alt = re.findall(r'src="(/assets/[^"]+\.js)"', r.text)
            scripts = [s.split('/')[-1].replace('.js', '') for s in scripts_alt]
        if not scripts:
            return FALLBACK
        for asset_hash in scripts[-5:]:
            try:
                ar = requests.get(
                    f"https://discord.com/assets/{asset_hash}.js",
                    headers={"User-Agent": USER_AGENT}, timeout=15,
                )
                m = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', ar.text)
                if m:
                    return int(m.group(1))
            except Exception:
                continue
        return FALLBACK
    except Exception:
        return FALLBACK


def make_super_properties(build_number: int) -> str:
    obj = {
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_version": "1.0.9175",
        "os_version": "10.0.26100",
        "os_arch": "x64",
        "app_arch": "x64",
        "system_locale": "en-US",
        "browser_user_agent": USER_AGENT,
        "browser_version": "32.2.7",
        "client_build_number": build_number,
        "native_build_number": 59498,
        "client_event_source": None,
    }
    return base64.b64encode(json.dumps(obj).encode()).decode()


class DiscordAPI:
    """HTTP client mimicking Discord Desktop for API calls."""

    def __init__(self, token: str, build_number: int):
        self.token = token
        self.session = requests.Session()
        sp = make_super_properties(build_number)
        self.session.headers.update({
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": USER_AGENT,
            "X-Super-Properties": sp,
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
        })

    def get(self, path: str):
        return self.session.get(f"{API_BASE}{path}", timeout=REQUEST_TIMEOUT)

    def post(self, path: str, payload=None):
        return self.session.post(f"{API_BASE}{path}", json=payload, timeout=REQUEST_TIMEOUT)


# ═══════════════════════════════════════════════════════════════════════════════
#  QUEST HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_task_config(quest):
    cfg = quest.get("config", {})
    return _get(cfg, "taskConfig", "task_config", "taskConfigV2", "task_config_v2")


def get_quest_name(quest):
    cfg = quest.get("config", {})
    msgs = cfg.get("messages", {})
    name = _get(msgs, "questName", "quest_name")
    if name:
        return name.strip()
    game = _get(msgs, "gameTitle", "game_title")
    if game:
        return game.strip()
    app_name = cfg.get("application", {}).get("name")
    if app_name:
        return app_name
    return f"Quest#{quest.get('id', '?')}"


def get_expires_at(quest):
    cfg = quest.get("config", {})
    return _get(cfg, "expiresAt", "expires_at")


def get_user_status(quest):
    us = _get(quest, "userStatus", "user_status")
    return us if isinstance(us, dict) else {}


def is_completable(quest):
    expires = parse_timestamp(get_expires_at(quest))
    if expires and expires <= time.time():
        return False
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc:
        return False
    tasks = tc["tasks"]
    return any(tasks.get(t) is not None for t in SUPPORTED_TASKS)


def is_enrolled(quest):
    us = get_user_status(quest)
    return bool(_get(us, "enrolledAt", "enrolled_at"))


def is_completed(quest):
    us = get_user_status(quest)
    return bool(_get(us, "completedAt", "completed_at"))


def get_task_type(quest):
    tc = get_task_config(quest)
    if not tc or "tasks" not in tc:
        return None
    for t in SUPPORTED_TASKS:
        if tc["tasks"].get(t) is not None:
            return t
    return None


def get_seconds_needed(quest):
    tc = get_task_config(quest)
    task_type = get_task_type(quest)
    if not tc or not task_type:
        return 0
    return tc["tasks"][task_type].get("target", 0)


def get_seconds_done(quest):
    task_type = get_task_type(quest)
    if not task_type:
        return 0
    progress = get_user_status(quest).get("progress") or {}
    return (progress.get(task_type) or {}).get("value", 0)


def get_enrolled_at(quest):
    us = get_user_status(quest)
    return _get(us, "enrolledAt", "enrolled_at")


def decode_user_id(token: str) -> str:
    """Extract user ID from Discord token (base64 encoded first segment)."""
    try:
        part = token.split(".")[0]
        padding = 4 - len(part) % 4
        if padding != 4:
            part += "=" * padding
        decoded = base64.b64decode(part).decode("utf-8")
        return decoded
    except Exception:
        return "unknown"


def fetch_username(api: DiscordAPI) -> str:
    """Fetch the account username via /users/@me."""
    try:
        r = api.get("/users/@me")
        if r.status_code == 200:
            data = r.json()
            global_name = data.get("global_name") or data.get("username", "?")
            username = data.get("username", "?")
            return f"{global_name} (@{username})" if global_name != username else f"@{username}"
        return "unknown"
    except Exception:
        return "unknown"


# ═══════════════════════════════════════════════════════════════════════════════
#  QUEST COMPLETER
# ═══════════════════════════════════════════════════════════════════════════════

class QuestCompleter:
    """Auto-completes Discord quests for a single account."""

    def __init__(self, token: str, poll_interval: int = 60, run_once: bool = False):
        self.token = token.strip()
        self.poll_interval = max(10, min(600, poll_interval))
        self.run_once = run_once

        self.user_id = decode_user_id(self.token)
        self.username = "..."
        self._api: Optional[DiscordAPI] = None
        self._build_number = 0
        self._completed_ids: set = set()
        self._should_stop = False

        self.stats = {
            "quests_completed": 0,
            "quests_enrolled": 0,
            "cycles_run": 0,
            "start_time": None,
        }

    def _log(self, msg: str, level: str = "info"):
        log(msg, level, self.username)

    def stop(self):
        self._should_stop = True

    # ── Setup ─────────────────────────────────────────────────────────────

    def _init_session(self):
        """Fetch build number, create API session, resolve username."""
        self._log("Fetching build number from Discord...")
        self._build_number = fetch_latest_build_number()
        self._api = DiscordAPI(self.token, self._build_number)
        self._log(f"Build: {C.BOLD}{self._build_number}{C.RESET}", "ok")

        self._log("Authenticating account...")
        self.username = fetch_username(self._api)
        self._log(f"Logged in: {C.BOLD}{self.username}{C.RESET} (ID: {self.user_id})", "ok")

    # ── Fetch ─────────────────────────────────────────────────────────────

    def _fetch_quests(self) -> list:
        for _ in range(5):
            try:
                r = self._api.get("/quests/@me")

                if r.status_code == 429:
                    retry_after = r.json().get("retry_after", 10)
                    self._log(f"Rate limited — waiting {retry_after}s", "warn")
                    time.sleep(retry_after)
                    continue

                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict):
                        blocked = _get(data, "quest_enrollment_blocked_until")
                        if blocked:
                            self._log(f"Enrollment blocked until: {blocked}", "warn")
                        return data.get("quests") or []
                    if isinstance(data, list):
                        return data
                    return []

                if r.status_code == 401:
                    self._log(f"{C.RED}Invalid or expired token!{C.RESET}", "error")
                    self._should_stop = True
                    return []

                if r.status_code == 403:
                    self._log(f"{C.RED}Account locked or forbidden!{C.RESET}", "error")
                    self._should_stop = True
                    return []

                self._log(f"Error fetching quests ({r.status_code}): {r.text[:200]}", "warn")
                return []

            except requests.ConnectionError:
                self._log("Network connection lost, retrying in 10s...", "error")
                time.sleep(10)
            except Exception as e:
                self._log(f"Error fetching quests: {e}", "error")
                return []

        self._log("Quest fetch failed after 5 retries, skipping this scan", "warn")
        return []

    # ── Enroll ────────────────────────────────────────────────────────────

    def _enroll_quest(self, quest: dict) -> bool:
        name = get_quest_name(quest)
        qid = quest["id"]
        for attempt in range(1, 4):
            try:
                r = self._api.post(f"/quests/{qid}/enroll", {
                    "location": 11,
                    "is_targeted": False,
                    "metadata_raw": None,
                    "metadata_sealed": None,
                    "traffic_metadata_raw": quest.get("traffic_metadata_raw"),
                    "traffic_metadata_sealed": quest.get("traffic_metadata_sealed"),
                })
                if r.status_code == 429:
                    retry_after = r.json().get("retry_after", 5)
                    self._log(f"Rate limited enroll (attempt {attempt}/3) — waiting {retry_after + 1}s", "warn")
                    time.sleep(retry_after + 1)
                    continue
                if r.status_code in (200, 201, 204):
                    self.stats["quests_enrolled"] += 1
                    self._log(f"  {C.GREEN}󰄬{C.RESET} Enrolled quest: {C.BOLD}{name}{C.RESET}", "ok")
                    return True
                self._log(f"Enroll failed ({r.status_code}): {r.text[:100]}", "warn")
                return False
            except Exception as e:
                self._log(f"Enroll error: {e}", "error")
                return False
        return False

    # ── Complete: Video ───────────────────────────────────────────────────

    def _complete_video(self, quest: dict) -> bool:
        name = get_quest_name(quest)
        qid = quest["id"]
        task_type = get_task_type(quest)
        seconds_needed = get_seconds_needed(quest)
        seconds_done = get_seconds_done(quest)
        enrolled_ts = parse_timestamp(get_enrolled_at(quest)) or time.time()

        self._log(f"󰕧 Video: {C.BOLD}{name}{C.RESET} ({seconds_done:.0f}/{seconds_needed}s)", "quest")

        max_future = 10
        speed = 7
        interval = 1
        failures = 0

        while seconds_done < seconds_needed and not self._should_stop:
            max_allowed = (time.time() - enrolled_ts) + max_future
            diff = max_allowed - seconds_done
            timestamp = seconds_done + speed

            if diff >= speed:
                try:
                    r = self._api.post(f"/quests/{qid}/video-progress", {
                        "timestamp": min(seconds_needed, timestamp + random.random())
                    })
                    if r.status_code == 200:
                        failures = 0
                        body = r.json()
                        if response_completed(body, task_type, seconds_needed):
                            return True
                        seconds_done = min(seconds_needed, timestamp)
                        pct = (seconds_done / seconds_needed * 100) if seconds_needed else 100
                        self._log(f"  {_progress_bar(pct)} {seconds_done:.0f}/{seconds_needed}s", "progress")
                    elif r.status_code == 429:
                        failures += 1
                        retry_after = r.json().get("retry_after", 5)
                        self._log(f"Rate limited — waiting {retry_after + 1}s", "warn")
                        time.sleep(retry_after + 1)
                    else:
                        failures += 1
                        self._log(f"Video progress error ({r.status_code}): {r.text[:200]}", "warn")
                except Exception as e:
                    failures += 1
                    self._log(f"Video progress error: {e}", "error")

                if failures >= MAX_FAILURES:
                    self._log(f"  Giving up on \"{name}\" after {failures} failed requests, will retry next scan", "warn")
                    return False

            if timestamp >= seconds_needed:
                break
            time.sleep(interval)

        if self._should_stop:
            return False

        # Final request at the target timestamp; only trust a confirmed response.
        try:
            r = self._api.post(f"/quests/{qid}/video-progress", {"timestamp": seconds_needed})
            if r.status_code == 200 and response_completed(r.json(), task_type, seconds_needed):
                return True
            self._log(f"Final video request not confirmed ({r.status_code})", "warn")
        except Exception as e:
            self._log(f"Final video request failed: {e}", "error")
        return False

    # ── Complete: Heartbeat (Play/Stream/Activity) ────────────────────────

    def _complete_heartbeat(self, quest: dict, stream_key: str, label: str) -> bool:
        name = get_quest_name(quest)
        qid = quest["id"]
        task_type = get_task_type(quest)
        seconds_needed = get_seconds_needed(quest)
        seconds_done = get_seconds_done(quest)

        remaining = max(0, seconds_needed - seconds_done)
        self._log(f"{label}: {C.BOLD}{name}{C.RESET} (~{remaining // 60}m remaining)", "quest")

        stalls = 0
        last_done = seconds_done

        while seconds_done < seconds_needed and not self._should_stop:
            try:
                r = self._api.post(f"/quests/{qid}/heartbeat", {
                    "stream_key": stream_key,
                    "terminal": False,
                })

                if r.status_code == 200:
                    body = r.json()
                    progress_data = body.get("progress") or {}
                    if task_type in progress_data:
                        seconds_done = (progress_data[task_type] or {}).get("value", seconds_done)

                    pct = (seconds_done / seconds_needed * 100) if seconds_needed else 100
                    self._log(f"  {_progress_bar(pct)} {seconds_done:.0f}/{seconds_needed}s", "progress")

                    if body.get("completed_at") or seconds_done >= seconds_needed:
                        return True

                    if seconds_done > last_done:
                        last_done = seconds_done
                        stalls = 0
                    else:
                        stalls += 1

                elif r.status_code == 429:
                    stalls += 1
                    retry_after = r.json().get("retry_after", 10)
                    self._log(f"Rate limited — waiting {retry_after + 1}s", "warn")
                    time.sleep(retry_after + 1)
                else:
                    stalls += 1
                    self._log(f"Heartbeat error ({r.status_code}): {r.text[:200]}", "warn")

            except Exception as e:
                stalls += 1
                self._log(f"Heartbeat error: {e}", "error")

            if stalls >= MAX_STALLS:
                self._log(f"  No progress after {stalls} heartbeats, will retry \"{name}\" next scan", "warn")
                return False

            time.sleep(HEARTBEAT_INTERVAL)

        if self._should_stop:
            return False

        # Terminal heartbeat; confirm from its response when possible.
        try:
            r = self._api.post(f"/quests/{qid}/heartbeat", {
                "stream_key": stream_key,
                "terminal": True,
            })
            if r.status_code == 200 and response_completed(r.json(), task_type, seconds_needed):
                return True
        except Exception as e:
            self._log(f"Final heartbeat failed: {e}", "error")

        # Server already reported the target reached.
        return seconds_done >= seconds_needed

    # ── Process ───────────────────────────────────────────────────────────

    def _process_quest(self, quest: dict):
        qid = quest.get("id")
        name = get_quest_name(quest)
        task_type = get_task_type(quest)

        if not task_type:
            self._log(f"  󰀦  \"{name}\" — unsupported task, skipping", "warn")
            return
        if qid in self._completed_ids:
            return
        if self._should_stop:
            return

        self._log(f"{'━' * 50}", "info")
        self._log(f"󰐊 Starting: {C.BOLD}{name}{C.RESET} (task: {C.CYAN}{task_type}{C.RESET})", "quest")

        if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
            ok = self._complete_video(quest)
        elif task_type in ("PLAY_ON_DESKTOP", "STREAM_ON_DESKTOP"):
            pid = random.randint(1000, 30000)
            emoji = "󰊴" if task_type == "PLAY_ON_DESKTOP" else "󰓦"
            ok = self._complete_heartbeat(quest, f"call:0:{pid}", f"{emoji} {task_type}")
        else:
            ok = self._complete_heartbeat(quest, "call:0:1", "󰊵  Activity")

        if ok:
            self.stats["quests_completed"] += 1
            self._completed_ids.add(qid)
            self._log(f"  {C.GREEN}󰄲 Completed: {name}{C.RESET}", "ok")
        elif not self._should_stop:
            self._log(f"  {C.YELLOW}Not completed: {name} — will retry next scan{C.RESET}", "warn")

    # ── Main Run ──────────────────────────────────────────────────────────

    def run(self):
        """Main entry point — runs the quest auto-completer."""
        self.stats["start_time"] = time.time()

        # Init
        try:
            self._init_session()
        except Exception as e:
            self._log(f"Failed to initialize session: {e}", "error")
            return

        cycle = 0

        while not self._should_stop:
            cycle += 1
            self.stats["cycles_run"] += 1
            self._log(f"{'─' * 50}", "info")
            self._log(f"󰍉 Scan #{cycle}", "info")

            # Fetch quests
            quests = self._fetch_quests()
            if self._should_stop:
                break

            if quests:
                total = len(quests)
                enrolled_count = sum(1 for q in quests if is_enrolled(q))
                completed_count = sum(1 for q in quests if is_completed(q))
                completable_count = sum(1 for q in quests if is_completable(q))

                self._log(
                    f"  Total: {C.BOLD}{total}{C.RESET} | "
                    f"Enrolled: {C.CYAN}{enrolled_count}{C.RESET} | "
                    f"Done: {C.GREEN}{completed_count}{C.RESET} | "
                    f"Completable: {C.YELLOW}{completable_count}{C.RESET}",
                    "info",
                )

                # Auto-accept
                unaccepted = [
                    q for q in quests
                    if not is_enrolled(q) and not is_completed(q) and is_completable(q)
                ]
                if unaccepted:
                    self._log(f"  󰏤 Auto-enrolling {len(unaccepted)} new quest(s)...", "quest")
                    for q in unaccepted:
                        self._enroll_quest(q)
                        time.sleep(3)
                    quests = self._fetch_quests()

                # Process enrolled + incomplete quests
                actionable = [
                    q for q in quests
                    if is_enrolled(q) and not is_completed(q) and is_completable(q)
                    and q.get("id") not in self._completed_ids
                ]
                if actionable:
                    self._log(f"  󰓅 {len(actionable)} quest(s) to complete:", "quest")
                    for q in actionable:
                        if self._should_stop:
                            break
                        try:
                            self._process_quest(q)
                        except Exception as e:
                            self._log(f"Error processing quest {q.get('id', '?')}: {e}", "error")
                else:
                    self._log("  󰒲 No quests to complete", "info")
            else:
                self._log("  󰒲 No quests found", "info")

            # Summary
            self._log(self._stats_summary(), "info")

            # If --once, exit after first cycle
            if self.run_once:
                self._log("--once mode: exiting after 1 scan.", "info")
                break

            # Wait
            self._log(f"  󱑂 Waiting {self.poll_interval}s before next scan...", "info")
            for _ in range(self.poll_interval):
                if self._should_stop:
                    break
                time.sleep(1)

        # Final stats
        self._print_final_stats()

    def _stats_summary(self) -> str:
        elapsed = int(time.time() - self.stats["start_time"]) if self.stats["start_time"] else 0
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        return (
            f"  󰄛 Completed: {C.GREEN}{self.stats['quests_completed']}{C.RESET} | "
            f"Enrolled: {C.CYAN}{self.stats['quests_enrolled']}{C.RESET} | "
            f"Cycles: {self.stats['cycles_run']} | "
            f"Runtime: {h}h{m}m{s}s"
        )

    def _print_final_stats(self):
        elapsed = int(time.time() - self.stats["start_time"]) if self.stats["start_time"] else 0
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        print()
        print(f"  {C.CYAN}{'═' * 50}{C.RESET}")
        print(f"  {C.BOLD}󰄛 RESULTS — {self.username}{C.RESET}")
        print(f"  {C.CYAN}{'─' * 50}{C.RESET}")
        print(f"  󰄲 Quests completed : {C.GREEN}{C.BOLD}{self.stats['quests_completed']}{C.RESET}")
        print(f"  󰏤 Quests enrolled  : {C.CYAN}{self.stats['quests_enrolled']}{C.RESET}")
        print(f"  󰑐 Total scan cycles : {self.stats['cycles_run']}")
        print(f"  󰔟  Total runtime    : {h}h {m}m {s}s")
        print(f"  {C.CYAN}{'═' * 50}{C.RESET}")
        print()


# ═══════════════════════════════════════════════════════════════════════════════
#  UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _progress_bar(pct: float, width: int = 20) -> str:
    """Render a colored progress bar."""
    filled = int(width * pct / 100)
    empty = width - filled
    if pct >= 100:
        color = C.GREEN
    elif pct >= 50:
        color = C.CYAN
    elif pct >= 25:
        color = C.YELLOW
    else:
        color = C.RED
    bar = f"{color}{'█' * filled}{C.DIM}{'░' * empty}{C.RESET}"
    return f"[{bar}] {pct:5.1f}%"


def mask_token(token: str) -> str:
    """Show only first 10 and last 5 chars of a token."""
    if len(token) <= 20:
        return token[:5] + "****" + token[-3:]
    return token[:10] + "..." + token[-5:]


# ═══════════════════════════════════════════════════════════════════════════════
#  MULTI-ACCOUNT RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

def run_multiple(tokens: list[str], poll_interval: int = 60, run_once: bool = False):
    """Run quest completers for multiple tokens concurrently."""
    if not tokens:
        log("No tokens provided!", "error")
        return

    completers = []
    threads = []

    log(f"Preparing to run {C.BOLD}{len(tokens)}{C.RESET} account(s)...", "info")
    print()

    for i, token in enumerate(tokens):
        token = token.strip()
        if not token or token.startswith("#"):
            continue
        log(f"  [{i + 1}/{len(tokens)}] Token: {C.DIM}{mask_token(token)}{C.RESET}", "info")
        completer = QuestCompleter(token, poll_interval, run_once)
        completers.append(completer)

    if not completers:
        log("No valid tokens found!", "error")
        return

    # Signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print()
        log(f"{C.YELLOW}Stopping all workers...{C.RESET}", "warn")
        for c in completers:
            c.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run each in a thread
    if len(completers) == 1:
        # Single account — run in main thread for simplicity
        completers[0].run()
    else:
        for c in completers:
            t = threading.Thread(target=c.run, daemon=True)
            threads.append(t)
            t.start()
            time.sleep(2)  # stagger starts

        # Wait for all
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            log("Stopping...", "warn")
            for c in completers:
                c.stop()
            for t in threads:
                t.join(timeout=10)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def interactive_prompt() -> list[str]:
    """Interactive mode: prompt user to paste tokens."""
    tokens = []
    while True:
        try:
            raw = input(f"  {C.CYAN}Token #{len(tokens) + 1}{C.RESET} (or 'done'): ").strip()
            if not raw or raw.lower() == "done":
                break
            if len(raw) < 50:
                print(f"  {C.RED}󰀦  Token too short (< 50 chars), skipping.{C.RESET}")
                continue
            tokens.append(raw)
            print(f"  {C.GREEN}󰄬{C.RESET} Added: {C.DIM}{mask_token(raw)}{C.RESET}")
        except (EOFError, KeyboardInterrupt):
            break

    return tokens


def main():
    parser = argparse.ArgumentParser(
        description="Discord Quest Auto-Completer (Standalone)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  python direct_run.py                       # Interactive mode
  python direct_run.py --file tokens.txt     # Multi-token file
  python direct_run.py --once                # Run once and exit
  python direct_run.py --poll 120            # Poll every 120 seconds
""",
    )
    parser.add_argument("--file", "-f", type=str, help="File containing token(s), one per line")
    parser.add_argument("--poll", "-p", type=int, default=60, help="Polling interval between scans (seconds, default: 60)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")

    args = parser.parse_args()

    tokens = []

    if args.file:
        if not os.path.isfile(args.file):
            print(f"  {C.RED}󰅖 File does not exist: {args.file}{C.RESET}")
            sys.exit(1)
        with open(args.file, "r") as f:
            tokens = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        log(f"Read {len(tokens)} token(s) from {C.BOLD}{args.file}{C.RESET}", "ok")
    else:
        tokens = interactive_prompt()

    if not tokens:
        print(f"  {C.RED}󰅖 No tokens available. Exiting.{C.RESET}")
        sys.exit(1)

    print(f"\n  {C.CYAN}{'═' * 50}{C.RESET}")
    log(f"Starting with {C.BOLD}{len(tokens)}{C.RESET} account(s) | Poll: {args.poll}s | Once: {args.once}", "info")
    print(f"  {C.CYAN}{'═' * 50}{C.RESET}\n")

    run_multiple(tokens, args.poll, args.once)

    print(f"\n  {C.GREEN}{C.BOLD}󰈅 Done! Exiting.{C.RESET}\n")


if __name__ == "__main__":
    main()
