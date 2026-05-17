import base64
import calendar
import json
import os
import re
import subprocess
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

try:
    from winotify import Notification
    HAS_TOAST = True
except Exception:
    HAS_TOAST = False

try:
    from streamlit_mic_recorder import mic_recorder
    HAS_MIC = True
except Exception:
    HAS_MIC = False

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SCHEDULES_FILE = DATA_DIR / "schedules.json"
MEMOS_FILE = DATA_DIR / "memos.json"
TODOS_FILE = DATA_DIR / "todos.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
CHAT_FILE       = DATA_DIR / "chat_history.json"
HABITS_FILE     = DATA_DIR / "habits.json"
GOALS_FILE      = DATA_DIR / "goals.json"
LEDGER_FILE     = DATA_DIR / "ledger.json"
BOOKS_FILE      = DATA_DIR / "books.json"
WORKOUTS_FILE   = DATA_DIR / "workouts.json"

CHAT_MAX_MESSAGES = 200   # 파일에 보관할 최대 메시지 수
CHAT_CONTEXT_LIMIT = 30   # Gemini에 전달할 최근 메시지 수

# 인천 송도 좌표
WEATHER_LAT = 37.3836
WEATHER_LON = 126.6564
WEATHER_LOCATION = "인천 송도"

# 구글 캘린더
GOOGLE_CREDS_FILE = Path(__file__).parent / "credentials.json"
GOOGLE_TOKEN_FILE = DATA_DIR / "token.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GOOGLE_CALENDAR_ID = "primary"

REMINDER_THRESHOLDS = [30, 15, 5]

RECURRENCE_OPTIONS = {
    "안 함 (1회)": "none",
    "🔁 매일": "daily",
    "🔁 매주": "weekly",
    "🔁 매월": "monthly",
}
RECURRENCE_LABEL = {
    "none": "",
    "daily": "🔁 매일",
    "weekly": "🔁 매주",
    "monthly": "🔁 매월",
}
IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

EXPENSE_CATEGORIES = ["식비", "교통", "쇼핑", "의료", "문화", "교육", "기타"]
INCOME_CATEGORIES  = ["급여", "용돈", "부수입", "기타"]
WORKOUT_TYPES      = ["달리기", "걷기", "헬스", "수영", "자전거", "요가", "필라테스", "등산", "기타"]
BOOK_STATUS_MAP    = {"want": "📚 읽고싶어요", "reading": "📖 읽는중", "done": "✅ 완독"}
POMO_WORK_SEC       = 25 * 60
POMO_BREAK_SEC      = 5  * 60
POMO_LONG_BREAK_SEC = 15 * 60

MOOD_FILE      = DATA_DIR / "mood.json"
LINKS_FILE     = DATA_DIR / "links.json"
SLEEP_FILE     = DATA_DIR / "sleep.json"
MEDS_FILE      = DATA_DIR / "medications.json"

MOOD_EMOJIS    = ["😞", "😕", "😐", "🙂", "😄"]
MOOD_LABELS    = ["별로", "조금 별로", "보통", "좋음", "최고"]
LINK_CATEGORIES = ["업무", "공부", "취미", "쇼핑", "뉴스", "기타"]

TODO_PRIORITY  = {"high": "🔴 높음", "medium": "🟡 보통", "low": "🟢 낮음"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
TRANS_LANGS    = ["영어", "일본어", "중국어", "스페인어", "프랑스어", "독일어", "한국어"]


# ════════════════════════════════════════
#  유틸리티
# ════════════════════════════════════════
@st.cache_resource
def _get_supabase():
    """Supabase 클라이언트 반환 (설정 안 됐으면 None)"""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _load(path):
    sb = _get_supabase()
    if sb:
        try:
            r = sb.table("app_data").select("value").eq("key", path.stem).execute()
            if r.data:
                return r.data[0]["value"]
            return []
        except Exception:
            pass
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path, items):
    sb = _get_supabase()
    if sb:
        try:
            sb.table("app_data").upsert({"key": path.stem, "value": items}).execute()
            return
        except Exception:
            pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_settings() -> dict:
    sb = _get_supabase()
    if sb:
        try:
            r = sb.table("app_data").select("value").eq("key", "settings").execute()
            if r.data:
                return r.data[0]["value"]
            return {"dark_mode": False}
        except Exception:
            pass
    if not SETTINGS_FILE.exists():
        return {"dark_mode": False}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(settings: dict):
    sb = _get_supabase()
    if sb:
        try:
            sb.table("app_data").upsert({"key": "settings", "value": settings}).execute()
            return
        except Exception:
            pass
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ─── 채팅 기록 ───
def load_chat_history() -> list:
    sb = _get_supabase()
    if sb:
        try:
            r = sb.table("app_data").select("value").eq("key", "chat_history").execute()
            if r.data:
                return r.data[0]["value"]
            return []
        except Exception:
            pass
    if not CHAT_FILE.exists():
        return []
    with open(CHAT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_chat_history(messages: list):
    # 최대 CHAT_MAX_MESSAGES 개만 보관
    trimmed = messages[-CHAT_MAX_MESSAGES:]
    sb = _get_supabase()
    if sb:
        try:
            sb.table("app_data").upsert({"key": "chat_history", "value": trimmed}).execute()
            return
        except Exception:
            pass
    with open(CHAT_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def clear_chat_history():
    sb = _get_supabase()
    if sb:
        try:
            sb.table("app_data").delete().eq("key", "chat_history").execute()
            return
        except Exception:
            pass
    if CHAT_FILE.exists():
        CHAT_FILE.unlink()


def highlight(text: str, query: str) -> str:
    """검색어를 노란 하이라이트로 강조"""
    if not text or not query:
        return text or ""
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.sub(
        lambda m: f'<mark style="background:#fff3cd;padding:0 3px;border-radius:3px;'
                  f'color:#37352f">{m.group()}</mark>',
        text,
    )


# ════════════════════════════════════════
#  구글 캘린더 연동
# ════════════════════════════════════════
def _google_libs_ok() -> bool:
    try:
        import google.oauth2.credentials  # noqa
        import googleapiclient.discovery  # noqa
        return True
    except ImportError:
        return False


def get_google_creds():
    """저장된 토큰으로 인증. (creds, error_msg) 반환"""
    if not _google_libs_ok():
        return None, "라이브러리 미설치 (아래 안내 참고)"
    if not GOOGLE_CREDS_FILE.exists():
        return None, "credentials.json 없음"

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    creds = None
    if GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES)
    if creds and creds.valid:
        return creds, None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            GOOGLE_TOKEN_FILE.write_text(creds.to_json())
            return creds, None
        except Exception:
            GOOGLE_TOKEN_FILE.unlink(missing_ok=True)
    return None, "로그인 필요"


def do_google_auth():
    """OAuth 브라우저 로그인. (creds, error_msg) 반환"""
    if not _google_libs_ok():
        return None, "라이브러리 미설치"
    if not GOOGLE_CREDS_FILE.exists():
        return None, "credentials.json 없음"
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            str(GOOGLE_CREDS_FILE), GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        GOOGLE_TOKEN_FILE.write_text(creds.to_json())
        return creds, None
    except Exception as e:
        return None, str(e)


def _build_service(creds):
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=creds)


def _parse_google_dt(start: dict):
    """구글 이벤트 start → datetime (KST naive)"""
    dt_str = start.get("dateTime") or start.get("date", "")
    if not dt_str:
        return None
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _rrule_to_recurrence(rules: list) -> str:
    for r in rules:
        if "FREQ=DAILY" in r:
            return "daily"
        if "FREQ=WEEKLY" in r:
            return "weekly"
        if "FREQ=MONTHLY" in r:
            return "monthly"
    return "none"


def _recurrence_to_rrule(rec: str) -> list:
    mapping = {"daily": "RRULE:FREQ=DAILY", "weekly": "RRULE:FREQ=WEEKLY",
               "monthly": "RRULE:FREQ=MONTHLY"}
    return [mapping[rec]] if rec in mapping else []


def sync_from_google(creds) -> tuple:
    """구글 → 로컬. (추가, 업데이트) 개수 반환"""
    service = _build_service(creds)
    now_iso = datetime.utcnow().isoformat() + "Z"
    end_iso = (datetime.utcnow() + timedelta(days=60)).isoformat() + "Z"

    result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=now_iso, timeMax=end_iso,
        singleEvents=False, maxResults=100,
    ).execute()
    gevents = result.get("items", [])

    local = load_schedules()
    by_gid = {s["google_id"]: i for i, s in enumerate(local) if s.get("google_id")}

    added = updated = 0
    for ev in gevents:
        if ev.get("status") == "cancelled":
            continue
        dt = _parse_google_dt(ev.get("start", {}))
        if not dt:
            continue
        rec = _rrule_to_recurrence(ev.get("recurrence", []))
        gid = ev["id"]

        entry = {
            "id": str(uuid.uuid4()),
            "datetime": dt.strftime("%Y-%m-%dT%H:%M"),
            "title": ev.get("summary", "(제목 없음)"),
            "note": ev.get("description", ""),
            "recurrence": rec,
            "google_id": gid,
            "source": "google",
        }

        if gid in by_gid:
            idx = by_gid[gid]
            local[idx].update({k: entry[k] for k in
                               ("datetime", "title", "note", "recurrence")})
            updated += 1
        else:
            local.append(entry)
            added += 1

    local.sort(key=lambda s: s["datetime"])
    save_schedules(local)
    return added, updated


def sync_to_google(creds) -> int:
    """로컬 → 구글. 새로 추가된 개수 반환"""
    service = _build_service(creds)
    local = load_schedules()
    pushed = 0

    for i, s in enumerate(local):
        if s.get("google_id"):
            continue  # 이미 연동됨
        try:
            dt = datetime.fromisoformat(s["datetime"])
        except ValueError:
            continue

        body = {
            "summary": s["title"],
            "description": s.get("note", ""),
            "start": {"dateTime": dt.isoformat(), "timeZone": "Asia/Seoul"},
            "end": {"dateTime": (dt + timedelta(hours=1)).isoformat(), "timeZone": "Asia/Seoul"},
        }
        rrule = _recurrence_to_rrule(s.get("recurrence", "none"))
        if rrule:
            body["recurrence"] = rrule

        try:
            created = service.events().insert(
                calendarId=GOOGLE_CALENDAR_ID, body=body
            ).execute()
            local[i]["google_id"] = created["id"]
            local[i]["source"] = "synced"
            pushed += 1
        except Exception:
            continue

    save_schedules(local)
    return pushed


def delete_from_google(creds, google_id: str):
    """구글 캘린더에서 이벤트 삭제"""
    try:
        service = _build_service(creds)
        service.events().delete(
            calendarId=GOOGLE_CALENDAR_ID, eventId=google_id
        ).execute()
    except Exception:
        pass


def weather_info(code: int, is_night: bool = False) -> tuple:
    """WMO 날씨 코드 → (이모지, 한국어 설명)"""
    if code == 0:
        return ("🌙", "맑음") if is_night else ("☀️", "맑음")
    if code in (1, 2):
        return ("🌙", "구름 조금") if is_night else ("⛅", "구름 조금")
    if code == 3:
        return "☁️", "흐림"
    if code in (45, 48):
        return "🌫️", "안개"
    if code in (51, 53, 55):
        return "🌦️", "이슬비"
    if code in (61, 63):
        return "🌧️", "비"
    if code == 65:
        return "🌧️", "강한 비"
    if code in (71, 73, 75):
        return "❄️", "눈"
    if code in (77,):
        return "🌨️", "진눈깨비"
    if code in (80, 81, 82):
        return "🌦️", "소나기"
    if code in (85, 86):
        return "🌨️", "눈 소나기"
    if code in (95, 96, 99):
        return "⛈️", "뇌우"
    return "🌡️", "날씨 확인 중"


@st.cache_data(ttl=1800)  # 30분마다 갱신
def fetch_weather() -> dict | None:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
        "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
        "precipitation,weather_code,wind_speed_10m,is_day"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
        "&timezone=Asia%2FSeoul"
        "&wind_speed_unit=ms"
        "&forecast_days=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        cur = data["current"]
        daily = data.get("daily", {})
        return {
            "temp": round(cur["temperature_2m"]),
            "feels_like": round(cur["apparent_temperature"]),
            "humidity": cur["relative_humidity_2m"],
            "wind": cur["wind_speed_10m"],
            "code": cur["weather_code"],
            "is_day": bool(cur.get("is_day", 1)),
            "temp_max": round(daily["temperature_2m_max"][0]) if daily.get("temperature_2m_max") else None,
            "temp_min": round(daily["temperature_2m_min"][0]) if daily.get("temperature_2m_min") else None,
            "precip_today": daily["precipitation_sum"][0] if daily.get("precipitation_sum") else 0,
        }
    except Exception:
        return None


def date_separator_label(ts_str: str) -> str:
    """메시지 타임스탬프를 '오늘', '어제', '5월 12일' 등으로 변환"""
    try:
        d = datetime.fromisoformat(ts_str).date()
    except Exception:
        return ""
    today = date.today()
    diff = (today - d).days
    if diff == 0:
        return "오늘"
    if diff == 1:
        return "어제"
    if diff < 7:
        weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
        return f"이번 주 {weekday_kr[d.weekday()]}요일"
    return d.strftime("%Y년 %m월 %d일")


def format_countdown(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 60:
        return "곧!"
    if total < 3600:
        return f"{total // 60}분 후"
    if total < 86400:
        h = total // 3600
        m = (total % 3600) // 60
        return f"{h}시간 {m}분 후" if m else f"{h}시간 후"
    return f"{delta.days}일 후"


# ════════════════════════════════════════
#  일정
# ════════════════════════════════════════
def load_schedules():
    items = _load(SCHEDULES_FILE)
    for s in items:
        s.setdefault("recurrence", "none")
    return items


def save_schedules(items):
    _save(SCHEDULES_FILE, items)


def add_schedule(when: datetime, title: str, note: str, recurrence: str = "none"):
    items = load_schedules()
    items.append({
        "id": str(uuid.uuid4()),
        "datetime": when.isoformat(timespec="minutes"),
        "title": title,
        "note": note,
        "recurrence": recurrence,
    })
    items.sort(key=lambda s: s["datetime"])
    save_schedules(items)


def update_schedule(item_id: str, when: datetime, title: str, note: str, recurrence: str = "none"):
    items = load_schedules()
    for s in items:
        if s["id"] == item_id:
            s["datetime"] = when.isoformat(timespec="minutes")
            s["title"] = title
            s["note"] = note
            s["recurrence"] = recurrence
    items.sort(key=lambda s: s["datetime"])
    save_schedules(items)


def delete_schedule(item_id: str):
    save_schedules([s for s in load_schedules() if s["id"] != item_id])


def _advance(dt: datetime, recurrence: str):
    if recurrence == "daily":
        return dt + timedelta(days=1)
    if recurrence == "weekly":
        return dt + timedelta(weeks=1)
    if recurrence == "monthly":
        month = dt.month + 1
        year = dt.year + (1 if month > 12 else 0)
        month = ((month - 1) % 12) + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)
    return None


def expand_schedule_in_range(s, start: datetime, end: datetime):
    try:
        base = datetime.fromisoformat(s["datetime"])
    except ValueError:
        return []
    recurrence = s.get("recurrence", "none")
    if recurrence == "none":
        return [base] if start <= base <= end else []
    occurrences = []
    current = base
    safety = 0
    while current < start and safety < 100000:
        nxt = _advance(current, recurrence)
        if nxt is None:
            break
        current = nxt
        safety += 1
    while current <= end and safety < 100000:
        occurrences.append(current)
        nxt = _advance(current, recurrence)
        if nxt is None:
            break
        current = nxt
        safety += 1
    return occurrences


def next_occurrence(s, after: datetime = None):
    if after is None:
        after = datetime.now()
    try:
        base = datetime.fromisoformat(s["datetime"])
    except ValueError:
        return None
    recurrence = s.get("recurrence", "none")
    if recurrence == "none":
        return base if base >= after else None
    current = base
    safety = 0
    if current >= after:
        return current
    while current < after and safety < 100000:
        nxt = _advance(current, recurrence)
        if nxt is None:
            return None
        current = nxt
        safety += 1
    return current


def get_upcoming_occurrences(within_days: int = 30):
    now = datetime.now()
    end = now + timedelta(days=within_days)
    result = []
    for s in load_schedules():
        for occ in expand_schedule_in_range(s, now, end):
            result.append((s, occ))
    result.sort(key=lambda x: x[1])
    return result


def get_occurrences_on_date(d: date):
    start = datetime.combine(d, time(0, 0))
    end = datetime.combine(d, time(23, 59))
    result = []
    for s in load_schedules():
        for occ in expand_schedule_in_range(s, start, end):
            result.append((s, occ))
    result.sort(key=lambda x: x[1])
    return result


def is_past_schedule(s) -> bool:
    if s.get("recurrence", "none") != "none":
        return False
    try:
        return datetime.fromisoformat(s["datetime"]) < datetime.now()
    except ValueError:
        return False


# ════════════════════════════════════════
#  메모
# ════════════════════════════════════════
def load_memos():
    return _load(MEMOS_FILE)


def save_memos(items):
    _save(MEMOS_FILE, items)


def add_memo(title: str, content: str, tags: list = None):
    items = load_memos()
    items.append({
        "id": str(uuid.uuid4()),
        "created_at": datetime.now().isoformat(timespec="minutes"),
        "title": title,
        "content": content,
        "tags": tags or [],
    })
    items.sort(key=lambda m: m["created_at"], reverse=True)
    save_memos(items)


def update_memo(item_id: str, title: str, content: str):
    items = load_memos()
    for m in items:
        if m["id"] == item_id:
            m["title"] = title
            m["content"] = content
    save_memos(items)


def delete_memo(item_id: str):
    save_memos([m for m in load_memos() if m["id"] != item_id])


# ════════════════════════════════════════
#  할 일
# ════════════════════════════════════════
def load_todos():
    return _load(TODOS_FILE)


def save_todos(items):
    _save(TODOS_FILE, items)


def add_todo(title: str, priority: str = "medium"):
    items = load_todos()
    items.append({
        "id": str(uuid.uuid4()),
        "created_at": datetime.now().isoformat(timespec="minutes"),
        "title": title,
        "completed": False,
        "completed_at": None,
        "priority": priority,
    })
    save_todos(items)


def toggle_todo(item_id: str):
    items = load_todos()
    for t in items:
        if t["id"] == item_id:
            t["completed"] = not t["completed"]
            t["completed_at"] = (
                datetime.now().isoformat(timespec="minutes") if t["completed"] else None
            )
    save_todos(items)


def delete_todo(item_id: str):
    save_todos([t for t in load_todos() if t["id"] != item_id])


# ════════════════════════════════════════
#  습관 트래커
# ════════════════════════════════════════
def load_habits(): return _load(HABITS_FILE)
def save_habits(items): _save(HABITS_FILE, items)

def add_habit(name: str, icon: str = "✅"):
    items = load_habits()
    items.append({"id": str(uuid.uuid4()), "name": name, "icon": icon,
                  "created_at": date.today().isoformat(), "check_dates": []})
    save_habits(items)

def toggle_habit(habit_id: str, d: str = None):
    d = d or date.today().isoformat()
    items = load_habits()
    for h in items:
        if h["id"] == habit_id:
            if d in h["check_dates"]:
                h["check_dates"].remove(d)
            else:
                h["check_dates"].append(d)
    save_habits(items)

def delete_habit(habit_id: str):
    save_habits([h for h in load_habits() if h["id"] != habit_id])

def habit_streak(h) -> int:
    checked = set(h.get("check_dates", []))
    streak = 0
    d = date.today()
    while d.isoformat() in checked:
        streak += 1
        d -= timedelta(days=1)
    return streak

def habit_week_status(h) -> list:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    checked = set(h.get("check_dates", []))
    return [(monday + timedelta(days=i)).isoformat() in checked for i in range(7)]


# ════════════════════════════════════════
#  목표 관리
# ════════════════════════════════════════
def load_goals(): return _load(GOALS_FILE)
def save_goals(items): _save(GOALS_FILE, items)

GOAL_TYPE_OPTIONS = {
    "manual":        "✏️ 직접 입력",
    "workout_count": "🏃 이번달 운동 횟수 자동추적",
    "expense_limit": "💰 이번달 지출 한도 자동추적",
}


def add_goal(title: str, description: str, deadline: str, target: int = 100, goal_type: str = "manual"):
    items = load_goals()
    items.append({"id": str(uuid.uuid4()), "title": title, "description": description,
                  "deadline": deadline, "progress": 0, "target": target,
                  "goal_type": goal_type,
                  "created_at": date.today().isoformat(), "completed": False})
    save_goals(items)


def compute_auto_goal_progress(goal: dict) -> int:
    """자동 추적 목표의 현재 진행값을 데이터에서 계산"""
    gtype = goal.get("goal_type", "manual")
    today = date.today()
    prefix = f"{today.year:04d}-{today.month:02d}"
    if gtype == "workout_count":
        return sum(1 for w in load_workouts() if w["date"].startswith(prefix))
    if gtype == "expense_limit":
        return ledger_monthly_summary(today.year, today.month)["expense"]
    return goal.get("progress", 0)


def update_goal_progress(goal_id: str, progress: int):
    items = load_goals()
    for g in items:
        if g["id"] == goal_id:
            g["progress"] = max(0, min(progress, g.get("target", 100)))
            g["completed"] = g["progress"] >= g.get("target", 100)
    save_goals(items)

def delete_goal(goal_id: str):
    save_goals([g for g in load_goals() if g["id"] != goal_id])


# ════════════════════════════════════════
#  가계부
# ════════════════════════════════════════
def load_ledger(): return _load(LEDGER_FILE)
def save_ledger(items): _save(LEDGER_FILE, items)

def add_ledger(entry_type: str, category: str, amount: int, note: str = "", entry_date: str = None):
    items = load_ledger()
    items.append({"id": str(uuid.uuid4()),
                  "date": entry_date or date.today().isoformat(),
                  "type": entry_type, "category": category,
                  "amount": amount, "note": note})
    items.sort(key=lambda x: x["date"], reverse=True)
    save_ledger(items)

def delete_ledger(entry_id: str):
    save_ledger([e for e in load_ledger() if e["id"] != entry_id])

def ledger_monthly_summary(year: int, month: int) -> dict:
    items = load_ledger()
    prefix = f"{year:04d}-{month:02d}"
    income = sum(e["amount"] for e in items if e["date"].startswith(prefix) and e["type"] == "income")
    expense = sum(e["amount"] for e in items if e["date"].startswith(prefix) and e["type"] == "expense")
    return {"income": income, "expense": expense, "net": income - expense}


# ════════════════════════════════════════
#  독서 기록
# ════════════════════════════════════════
def load_books(): return _load(BOOKS_FILE)
def save_books(items): _save(BOOKS_FILE, items)

def add_book(title: str, author: str = "", status: str = "want"):
    items = load_books()
    items.append({"id": str(uuid.uuid4()), "title": title, "author": author,
                  "status": status, "rating": 0, "note": "",
                  "added_at": date.today().isoformat(), "finished_at": None})
    save_books(items)

def update_book(book_id: str, **kwargs):
    items = load_books()
    for b in items:
        if b["id"] == book_id:
            b.update(kwargs)
            if kwargs.get("status") == "done" and not b.get("finished_at"):
                b["finished_at"] = date.today().isoformat()
    save_books(items)

def delete_book(book_id: str):
    save_books([b for b in load_books() if b["id"] != book_id])


# ════════════════════════════════════════
#  운동 기록
# ════════════════════════════════════════
def load_workouts(): return _load(WORKOUTS_FILE)
def save_workouts(items): _save(WORKOUTS_FILE, items)

def add_workout(workout_type: str, duration: int, note: str = "", workout_date: str = None):
    items = load_workouts()
    items.append({"id": str(uuid.uuid4()),
                  "date": workout_date or date.today().isoformat(),
                  "type": workout_type, "duration": duration, "note": note})
    items.sort(key=lambda x: x["date"], reverse=True)
    save_workouts(items)

def delete_workout(workout_id: str):
    save_workouts([w for w in load_workouts() if w["id"] != workout_id])

# ════════════════════════════════════════
#  기분 / 일기
# ════════════════════════════════════════
def load_mood(): return _load(MOOD_FILE)
def save_mood(items): _save(MOOD_FILE, items)

def add_mood(score: int, note: str = ""):
    items = load_mood()
    today = date.today().isoformat()
    items = [m for m in items if m["date"] != today]   # 오늘 것 교체
    items.append({"id": str(uuid.uuid4()), "date": today,
                  "score": score, "emoji": MOOD_EMOJIS[score - 1], "note": note})
    items.sort(key=lambda x: x["date"], reverse=True)
    save_mood(items)

def delete_mood(mood_id: str):
    save_mood([m for m in load_mood() if m["id"] != mood_id])


# ════════════════════════════════════════
#  링크 저장함
# ════════════════════════════════════════
def load_links(): return _load(LINKS_FILE)
def save_links(items): _save(LINKS_FILE, items)

def add_link(url: str, title: str, category: str, note: str = ""):
    items = load_links()
    items.append({"id": str(uuid.uuid4()), "url": url,
                  "title": title or url, "category": category,
                  "note": note, "created_at": date.today().isoformat()})
    save_links(items)

def delete_link(link_id: str):
    save_links([lk for lk in load_links() if lk["id"] != link_id])


# ════════════════════════════════════════
#  수면 기록
# ════════════════════════════════════════
def load_sleep(): return _load(SLEEP_FILE)
def save_sleep(items): _save(SLEEP_FILE, items)

def add_sleep(sleep_date: str, bedtime: str, wakeup: str, quality: int, note: str = ""):
    bed_dt  = datetime.strptime(f"{sleep_date} {bedtime}", "%Y-%m-%d %H:%M")
    if wakeup > bedtime:
        wake_date = sleep_date
    else:
        wake_date = (date.fromisoformat(sleep_date) + timedelta(days=1)).isoformat()
    wake_dt = datetime.strptime(f"{wake_date} {wakeup}", "%Y-%m-%d %H:%M")
    dur = round((wake_dt - bed_dt).total_seconds() / 3600, 1)
    items = load_sleep()
    items = [s for s in items if s["date"] != sleep_date]  # 같은 날 교체
    items.append({"id": str(uuid.uuid4()), "date": sleep_date,
                  "bedtime": bedtime, "wakeup": wakeup,
                  "duration": dur, "quality": quality, "note": note})
    items.sort(key=lambda x: x["date"], reverse=True)
    save_sleep(items)

def delete_sleep_entry(sleep_id: str):
    save_sleep([s for s in load_sleep() if s["id"] != sleep_id])


# ════════════════════════════════════════
#  복약 알림
# ════════════════════════════════════════
def load_meds(): return _load(MEDS_FILE)
def save_meds(items): _save(MEDS_FILE, items)

def add_med(name: str, times: list, note: str = ""):
    items = load_meds()
    items.append({"id": str(uuid.uuid4()), "name": name,
                  "times": times, "enabled": True, "note": note})
    save_meds(items)

def toggle_med(med_id: str):
    items = load_meds()
    for m in items:
        if m["id"] == med_id:
            m["enabled"] = not m["enabled"]
    save_meds(items)

def delete_med(med_id: str):
    save_meds([m for m in load_meds() if m["id"] != med_id])


def workout_week_summary() -> dict:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_dates = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    items = [w for w in load_workouts() if w["date"] in week_dates]
    return {"count": len(items), "total_min": sum(w["duration"] for w in items), "items": items}


# ════════════════════════════════════════
#  백업 / 복원
# ════════════════════════════════════════
def export_all_data() -> dict:
    return {
        "version": 3,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "schedules": load_schedules(),
        "memos": load_memos(),
        "todos": load_todos(),
        "settings": load_settings(),
        "chat_history": load_chat_history(),
        "habits": load_habits(),
        "goals": load_goals(),
        "ledger": load_ledger(),
        "books": load_books(),
        "workouts": load_workouts(),
        "mood": load_mood(),
        "links": load_links(),
        "sleep": load_sleep(),
        "medications": load_meds(),
    }


def import_all_data(data: dict):
    if "schedules" in data and isinstance(data["schedules"], list):
        save_schedules(data["schedules"])
    if "memos" in data and isinstance(data["memos"], list):
        save_memos(data["memos"])
    if "todos" in data and isinstance(data["todos"], list):
        save_todos(data["todos"])
    if "settings" in data and isinstance(data["settings"], dict):
        save_settings(data["settings"])
    if "chat_history" in data and isinstance(data["chat_history"], list):
        save_chat_history(data["chat_history"])
    if "habits" in data and isinstance(data["habits"], list):
        save_habits(data["habits"])
    if "goals" in data and isinstance(data["goals"], list):
        save_goals(data["goals"])
    if "ledger" in data and isinstance(data["ledger"], list):
        save_ledger(data["ledger"])
    if "books" in data and isinstance(data["books"], list):
        save_books(data["books"])
    if "workouts" in data and isinstance(data["workouts"], list):
        save_workouts(data["workouts"])
    if "mood" in data and isinstance(data["mood"], list):
        save_mood(data["mood"])
    if "links" in data and isinstance(data["links"], list):
        save_links(data["links"])
    if "sleep" in data and isinstance(data["sleep"], list):
        save_sleep(data["sleep"])
    if "medications" in data and isinstance(data["medications"], list):
        save_meds(data["medications"])


# ════════════════════════════════════════
#  텍스트 변환 (AI 컨텍스트)
# ════════════════════════════════════════
def schedules_as_text():
    items = load_schedules()
    if not items:
        return "(저장된 일정 없음)"
    lines = []
    for s in items:
        rec = RECURRENCE_LABEL.get(s.get("recurrence", "none"), "")
        line = f"- {s['datetime']} | {s['title']}"
        if rec:
            line += f" ({rec})"
        if s.get("note"):
            line += f" — {s['note']}"
        lines.append(line)
    return "\n".join(lines)


def memos_as_text():
    items = load_memos()
    if not items:
        return "(저장된 메모 없음)"
    return "\n".join(
        f"- [{m['created_at']}] {m['title']}: {m['content']}" for m in items
    )


def todos_as_text():
    items = load_todos()
    if not items:
        return "(저장된 할 일 없음)"
    return "\n".join(
        f"- {'[완료]' if t['completed'] else '[대기]'} {t['title']}" for t in items
    )


# ════════════════════════════════════════
#  Gemini 도구
# ════════════════════════════════════════
def tool_add_schedule(datetime_iso: str, title: str, note: str = "", recurrence: str = "none") -> str:
    """사용자의 일정을 추가합니다. 새 약속/일정을 만들 때 호출하세요.

    Args:
        datetime_iso: ISO 8601 시각. 예: '2026-05-14T15:00'.
        title: 일정 제목.
        note: 추가 메모 (선택).
        recurrence: 반복 주기. "none"(기본), "daily"(매일), "weekly"(매주), "monthly"(매월).
    """
    try:
        when = datetime.fromisoformat(datetime_iso)
    except ValueError:
        return f"날짜 형식 오류: '{datetime_iso}'. 'YYYY-MM-DDTHH:MM' 형식이어야 합니다."
    if recurrence not in ("none", "daily", "weekly", "monthly"):
        recurrence = "none"
    add_schedule(when, title, note or "", recurrence)
    rec_label = f" ({RECURRENCE_LABEL[recurrence]})" if recurrence != "none" else ""
    return f"일정 '{title}'{rec_label}이(가) {datetime_iso}에 추가되었습니다."


def tool_add_memo(title: str, content: str = "") -> str:
    """사용자의 메모를 추가합니다. 정보를 저장하고 싶을 때 호출하세요.

    Args:
        title: 메모 제목.
        content: 메모 본문 (선택).
    """
    add_memo(title, content or "")
    return f"메모 '{title}'이(가) 추가되었습니다."


def tool_add_todo(title: str) -> str:
    """할 일(체크박스)을 추가합니다. 시간이 없는 단순 To-Do에 사용. 시간이 있으면 tool_add_schedule.

    Args:
        title: 할 일 내용.
    """
    add_todo(title)
    return f"할 일 '{title}'이(가) 추가되었습니다."


def tool_complete_todo(title_keyword: str) -> str:
    """할 일을 완료로 표시합니다. "X 다 했어"라고 말할 때 호출.

    Args:
        title_keyword: 할 일 제목에 포함된 단어 (부분 일치).
    """
    items = load_todos()
    matched = [t for t in items if title_keyword in t["title"] and not t["completed"]]
    if not matched:
        return f"'{title_keyword}'을(를) 포함하는 미완료 할 일이 없습니다."
    for t in matched:
        toggle_todo(t["id"])
    return f"할 일 {len(matched)}개 완료 처리: {', '.join(t['title'] for t in matched)}"


def tool_log_workout(workout_type: str, duration_min: int, note: str = "") -> str:
    """운동을 기록합니다. '오늘 달리기 30분 했어', '헬스 1시간 했어' 같을 때 호출.

    Args:
        workout_type: 운동 종류. '달리기','걷기','헬스','수영','자전거','요가','필라테스','등산','기타' 중 하나.
        duration_min: 운동 시간 (분). 예: 30, 60.
        note: 추가 메모 (선택).
    """
    add_workout(workout_type, duration_min, note)
    return f"운동 '{workout_type}' {duration_min}분이 기록되었습니다."


def tool_log_sleep(hours: float, quality: int = 3, note: str = "") -> str:
    """수면을 기록합니다. '어젯밤 7시간 잤어', '오늘 수면 별로였어' 같을 때 호출.

    Args:
        hours: 수면 시간 (시간). 예: 7.5.
        quality: 수면 질 1~5 (1:최악, 3:보통, 5:최고). 기본값 3.
        note: 추가 메모 (선택).
    """
    today = date.today().isoformat()
    now_dt = datetime.now()
    wakeup_dt = now_dt
    bedtime_dt = wakeup_dt - timedelta(hours=hours)
    items = load_sleep()
    items = [s for s in items if s.get("date") != today]
    items.append({
        "id": str(uuid.uuid4()),
        "date": today,
        "bedtime": bedtime_dt.strftime("%H:%M"),
        "wakeup": wakeup_dt.strftime("%H:%M"),
        "duration": round(hours, 1),
        "quality": max(1, min(5, quality)),
        "note": note,
    })
    items.sort(key=lambda x: x["date"], reverse=True)
    save_sleep(items)
    return f"수면 {hours}시간 (수면질 {quality}/5)이 기록되었습니다."


def tool_log_mood(score: int, note: str = "") -> str:
    """오늘의 기분을 기록합니다. '오늘 기분 좋아', '기분 최고야', '기분 별로야' 같을 때 호출.

    Args:
        score: 기분 점수 1~5 (1:별로, 2:조금별로, 3:보통, 4:좋음, 5:최고).
        note: 일기/메모 (선택).
    """
    score = max(1, min(5, score))
    add_mood(score, note)
    return f"오늘 기분 {MOOD_EMOJIS[score-1]} ({MOOD_LABELS[score-1]})이 기록되었습니다."


def tool_add_expense(amount: int, category: str = "기타", note: str = "") -> str:
    """지출을 가계부에 기록합니다. '점심 8000원 썼어', '교통비 1500원' 같을 때 호출.

    Args:
        amount: 금액 (원). 예: 8000.
        category: 카테고리. '식비','교통','쇼핑','의료','문화','교육','기타' 중 하나.
        note: 내용 (선택).
    """
    add_ledger("expense", category, amount, note)
    return f"지출 {amount:,}원 ({category})이 기록되었습니다."


def tool_add_income(amount: int, category: str = "기타", note: str = "") -> str:
    """수입을 가계부에 기록합니다. '월급 받았어', '용돈 10만원 받았어' 같을 때 호출.

    Args:
        amount: 금액 (원). 예: 100000.
        category: 카테고리. '급여','용돈','부수입','기타' 중 하나.
        note: 내용 (선택).
    """
    add_ledger("income", category, amount, note)
    return f"수입 {amount:,}원 ({category})이 기록되었습니다."


def tool_check_habit(habit_name_keyword: str) -> str:
    """오늘의 습관을 완료 체크합니다. '물 마시기 했어', '운동 습관 완료' 같을 때 호출.

    Args:
        habit_name_keyword: 습관 이름에 포함된 단어 (부분 일치).
    """
    items = load_habits()
    today = date.today().isoformat()
    matched = [h for h in items if habit_name_keyword in h["name"]]
    if not matched:
        return f"'{habit_name_keyword}'을(를) 포함하는 습관이 없습니다."
    results = []
    for h in matched:
        already = today in h.get("check_dates", [])
        toggle_habit(h["id"], today)
        results.append(f"'{h['name']}' {'체크 취소' if already else '완료 체크'}")
    return ", ".join(results) + "되었습니다."


def tool_get_today_summary() -> str:
    """오늘의 전체 현황 요약을 반환합니다. '오늘 뭐 했어?', '오늘 현황 알려줘' 같을 때 호출."""
    today = date.today().isoformat()
    schedules = [s for s in load_schedules() if s["datetime"][:10] == today]
    sch_text = "\n".join(f"  - {s['datetime'][11:16]} {s['title']}" for s in schedules) or "  없음"
    todos_undone = [t for t in load_todos() if not t["completed"]]
    todo_text = "\n".join(f"  - {t['title']}" for t in todos_undone[:5]) or "  없음"
    workouts = [w for w in load_workouts() if w["date"] == today]
    workout_text = "\n".join(f"  - {w['type']} {w['duration']}분" for w in workouts) or "  없음"
    moods = [m for m in load_mood() if m["date"] == today]
    mood_text = f"{moods[0]['emoji']} {MOOD_LABELS[moods[0]['score']-1]}" if moods else "  미기록"
    expenses = [l for l in load_ledger() if l["date"] == today and l["type"] == "expense"]
    expense_text = f"  {sum(l['amount'] for l in expenses):,}원" if expenses else "  없음"
    habits = load_habits()
    checked = sum(1 for h in habits if today in h.get("check_dates", []))
    habit_text = f"  {checked}/{len(habits)}개 완료" if habits else "  없음"
    return (f"📅 오늘 일정:\n{sch_text}\n"
            f"✅ 미완료 할 일:\n{todo_text}\n"
            f"🏃 오늘 운동:\n{workout_text}\n"
            f"😊 오늘 기분: {mood_text}\n"
            f"💰 오늘 지출:{expense_text}\n"
            f"🔁 습관:{habit_text}")


GEMINI_TOOLS = [
    tool_add_schedule, tool_add_memo, tool_add_todo, tool_complete_todo,
    tool_log_workout, tool_log_sleep, tool_log_mood,
    tool_add_expense, tool_add_income,
    tool_check_habit, tool_get_today_summary,
]


# ════════════════════════════════════════
#  Gemini 호출
# ════════════════════════════════════════
def ask_gemini(session_messages: list, system_instruction: str,
               image_data: bytes = None, image_mime: str = "image/jpeg") -> str:
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=GEMINI_TOOLS,
    )
    # contents 구성 (마지막 user 메시지에만 이미지 첨부 가능)
    gemini_contents = []
    for i, msg in enumerate(session_messages):
        role = "model" if msg["role"] == "assistant" else "user"
        is_last_user = (i == len(session_messages) - 1 and role == "user")
        if is_last_user and image_data:
            parts = [
                {"inline_data": {"mime_type": image_mime,
                                 "data": base64.b64encode(image_data).decode()}},
                {"text": msg["content"]},
            ]
        else:
            parts = [{"text": msg["content"]}]
        gemini_contents.append({"role": role, "parts": parts})

    last_error = None
    for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        for _ in range(2):
            try:
                resp = client.models.generate_content(
                    model=model, contents=gemini_contents, config=config
                )
                return resp.text or "처리했어요."
            except genai_errors.ServerError as e:
                last_error = e
                time_module.sleep(1.5)
            except genai_errors.ClientError as e:
                last_error = e
                break
    raise last_error


# ════════════════════════════════════════
#  음성 입력 처리
# ════════════════════════════════════════
def ask_gemini_voice(audio_bytes: bytes, audio_mime: str = "audio/webm") -> tuple:
    """음성 → (인식된 텍스트, 답변) 반환"""
    now = datetime.now()
    system = (
        f"너는 사용자의 개인 비서야. "
        f"오늘은 {now.strftime('%Y년 %m월 %d일')}, 지금 시각은 {now.strftime('%H:%M')}이야.\n\n"
        f"[현재 일정]\n{schedules_as_text()}\n\n"
        f"[현재 할 일]\n{todos_as_text()}\n\n"
        f"[현재 메모]\n{memos_as_text()}\n\n"
        "음성 메시지를 받았어. 음성을 한국어로 정확히 인식한 뒤,\n"
        "반드시 첫 줄을 '🎤 인식: \"[인식된 텍스트]\"' 형식으로 시작하고,\n"
        "빈 줄 하나 띄고 개인 비서로서 적절히 답변해.\n"
        "일정/메모/할일 추가 요청이 있으면 도구를 호출해서 저장해.\n"
        "단순 질문이면 도구 없이 한국어로 답해."
    )
    contents = [{
        "role": "user",
        "parts": [
            {"inline_data": {
                "mime_type": audio_mime,
                "data": base64.b64encode(audio_bytes).decode()
            }},
            {"text": "음성 메시지입니다. 인식하고 답변해주세요."},
        ],
    }]
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=GEMINI_TOOLS,
    )
    last_err = None
    for model in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
        for _ in range(2):
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                full = resp.text or ""
                # 첫 줄에서 인식 텍스트 파싱
                lines = full.strip().split("\n")
                transcribed, answer = "", full
                if lines and lines[0].startswith("🎤 인식:"):
                    m = re.search(r'["\"](.+?)["\"]', lines[0])
                    transcribed = m.group(1) if m else lines[0].replace("🎤 인식:", "").strip(' "')
                    answer = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
                    answer = answer or "네, 처리했어요!"
                else:
                    transcribed = "(음성 메시지)"
                return transcribed, answer
            except genai_errors.ServerError as e:
                last_err = e
                time_module.sleep(1.5)
            except genai_errors.ClientError as e:
                last_err = e
                break
    raise last_err


# ════════════════════════════════════════
#  텔레그램 알림
# ════════════════════════════════════════
def send_telegram(message: str) -> bool:
    cfg = load_settings()
    token   = cfg.get("telegram_token", "").strip()
    chat_id = cfg.get("telegram_chat_id", "").strip()
    if not token or not chat_id:
        return False
    try:
        body = json.dumps({"chat_id": chat_id, "text": message}).encode()
        req  = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
        return True
    except Exception:
        return False


# ════════════════════════════════════════
#  5일 날씨 예보
# ════════════════════════════════════════
@st.cache_data(ttl=1800)
def fetch_weather_forecast() -> list:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
        "&timezone=Asia%2FSeoul&forecast_days=6"
    )
    try:
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        daily = data.get("daily", {})
        result = []
        for i in range(1, 6):  # 내일~5일 후
            result.append({
                "date":     daily["time"][i],
                "temp_max": round(daily["temperature_2m_max"][i]),
                "temp_min": round(daily["temperature_2m_min"][i]),
                "precip":   round(daily["precipitation_sum"][i], 1),
                "code":     daily["weather_code"][i],
            })
        return result
    except Exception:
        return []


# ════════════════════════════════════════
#  뉴스 피드 (Google News RSS)
# ════════════════════════════════════════
def fetch_news(keywords: list, max_per: int = 5) -> list:
    results = []
    for kw in keywords[:4]:
        enc_kw = urllib.parse.quote(kw)
        url = f"https://news.google.com/rss/search?q={enc_kw}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                content = resp.read()
            root    = ET.fromstring(content)
            channel = root.find("channel")
            items   = channel.findall("item") if channel else []
            for item in items[:max_per]:
                title    = item.findtext("title", "").split(" - ")[0].strip()
                link     = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")[:16]
                results.append({"keyword": kw, "title": title,
                                 "link": link, "pub_date": pub_date})
        except Exception:
            continue
    return results


# ════════════════════════════════════════
#  URL / 유튜브 요약
# ════════════════════════════════════════
def fetch_and_summarize_url(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"❌ URL 접근 실패: {e}"
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>",  " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()[:6000]
    if not text.strip():
        return "❌ 페이지 내용을 읽을 수 없어요."
    prompt = (
        f"다음 웹페이지 내용을 한국어로 5줄 이내로 핵심만 요약해줘:\n\n{text}"
    )
    cfg = types.GenerateContentConfig(
        system_instruction="당신은 웹 콘텐츠 요약 전문가입니다. 핵심만 간결하게 답하세요."
    )
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
        config=cfg,
    )
    return resp.text or "요약 실패"


# ════════════════════════════════════════
#  번역
# ════════════════════════════════════════
def translate_text(text: str, target_lang: str) -> str:
    prompt = f"다음 텍스트를 {target_lang}로 번역해줘. 번역 결과만 출력해:\n\n{text}"
    cfg = types.GenerateContentConfig(
        system_instruction="당신은 전문 번역가입니다. 번역 결과만 출력하세요."
    )
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
        config=cfg,
    )
    return resp.text or "번역 실패"


# ════════════════════════════════════════
#  AI 일정 제안
# ════════════════════════════════════════
def suggest_schedule() -> str:
    now   = datetime.now()
    today = date.today()
    upcoming  = get_upcoming_occurrences(within_days=7)
    todos_p   = [t for t in load_todos() if not t["completed"]]
    goals_a   = [g for g in load_goals() if not g.get("completed")]

    sched_txt = "\n".join(
        f"- {occ.strftime('%m/%d %H:%M')} {s['title']}" for s, occ in upcoming[:10]
    ) or "없음"
    todo_txt  = "\n".join(
        f"- [{TODO_PRIORITY.get(t.get('priority','medium'),'보통')}] {t['title']}"
        for t in todos_p[:10]
    ) or "없음"
    goal_txt  = "\n".join(
        f"- {g['title']} ({int(g['progress']/g.get('target',100)*100)}%)"
        for g in goals_a[:5]
    ) or "없음"

    prompt = (
        f"오늘은 {today.strftime('%Y년 %m월 %d일')}, 지금 {now.strftime('%H:%M')}이야.\n\n"
        f"[이번 주 일정]\n{sched_txt}\n\n"
        f"[미완료 할일]\n{todo_txt}\n\n"
        f"[진행 중 목표]\n{goal_txt}\n\n"
        "위 정보 바탕으로:\n"
        "1. 🎯 오늘 집중해야 할 일 TOP 3\n"
        "2. 📅 이번 주 일정을 고려한 시간 활용 팁\n"
        "3. 💡 목표 달성을 위한 오늘의 작은 행동 1가지\n"
        "를 친근하고 구체적으로 한국어로 알려줘."
    )
    cfg = types.GenerateContentConfig(
        system_instruction="당신은 개인 생산성 코치입니다. 따뜻하고 실용적으로 조언하세요."
    )
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
        config=cfg,
    )
    return resp.text or "제안 실패"


# ════════════════════════════════════════
#  AI 패턴 분석
# ════════════════════════════════════════
def generate_ai_analysis() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_dates = [(monday + timedelta(days=i)).isoformat() for i in range(7)]

    habits = load_habits()
    habit_stats = "\n".join(
        f"- {h['name']}: {sum(1 for d in week_dates if d in h.get('check_dates',[]))}/7일"
        for h in habits
    ) or "없음"

    w_sum = workout_week_summary()
    mood_recent = load_mood()[:7]
    mood_txt = "\n".join(
        f"- {m['date']}: {m['emoji']} {MOOD_LABELS[m['score']-1]}"
        + (f" ({m['note']})" if m.get("note") else "")
        for m in mood_recent
    ) or "기록 없음"

    sleep_recent = load_sleep()[:7]
    sleep_txt = "\n".join(
        f"- {s['date']}: {s['duration']}시간 (취침 {s['bedtime']} → 기상 {s['wakeup']}, 만족도 {s['quality']}/5)"
        for s in sleep_recent
    ) or "기록 없음"

    ml = ledger_monthly_summary(today.year, today.month)
    goals = [g for g in load_goals() if not g.get("completed")]
    goals_txt = "\n".join(
        f"- {g['title']}: {g['progress']}/{g.get('target',100)} ({int(g['progress']/g.get('target',100)*100)}%)"
        for g in goals
    ) or "없음"

    todos_pending = [t for t in load_todos() if not t["completed"]]

    data_summary = f"""오늘: {today.strftime('%Y년 %m월 %d일')}

[이번 주 습관 달성]
{habit_stats}

[이번 주 운동]
총 {w_sum['count']}회, {w_sum['total_min']}분

[최근 기분]
{mood_txt}

[최근 수면]
{sleep_txt}

[이번 달 가계부]
수입 {ml['income']:,}원 / 지출 {ml['expense']:,}원 / 잔액 {ml['net']:+,}원

[진행 중 목표]
{goals_txt}

[남은 할 일]
{len(todos_pending)}개"""

    prompt = (
        "당신은 따뜻하고 친근한 개인 AI 비서입니다.\n"
        "아래 사용자의 데이터를 분석해서 다음 3가지를 한국어로 알려주세요:\n"
        "1. 🌟 잘하고 있는 점 (구체적으로 칭찬)\n"
        "2. 💡 개선하면 좋을 점\n"
        "3. 🎯 이번 주 추천 행동 3가지\n\n"
        f"{data_summary}"
    )
    cfg = types.GenerateContentConfig(
        system_instruction="당신은 따뜻하고 친근한 개인 AI 비서입니다. 항상 한국어로 답하세요."
    )
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
        config=cfg,
    )
    return resp.text or "분석 결과를 가져올 수 없었어요."


# ════════════════════════════════════════
#  교차 분석 인사이트
# ════════════════════════════════════════
def get_daily_data(days: int = 30) -> list:
    """최근 N일 데이터를 날짜별로 통합"""
    today = date.today()
    sleep_map  = {s["date"]: s for s in load_sleep()}
    mood_map   = {m["date"]: m for m in load_mood()}
    workout_map, expense_map = {}, {}
    for w in load_workouts():
        workout_map.setdefault(w["date"], []).append(w)
    for l in load_ledger():
        if l["type"] == "expense":
            expense_map[l["date"]] = expense_map.get(l["date"], 0) + l["amount"]
    result = []
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        result.append({
            "date": d,
            "sleep_hours":   sleep_map.get(d, {}).get("duration"),
            "sleep_quality": sleep_map.get(d, {}).get("quality"),
            "mood_score":    mood_map.get(d, {}).get("score"),
            "workout_min":   sum(w["duration"] for w in workout_map.get(d, [])),
            "expense":       expense_map.get(d, 0),
        })
    return result


def calculate_cross_insights(daily: list) -> list:
    """교차 분석 인사이트 리스트 반환"""
    insights = []

    # 1. 수면 → 기분
    good_s = [d["mood_score"] for d in daily if d["sleep_hours"] and d["sleep_hours"] >= 7 and d["mood_score"]]
    bad_s  = [d["mood_score"] for d in daily if d["sleep_hours"] and d["sleep_hours"] < 6  and d["mood_score"]]
    if good_s and bad_s:
        ga, ba = sum(good_s)/len(good_s), sum(bad_s)/len(bad_s)
        if abs(ga - ba) >= 0.4:
            diff = ga - ba
            insights.append({
                "icon": "🌙", "title": "수면 → 기분 상관관계",
                "body": f"7시간↑ 수면 시 기분 평균 **{ga:.1f}/5**\n6시간↓ 수면 시 기분 평균 **{ba:.1f}/5**",
                "tip":  f"충분한 수면이 기분을 {abs(diff):.1f}점 높여줘요!" if diff > 0 else f"수면 부족이 기분을 {abs(diff):.1f}점 낮춰요.",
                "good": diff > 0,
            })

    # 2. 기분 → 지출
    good_m = [d["expense"] for d in daily if d["mood_score"] and d["mood_score"] >= 4 and d["expense"] > 0]
    bad_m  = [d["expense"] for d in daily if d["mood_score"] and d["mood_score"] <= 2 and d["expense"] > 0]
    if good_m and bad_m:
        ga, ba = sum(good_m)/len(good_m), sum(bad_m)/len(bad_m)
        if ba > ga * 1.15:
            insights.append({
                "icon": "💸", "title": "감정적 소비 패턴",
                "body": f"기분 좋은 날 평균 지출 **{ga:,.0f}원**\n기분 나쁜 날 평균 지출 **{ba:,.0f}원**",
                "tip":  "기분이 안 좋을 때 지출이 늘어요. 충동구매 주의!",
                "good": False,
            })

    # 3. 운동 → 기분
    w_m  = [d["mood_score"] for d in daily if d["workout_min"] > 0 and d["mood_score"]]
    nw_m = [d["mood_score"] for d in daily if d["workout_min"] == 0 and d["mood_score"]]
    if w_m and nw_m:
        wa, nwa = sum(w_m)/len(w_m), sum(nw_m)/len(nw_m)
        if abs(wa - nwa) >= 0.3:
            diff = wa - nwa
            insights.append({
                "icon": "🏃", "title": "운동 → 기분 상관관계",
                "body": f"운동한 날 기분 평균 **{wa:.1f}/5**\n운동 안 한 날 기분 평균 **{nwa:.1f}/5**",
                "tip":  f"운동하면 기분이 {abs(diff):.1f}점 올라가요! 꾸준히 해봐요." if diff > 0 else "운동이 기분에 별 영향 없는 편이에요.",
                "good": diff > 0,
            })

    # 4. 수면 → 지출
    good_sl = [d["expense"] for d in daily if d["sleep_hours"] and d["sleep_hours"] >= 7 and d["expense"] > 0]
    bad_sl  = [d["expense"] for d in daily if d["sleep_hours"] and d["sleep_hours"] < 6  and d["expense"] > 0]
    if good_sl and bad_sl:
        ga, ba = sum(good_sl)/len(good_sl), sum(bad_sl)/len(bad_sl)
        if ba > ga * 1.2:
            insights.append({
                "icon": "😴", "title": "수면 부족 → 지출 증가",
                "body": f"잘 잔 날 평균 지출 **{ga:,.0f}원**\n못 잔 날 평균 지출 **{ba:,.0f}원**",
                "tip":  "수면 부족이 지출을 늘려요. 푹 자면 돈도 아껴요!",
                "good": False,
            })

    # 5. 요일별 지출 패턴
    wd_exp = {i: [] for i in range(7)}
    for d in daily:
        if d["expense"] > 0:
            wd_exp[date.fromisoformat(d["date"]).weekday()].append(d["expense"])
    wd_avg = {i: sum(v)/len(v) for i, v in wd_exp.items() if v}
    if len(wd_avg) >= 3:
        day_names = ["월","화","수","목","금","토","일"]
        max_d = max(wd_avg, key=wd_avg.get)
        min_d = min(wd_avg, key=wd_avg.get)
        insights.append({
            "icon": "📅", "title": "요일별 소비 패턴",
            "body": f"가장 많이 쓰는 날: **{day_names[max_d]}요일** ({wd_avg[max_d]:,.0f}원)\n가장 적게 쓰는 날: **{day_names[min_d]}요일** ({wd_avg[min_d]:,.0f}원)",
            "tip":  f"{day_names[max_d]}요일에 소비가 집중돼요. 미리 예산을 정해두면 좋아요!",
            "good": None,
        })

    return insights


def generate_cross_narrative(insights: list) -> str:
    """교차 분석 결과를 AI가 종합해서 한 문단으로 설명"""
    if not insights:
        return "데이터가 더 쌓이면 인사이트를 분석해드릴게요! (최소 7일 이상 기록 필요)"
    summary = "\n".join(f"- {ins['icon']} {ins['title']}: {ins['body'].replace('**','')}\n  팁: {ins['tip']}" for ins in insights)
    prompt = (
        "다음은 사용자의 생활 패턴 교차 분석 결과야.\n\n"
        f"{summary}\n\n"
        "이 데이터를 바탕으로 따뜻하고 친근한 말투로 3~4문장 한국어 종합 코멘트를 써줘. "
        "구체적인 수치를 활용해서 실용적인 조언도 포함해줘."
    )
    cfg = types.GenerateContentConfig(system_instruction="친근한 개인 AI 비서. 항상 한국어로 답해.")
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            config=cfg,
        )
        return resp.text or ""
    except Exception:
        return ""


# ════════════════════════════════════════
#  영수증 자동 분석
# ════════════════════════════════════════
def analyze_receipt(image_bytes: bytes, mime_type: str) -> dict:
    """영수증/결제 내역 사진을 Gemini Vision으로 분석해서 지출 항목 반환"""
    today_str = date.today().isoformat()
    prompt = (
        "이 영수증(또는 결제 내역 사진)을 분석해서 다음 JSON 형식으로만 응답하세요:\n"
        f'{{"store":"가게명","date":"{today_str}","items":['
        f'{{"name":"항목명","amount":금액정수,"category":"식비/교통/쇼핑/의료/문화/교육/기타 중 하나"}}],"total":총금액정수}}\n'
        "날짜가 보이면 YYYY-MM-DD 형식으로. 숫자는 원 단위 정수. JSON만 응답, 설명 없이."
    )
    img_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    cfg = types.GenerateContentConfig(system_instruction="영수증 분석 전문가. JSON만 응답.")
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt, img_part],
        config=cfg,
    )
    text = resp.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)


# ════════════════════════════════════════
#  알림
# ════════════════════════════════════════
def upcoming_for_reminder(within_minutes: int):
    now = datetime.now()
    cutoff = now + timedelta(minutes=within_minutes)
    result = []
    for s in load_schedules():
        for occ in expand_schedule_in_range(s, now, cutoff):
            result.append((s, occ, occ - now))
    return result


def _show_toast_powershell(title: str, message: str) -> bool:
    safe_t = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_m = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType = WindowsRuntime] | Out-Null;"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$xml.LoadXml('<toast><visual><binding template=\"ToastText02\">"
        f"<text id=\"1\">{safe_t}</text><text id=\"2\">{safe_m}</text>"
        f"</binding></visual></toast>');"
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml;"
        "[Windows.UI.Notifications.ToastNotificationManager]"
        "::CreateToastNotifier('PowerShell').Show($toast)"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def show_toast(title: str, message: str) -> bool:
    if HAS_TOAST:
        try:
            Notification(app_id="내 AI 비서", title=title, msg=message).show()
            return True
        except Exception:
            pass
    return _show_toast_powershell(title, message)


# ════════════════════════════════════════
#  CSS
# ════════════════════════════════════════
def build_css(dark: bool) -> str:
    if dark:
        c = {
            "bg": "#191919", "text": "#e8e8e6", "text_secondary": "#9b9b97",
            "sidebar_bg": "#202020", "border": "#373737", "card_bg": "#2a2a2a",
            "input_bg": "#252525", "hover": "#2f2f2f",
            "banner_bg": "#3a2e10", "banner_border": "#7a5a15", "banner_text": "#fcd34d",
            "button_bg": "#2a2a2a", "primary": "#2383e2", "primary_hover": "#1a6dbf",
        }
    else:
        c = {
            "bg": "#ffffff", "text": "#37352f", "text_secondary": "#787774",
            "sidebar_bg": "#fbfbfa", "border": "#e9e9e7", "card_bg": "#f7f7f5",
            "input_bg": "#f7f7f5", "hover": "#efefed",
            "banner_bg": "#fff8e1", "banner_border": "#ffe082", "banner_text": "#5d4500",
            "button_bg": "#ffffff", "primary": "#2383e2", "primary_hover": "#1a6dbf",
        }
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html,body,[class*="css"],.stApp,.stMarkdown,.stTextInput,.stTextArea,.stButton{{
    font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif!important;
    color:{c['text']};
}}
.stApp{{background-color:{c['bg']}!important;}}
h1,h2,h3,p,label,.stMarkdown,.stCaption{{color:{c['text']}!important;}}
h1,h2,h3{{font-weight:700!important;letter-spacing:-0.01em;}}
h1{{font-size:2rem!important;margin-bottom:0.25rem!important;}}
section[data-testid="stSidebar"]{{background-color:{c['sidebar_bg']}!important;border-right:1px solid {c['border']};}}
section[data-testid="stSidebar"] .stRadio>div{{gap:0.25rem;}}
section[data-testid="stSidebar"] .stRadio label{{
    padding:0.4rem 0.6rem;border-radius:6px;transition:background 0.1s;color:{c['text']}!important;
}}
section[data-testid="stSidebar"] .stRadio label:hover{{background:{c['hover']};}}
section[data-testid="stSidebar"] .stButton>button{{
    text-align:left!important;justify-content:flex-start!important;
    font-size:0.9rem!important;padding:0.35rem 0.6rem!important;
    border:none!important;background:transparent!important;
    color:{c['text']}!important;box-shadow:none!important;
}}
section[data-testid="stSidebar"] .stButton>button:hover{{
    background:{c['hover']}!important;
}}
section[data-testid="stSidebar"] .stExpander{{
    border:none!important;background:transparent!important;
}}
.stButton>button{{
    border-radius:6px;border:1px solid {c['border']};background:{c['button_bg']};
    color:{c['text']};font-weight:500;transition:background 0.1s;
    box-shadow:rgba(15,15,15,0.04) 0px 1px 2px;
}}
.stButton>button:hover{{background:{c['hover']};border-color:{c['border']};color:{c['text']};}}
.stButton>button[kind="primary"]{{background:{c['primary']};color:white;border:none;}}
.stButton>button[kind="primary"]:hover{{background:{c['primary_hover']};color:white;}}
.stTextInput input,.stTextArea textarea{{
    border-radius:6px!important;border:1px solid {c['border']}!important;
    background:{c['input_bg']}!important;color:{c['text']}!important;
}}
div[data-baseweb="select"]>div,div[data-baseweb="input"]>div{{
    background:{c['input_bg']}!important;border-color:{c['border']}!important;color:{c['text']}!important;
}}
.stChatMessage{{background:transparent!important;border:none!important;padding:0.5rem 0!important;}}
.stChatMessage p{{color:{c['text']}!important;}}
div[data-testid="stChatInput"]{{border-radius:8px;border:1px solid {c['border']};background:{c['input_bg']};}}
div[data-testid="stChatInput"] textarea{{color:{c['text']}!important;background:transparent!important;}}
hr{{border-color:{c['border']}!important;margin:1.5rem 0!important;}}

/* 카드 */
.item-card{{background:{c['card_bg']};border:1px solid {c['border']};border-radius:8px;padding:12px 16px;margin-bottom:8px;}}
.item-card.past{{opacity:0.55;}}
.item-meta{{color:{c['text_secondary']};font-size:0.85rem;font-weight:500;}}
.item-title{{color:{c['text']};font-weight:600;font-size:1rem;margin-top:2px;}}
.item-body{{color:{c['text']};font-size:0.92rem;margin-top:6px;white-space:pre-wrap;}}
.item-note{{color:{c['text_secondary']};font-size:0.85rem;margin-top:4px;}}
.recurrence-tag{{
    display:inline-block;background:{c['primary']};color:white!important;
    font-size:0.72rem;font-weight:600;padding:1px 7px;border-radius:4px;
    margin-left:6px;vertical-align:middle;
}}

/* 알림 배너 */
.reminder-banner{{
    background:{c['banner_bg']};border:1px solid {c['banner_border']};
    border-left:4px solid #f59e0b;border-radius:8px;
    padding:10px 14px;margin-bottom:12px;color:{c['banner_text']};font-weight:500;
}}

/* 홈 */
.next-card{{
    background:linear-gradient(135deg,#2383e2 0%,#1a6dbf 100%);
    border-radius:12px;padding:20px 24px;margin-bottom:20px;
    box-shadow:0 4px 12px rgba(35,131,226,0.18);
}}
.next-card .next-label,.next-card .next-title,.next-card .next-time{{color:#ffffff!important;}}
.next-label{{font-size:0.85rem;opacity:0.9;font-weight:500;letter-spacing:0.02em;}}
.next-title{{font-size:1.5rem;font-weight:700;margin-top:4px;}}
.next-time{{font-size:0.95rem;margin-top:6px;opacity:0.95;}}
.next-card.empty{{background:{c['card_bg']};border:1px solid {c['border']};}}
.next-card.empty .next-label,.next-card.empty .next-title{{color:{c['text_secondary']}!important;}}

.today-row{{
    background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:6px;padding:10px 14px;margin-bottom:6px;
}}
.today-time{{font-weight:600;color:{c['primary']};font-size:0.9rem;}}
.today-title{{color:{c['text']};margin-top:2px;}}

.stat-card{{background:{c['card_bg']};border:1px solid {c['border']};border-radius:8px;padding:14px 16px;text-align:center;}}
.stat-num{{font-size:1.7rem;font-weight:700;color:{c['primary']};}}
.stat-label{{font-size:0.85rem;color:{c['text_secondary']};margin-top:2px;}}

/* 검색 */
.search-section-title{{color:{c['text_secondary']};font-size:0.8rem;font-weight:600;
    text-transform:uppercase;letter-spacing:0.08em;margin:16px 0 8px;}}

/* 날씨 카드 */
.weather-card{{
    background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:12px;padding:18px 20px;height:100%;
}}
.weather-location{{color:{c['text_secondary']};font-size:0.82rem;font-weight:500;}}
.weather-main{{display:flex;align-items:center;gap:8px;margin:8px 0 4px;}}
.weather-emoji{{font-size:2.2rem;line-height:1;}}
.weather-temp{{font-size:2.4rem;font-weight:700;color:{c['text']};line-height:1;}}
.weather-desc{{color:{c['text_secondary']};font-size:0.9rem;margin-bottom:10px;}}
.weather-feels{{color:{c['text_secondary']};font-size:0.82rem;}}
.weather-details{{
    display:flex;gap:12px;flex-wrap:wrap;
    margin-top:10px;padding-top:10px;border-top:1px solid {c['border']};
}}
.weather-detail-item{{color:{c['text_secondary']};font-size:0.82rem;}}
.weather-minmax{{color:{c['text']};font-size:0.85rem;font-weight:500;margin-top:4px;}}
.weather-error{{color:{c['text_secondary']};font-size:0.88rem;padding:12px 0;}}

/* 캘린더 뷰 */
.cal-table{{width:100%;border-collapse:collapse;margin-top:8px;}}
.cal-table th{{text-align:center;padding:8px 4px;font-size:0.82rem;font-weight:600;
    color:{c['text_secondary']};border-bottom:1px solid {c['border']};}}
.cal-table td{{text-align:center;padding:4px;vertical-align:top;height:70px;width:14.28%;}}
.cal-day{{border-radius:6px;padding:4px;cursor:default;height:100%;}}
.cal-day:hover{{background:{c['hover']};}}
.cal-day.today .cal-num{{background:{c['primary']};color:white!important;border-radius:50%;
    width:26px;height:26px;display:flex;align-items:center;justify-content:center;margin:0 auto 2px;}}
.cal-day.other-month .cal-num{{color:{c['text_secondary']};opacity:0.4;}}
.cal-num{{font-size:0.88rem;font-weight:500;color:{c['text']};margin-bottom:2px;}}
.cal-dot{{width:6px;height:6px;border-radius:50%;background:{c['primary']};
    display:inline-block;margin:1px;}}

/* 습관 트래커 */
.habit-row{{background:{c['card_bg']};border:1px solid {c['border']};border-radius:8px;
    padding:12px 16px;margin-bottom:8px;}}
.habit-week{{display:flex;gap:4px;margin-top:6px;}}
.habit-dot{{width:20px;height:20px;border-radius:50%;font-size:0.65rem;
    display:flex;align-items:center;justify-content:center;font-weight:600;}}
.habit-dot.done{{background:{c['primary']};color:white;}}
.habit-dot.miss{{background:{c['border']};color:{c['text_secondary']};}}
.streak-badge{{display:inline-block;background:#f59e0b;color:white;
    font-size:0.72rem;font-weight:700;padding:1px 7px;border-radius:10px;margin-left:8px;}}

/* 목표 */
.goal-card{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:14px 16px;margin-bottom:10px;}}
.goal-done{{opacity:0.6;}}
.progress-bar-bg{{background:{c['border']};border-radius:4px;height:8px;margin:8px 0;}}
.progress-bar-fill{{height:8px;border-radius:4px;background:{c['primary']};transition:width 0.3s;}}

/* 가계부 */
.income-tag{{color:#16a34a;font-weight:600;}}
.expense-tag{{color:#dc2626;font-weight:600;}}
.ledger-row{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:6px;padding:10px 14px;margin-bottom:6px;
    display:flex;justify-content:space-between;align-items:center;}}
.summary-box{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:14px;text-align:center;}}

/* 독서 */
.book-card{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:12px;margin-bottom:8px;}}
.book-status-badge{{display:inline-block;font-size:0.72rem;font-weight:600;
    padding:2px 8px;border-radius:10px;margin-bottom:4px;}}
.badge-want{{background:#e0f2fe;color:#0369a1;}}
.badge-reading{{background:#fef9c3;color:#854d0e;}}
.badge-done{{background:#dcfce7;color:#15803d;}}

/* 운동 */
.workout-row{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:6px;padding:10px 14px;margin-bottom:6px;}}

/* 포모도로 */
.pomo-display{{text-align:center;padding:30px 0;}}
.pomo-timer{{font-size:5rem;font-weight:800;letter-spacing:-2px;color:{c['text']};line-height:1;}}
.pomo-mode{{font-size:1rem;font-weight:600;color:{c['text_secondary']};margin-top:8px;}}
.pomo-session{{font-size:0.85rem;color:{c['text_secondary']};margin-top:4px;}}
.pomo-work{{color:{c['primary']};}}
.pomo-break{{color:#16a34a;}}

/* 기분 */
.mood-btn{{display:inline-flex;flex-direction:column;align-items:center;
    gap:4px;padding:12px 20px;border-radius:12px;cursor:pointer;
    border:2px solid {c['border']};background:{c['card_bg']};
    transition:all 0.15s;font-size:1.8rem;}}
.mood-btn:hover{{border-color:{c['primary']};transform:scale(1.08);}}
.mood-btn.selected{{border-color:{c['primary']};background:#e8f0fd;}}
.mood-history-item{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:10px 14px;margin-bottom:6px;
    display:flex;align-items:center;gap:12px;}}

/* 링크 */
.link-card{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:12px 16px;margin-bottom:8px;}}
.link-url{{color:{c['primary']};font-size:0.82rem;word-break:break-all;}}
.link-cat-badge{{display:inline-block;font-size:0.72rem;font-weight:600;
    padding:2px 8px;border-radius:10px;background:{c['border']};
    color:{c['text_secondary']};margin-bottom:4px;}}

/* 수면 */
.sleep-row{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:10px 14px;margin-bottom:6px;}}
.sleep-dur{{font-size:1.4rem;font-weight:700;color:#8b5cf6;}}

/* AI 분석 */
.ai-analysis{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:12px;padding:20px 24px;line-height:1.8;}}

/* 우선순위 */
.priority-high{{color:#dc2626;font-weight:700;font-size:0.78rem;}}
.priority-medium{{color:#d97706;font-weight:700;font-size:0.78rem;}}
.priority-low{{color:#16a34a;font-weight:700;font-size:0.78rem;}}

/* 태그 */
.tag-badge{{display:inline-block;font-size:0.72rem;font-weight:600;
    padding:2px 8px;border-radius:10px;margin:2px;
    background:{c['border']};color:{c['text']};}}

/* 날씨 예보 */
.forecast-card{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:10px 8px;text-align:center;}}
.forecast-day{{font-size:0.8rem;font-weight:600;color:{c['text_secondary']};}}
.forecast-emoji{{font-size:1.6rem;margin:4px 0;}}
.forecast-temp{{font-size:0.85rem;font-weight:600;color:{c['text']};}}

/* 뉴스 */
.news-card{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:10px 14px;margin-bottom:6px;}}
.news-title{{font-weight:600;color:{c['text']};font-size:0.95rem;}}
.news-meta{{font-size:0.78rem;color:{c['text_secondary']};margin-top:3px;}}
.news-kw{{display:inline-block;font-size:0.68rem;font-weight:700;
    padding:1px 6px;border-radius:8px;background:{c['primary']};
    color:white;margin-right:6px;}}

/* 번역 */
.trans-box{{background:{c['card_bg']};border:1px solid {c['border']};
    border-radius:8px;padding:16px;margin-top:8px;font-size:1rem;line-height:1.7;}}
</style>
"""


# ════════════════════════════════════════
#  Streamlit 초기화
# ════════════════════════════════════════
st.set_page_config(page_title="내 AI 비서", page_icon="🤖", layout="wide")

if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = load_settings().get("dark_mode", False)
if "page" not in st.session_state:
    st.session_state.page = "🏠 홈"
if "editing_sched_id" not in st.session_state:
    st.session_state.editing_sched_id = None
if "editing_memo_id" not in st.session_state:
    st.session_state.editing_memo_id = None
if "upload_key" not in st.session_state:
    st.session_state.upload_key = 0
if "mic_key" not in st.session_state:
    st.session_state.mic_key = 0
# 포모도로
if "pomo_running"   not in st.session_state: st.session_state.pomo_running = False
if "pomo_mode"      not in st.session_state: st.session_state.pomo_mode = "work"
if "pomo_sessions"  not in st.session_state: st.session_state.pomo_sessions = 0
if "pomo_end_wall"  not in st.session_state: st.session_state.pomo_end_wall = None
if "pomo_remaining" not in st.session_state: st.session_state.pomo_remaining = POMO_WORK_SEC
# 캘린더 뷰
if "cal_year"  not in st.session_state: st.session_state.cal_year  = date.today().year
if "cal_month" not in st.session_state: st.session_state.cal_month = date.today().month

st.markdown(build_css(st.session_state.dark_mode), unsafe_allow_html=True)

if not API_KEY:
    st.error("API 키가 설정되지 않았습니다. .env 파일에 GEMINI_API_KEY를 넣어주세요.")
    st.stop()

client = genai.Client(api_key=API_KEY)


# ════════════════════════════════════════
#  사이드바
# ════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🤖 내 AI 비서")
    st.caption("개인용 노션 스타일")
    st.write("")
    MENU = {
        "📌 메인":     ["🏠 홈", "💬 채팅", "🔍 검색"],
        "📅 일정·할일": ["📅 일정", "🗓️ 캘린더뷰", "✅ 할 일", "📝 메모"],
        "🎯 성장":     ["🔁 습관", "🎯 목표", "⏱️ 포모도로"],
        "🏃 건강":     ["🏃 운동", "🌙 수면", "😊 기분/일기", "💊 복약알림"],
        "💰 재무":     ["💰 가계부"],
        "📚 기록":     ["📚 독서", "🔗 링크"],
        "🤖 AI 도구":  ["💡 AI제안", "🤖 AI분석", "🌐 번역", "🔗 URL요약", "📰 뉴스"],
        "📊 통계":     ["📊 리포트", "📈 차트"],
        "🔗 연동":     ["🔗 구글 캘린더"],
    }

    for category, pages in MENU.items():
        is_active_cat = st.session_state.page in pages
        with st.expander(category, expanded=is_active_cat):
            for p in pages:
                is_active = st.session_state.page == p
                label = f"**{p}**" if is_active else p
                if st.button(label, key=f"nav_{p}", use_container_width=True):
                    st.session_state.page = p
                    st.rerun()
    st.write("")
    st.divider()

    page = st.session_state.page  # 현재 페이지

    # 다크모드
    new_dark = st.toggle("🌙 다크 모드", value=st.session_state.dark_mode)
    if new_dark != st.session_state.dark_mode:
        st.session_state.dark_mode = new_dark
        _s = load_settings()
        _s["dark_mode"] = new_dark
        save_settings(_s)
        st.rerun()

    # 텔레그램 설정
    with st.expander("📱 텔레그램 알림 설정"):
        _tcfg = load_settings()
        _ttoken = st.text_input("Bot Token", value=_tcfg.get("telegram_token",""),
                                type="password", placeholder="1234567:ABC...")
        _tcid   = st.text_input("Chat ID",   value=_tcfg.get("telegram_chat_id",""),
                                placeholder="숫자로 된 ID")
        if st.button("💾 텔레그램 저장", use_container_width=True, key="tg_save"):
            _tcfg["telegram_token"]   = _ttoken.strip()
            _tcfg["telegram_chat_id"] = _tcid.strip()
            save_settings(_tcfg)
            st.success("저장!")
        if st.button("📨 테스트 전송", use_container_width=True, key="tg_test"):
            ok = send_telegram("✅ 내 AI비서 텔레그램 연결 성공!")
            st.success("전송 완료!") if ok else st.error("실패 (Token/Chat ID 확인)")
        with st.expander("❓ 설정 방법"):
            st.markdown("""
1. 텔레그램에서 **@BotFather** 검색
2. `/newbot` 입력 → 이름 설정 → **Token 복사**
3. **@userinfobot** 검색 → `/start` → **Chat ID 복사**
4. 위에 붙여넣고 저장!
""")

    # 뉴스 키워드 설정
    with st.expander("📰 뉴스 키워드 설정"):
        _ncfg = load_settings()
        _kws  = ", ".join(_ncfg.get("news_keywords", ["AI", "경제"]))
        _new_kws = st.text_input("키워드 (쉼표로 구분)", value=_kws,
                                 placeholder="AI, 경제, 스포츠")
        if st.button("💾 저장", key="news_kw_save", use_container_width=True):
            kw_list = [k.strip() for k in _new_kws.split(",") if k.strip()][:4]
            _ncfg["news_keywords"] = kw_list
            save_settings(_ncfg)
            st.success("저장!")

    # 알림 설정
    with st.expander("🔔 알림 설정"):
        _cfg = load_settings()
        briefing_on = st.toggle(
            "☀️ 아침 브리핑",
            value=_cfg.get("briefing_enabled", False),
            help="매일 설정한 시각에 오늘 일정·할 일을 알림으로 보내요",
        )
        if briefing_on != _cfg.get("briefing_enabled", False):
            _cfg["briefing_enabled"] = briefing_on
            save_settings(_cfg)

        if briefing_on:
            _h, _m = map(int, _cfg.get("briefing_time", "08:00").split(":"))
            _bt = st.time_input("브리핑 시각", value=time(_h, _m), label_visibility="visible")
            if st.button("💾 시각 저장", key="save_bt", use_container_width=True):
                _cfg["briefing_time"] = _bt.strftime("%H:%M")
                save_settings(_cfg)
                st.success(f"{_bt.strftime('%H:%M')}에 저장됐어요!")

        if st.button("🔔 알림 테스트", use_container_width=True):
            ok = show_toast("알림 테스트", "이 메시지가 보이면 알림 정상 작동!")
            st.success("보냈어요!") if ok else st.error("전송 실패")

    st.write("")
    if st.button("🧹 채팅 기록 지우기", use_container_width=True):
        st.session_state.messages = []
        clear_chat_history()
        st.rerun()

    # 백업
    with st.expander("💾 백업/복원"):
        backup_json = json.dumps(export_all_data(), ensure_ascii=False, indent=2)
        st.download_button(
            "📥 백업 다운로드",
            data=backup_json.encode("utf-8"),
            file_name=f"ai-bisya-{date.today()}.json",
            mime="application/json",
            use_container_width=True,
        )
        uploaded = st.file_uploader("📤 복원 파일", type=["json"], key="backup_uploader")
        if uploaded:
            if st.button("⚠️ 복원하기 (현재 데이터 덮어씀)", use_container_width=True):
                try:
                    import_all_data(json.loads(uploaded.read().decode("utf-8")))
                    st.success("복원 완료!")
                    st.rerun()
                except Exception as e:
                    st.error(f"파일 오류: {e}")


# ════════════════════════════════════════
#  Fragment: 일정 알림 + 아침 브리핑
# ════════════════════════════════════════
@st.fragment(run_every=60)
def reminder_and_briefing():
    # ── 일정 알림
    if "notified_keys" not in st.session_state:
        st.session_state.notified_keys = set()

    max_threshold = max(REMINDER_THRESHOLDS)
    for s, occ, delta in upcoming_for_reminder(within_minutes=max_threshold):
        mins = max(1, int(delta.total_seconds() // 60))
        st.markdown(
            f'<div class="reminder-banner">⏰ <b>{mins}분 후</b> — {s["title"]}</div>',
            unsafe_allow_html=True,
        )
        for thr in REMINDER_THRESHOLDS:
            if mins <= thr:
                key = f"{s['id']}_{occ.isoformat()}_{thr}"
                if key not in st.session_state.notified_keys:
                    show_toast(
                        f"⏰ {thr}분 전 알림",
                        f"{s['title']} ({occ.strftime('%H:%M')})",
                    )
                    st.session_state.notified_keys.add(key)
                    send_telegram(f"⏰ {thr}분 전 알림\n{s['title']} ({occ.strftime('%H:%M')})")

    # ── 복약 알림
    if "notified_meds" not in st.session_state:
        st.session_state.notified_meds = set()
    current_time_str = datetime.now().strftime("%H:%M")
    today_str = date.today().isoformat()
    for med in load_meds():
        if not med.get("enabled", True):
            continue
        for t in med.get("times", []):
            key = f"{med['id']}_{today_str}_{t}"
            if current_time_str == t and key not in st.session_state.notified_meds:
                show_toast("💊 복약 시간", f"{med['name']} 먹을 시간이에요!")
                st.session_state.notified_meds.add(key)

    # ── 아침 브리핑
    cfg = load_settings()
    if not cfg.get("briefing_enabled", False):
        return

    briefing_time_str = cfg.get("briefing_time", "08:00")
    now = datetime.now()
    if now.strftime("%H:%M") != briefing_time_str:
        return
    today_str = now.strftime("%Y-%m-%d")
    if cfg.get("last_briefing_date") == today_str:
        return  # 오늘 이미 전송

    today_scheds = get_occurrences_on_date(date.today())
    pending = [t for t in load_todos() if not t["completed"]]

    lines = []
    # 일정
    if today_scheds:
        lines.append(f"📅 오늘 일정 {len(today_scheds)}개: " +
                     ", ".join(f"{occ.strftime('%H:%M')} {s['title']}" for s, occ in today_scheds[:3]))
    else:
        lines.append("📅 오늘 일정 없음")

    # 할 일
    if pending:
        lines.append(f"✅ 남은 할 일 {len(pending)}개")

    # 어제 수면 체크
    sleep_records = load_sleep()
    if sleep_records:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        yesterday_sleep = next((s for s in sleep_records if s["date"] == yesterday), None)
        if yesterday_sleep:
            h = yesterday_sleep["duration"]
            if h < 6:
                lines.append(f"😴 어제 수면 {h}시간 — 많이 부족해요! 오늘 컨디션 조심")
            elif h < 7:
                lines.append(f"😴 어제 수면 {h}시간 — 조금 부족해요")

    # 이번달 지출 경고
    try:
        now_inner = datetime.now()
        m_summary = ledger_monthly_summary(now_inner.year, now_inner.month)
        if m_summary["expense"] > 0:
            lines.append(f"💰 이번달 지출 {m_summary['expense']:,}원")
    except Exception:
        pass

    show_toast("☀️ 아침 브리핑", " / ".join(lines)[:300])
    send_telegram("☀️ 아침 브리핑\n" + "\n".join(lines))
    cfg["last_briefing_date"] = today_str
    save_settings(cfg)


reminder_and_briefing()


# ════════════════════════════════════════
#  페이지: 홈
# ════════════════════════════════════════
if page == "🏠 홈":
    now = datetime.now()
    weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]
    st.title(f"🏠 {now.strftime('%Y년 %m월 %d일')} ({weekday_kr})")
    st.caption(f"지금 {now.strftime('%H:%M')}")
    st.write("")

    # ── 아침 브리핑 배너 (오전 6~12시 사이, 하루 1번)
    if 6 <= now.hour < 12:
        briefing_dismissed_key = f"briefing_dismissed_{date.today().isoformat()}"
        if not st.session_state.get(briefing_dismissed_key, False):
            today_scheds_h = get_occurrences_on_date(date.today())
            pending_h = [t for t in load_todos() if not t["completed"]]
            sleep_records_h = load_sleep()
            sleep_warn = ""
            if sleep_records_h:
                yesterday_h = (date.today() - timedelta(days=1)).isoformat()
                ys = next((s for s in sleep_records_h if s["date"] == yesterday_h), None)
                if ys and ys["duration"] < 7:
                    icon = "😴" if ys["duration"] < 6 else "🌙"
                    sleep_warn = f"{icon} 어제 수면 **{ys['duration']}시간** {'— 많이 부족해요!' if ys['duration'] < 6 else '— 조금 부족해요'}"
            try:
                m_summary_h = ledger_monthly_summary(now.year, now.month)
                spend_txt = f"💰 이번달 지출 **{m_summary_h['expense']:,}원**"
            except Exception:
                spend_txt = ""

            banner_lines = []
            if today_scheds_h:
                sched_preview = ", ".join(f"{occ.strftime('%H:%M')} {s['title']}" for s, occ in today_scheds_h[:3])
                banner_lines.append(f"📅 오늘 일정 **{len(today_scheds_h)}개** — {sched_preview}")
            else:
                banner_lines.append("📅 오늘 예정된 일정 없음")
            if pending_h:
                banner_lines.append(f"✅ 남은 할 일 **{len(pending_h)}개**")
            if sleep_warn:
                banner_lines.append(sleep_warn)
            if spend_txt:
                banner_lines.append(spend_txt)

            with st.container():
                col_b, col_x = st.columns([11, 1])
                with col_b:
                    st.markdown(
                        '<div style="background:linear-gradient(135deg,#667eea,#764ba2);'
                        'border-radius:12px;padding:16px 20px;margin-bottom:12px;color:white">'
                        '<div style="font-size:1.1rem;font-weight:700;margin-bottom:8px">☀️ 좋은 아침이에요!</div>'
                        + "".join(f'<div style="font-size:0.9rem;margin:4px 0">{l}</div>' for l in banner_lines)
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                with col_x:
                    if st.button("✕", key="dismiss_briefing", help="닫기"):
                        st.session_state[briefing_dismissed_key] = True
                        st.rerun()
    st.write("")

    # 다음 일정 + 날씨 (2열)
    col_sched, col_weather = st.columns([3, 2])

    with col_sched:
        upcoming = get_upcoming_occurrences(within_days=60)
        if upcoming:
            s, occ = upcoming[0]
            delta = occ - now
            rec_tag = (
                f'<span class="recurrence-tag">{RECURRENCE_LABEL[s["recurrence"]]}</span>'
                if s.get("recurrence", "none") != "none" else ""
            )
            st.markdown(
                f'<div class="next-card">'
                f'<div class="next-label">⏰ 다음 일정</div>'
                f'<div class="next-title">{s["title"]}{rec_tag}</div>'
                f'<div class="next-time">{occ.strftime("%Y-%m-%d %H:%M")} · '
                f'<b>{format_countdown(delta)}</b></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="next-card empty">'
                f'<div class="next-label">⏰ 다음 일정</div>'
                f'<div class="next-title">예정된 일정이 없어요</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with col_weather:
        w = fetch_weather()
        if w:
            emoji, desc = weather_info(w["code"], is_night=not w["is_day"])
            minmax = (
                f'🔺 {w["temp_max"]}° / 🔻 {w["temp_min"]}°'
                if w["temp_max"] is not None else ""
            )
            precip = f'☔ {w["precip_today"]}mm' if w["precip_today"] > 0 else ""
            st.markdown(
                f'<div class="weather-card">'
                f'<div class="weather-location">📍 {WEATHER_LOCATION}</div>'
                f'<div class="weather-main">'
                f'  <span class="weather-emoji">{emoji}</span>'
                f'  <span class="weather-temp">{w["temp"]}°</span>'
                f'</div>'
                f'<div class="weather-desc">{desc}</div>'
                f'<div class="weather-feels">체감 {w["feels_like"]}°</div>'
                f'<div class="weather-details">'
                f'  <span class="weather-detail-item">💧 {w["humidity"]}%</span>'
                f'  <span class="weather-detail-item">💨 {w["wind"]}m/s</span>'
                f'  {"<span class=\"weather-detail-item\">" + precip + "</span>" if precip else ""}'
                f'</div>'
                f'{"<div class=\"weather-minmax\">" + minmax + "</div>" if minmax else ""}'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="weather-card">'
                f'<div class="weather-location">📍 {WEATHER_LOCATION}</div>'
                f'<div class="weather-error">날씨 정보를 불러올 수 없어요.<br>인터넷 연결을 확인해주세요.</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # 통계
    todos_all = load_todos()
    pending_count = sum(1 for t in todos_all if not t["completed"])
    week_count = sum(
        1 for s in load_schedules()
        for _ in expand_schedule_in_range(s, now, now + timedelta(days=7))
    )
    today_str = date.today().isoformat()
    habits_all = load_habits()
    habit_done_today = sum(1 for h in habits_all if today_str in h.get("check_dates", []))
    w_week = workout_week_summary()
    month_finance = ledger_monthly_summary(now.year, now.month)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, num, label, color in [
        (c1, week_count,       "이번 주 일정",    "#2383e2"),
        (c2, pending_count,    "남은 할 일",       "#f59e0b"),
        (c3, len(load_memos()), "메모",            "#787774"),
        (c4, f"{habit_done_today}/{len(habits_all)}", "오늘 습관", "#16a34a"),
        (c5, f"{w_week['total_min']}분", "이번 주 운동", "#8b5cf6"),
        (c6, f"{month_finance['net']:+,}", "이번 달 잔액", "#2383e2" if month_finance['net'] >= 0 else "#dc2626"),
    ]:
        with col:
            st.markdown(
                f'<div class="stat-card"><div class="stat-num" style="font-size:1.3rem;color:{color}">{num}</div>'
                f'<div class="stat-label">{label}</div></div>',
                unsafe_allow_html=True,
            )

    # 5일 날씨 예보
    st.write("")
    forecast = fetch_weather_forecast()
    if forecast:
        st.markdown("### 🌤️ 5일 날씨 예보")
        week_kr = ["월","화","수","목","금","토","일"]
        fcols = st.columns(5)
        for i, (fc, col) in enumerate(zip(forecast, fcols)):
            d = date.fromisoformat(fc["date"])
            emoji, _ = weather_info(fc["code"])
            rain_txt = f"☔{fc['precip']}mm" if fc["precip"] > 0 else ""
            with col:
                st.markdown(
                    f'<div class="forecast-card">'
                    f'<div class="forecast-day">{week_kr[d.weekday()]} ({d.strftime("%m/%d")})</div>'
                    f'<div class="forecast-emoji">{emoji}</div>'
                    f'<div class="forecast-temp">🔺{fc["temp_max"]}° 🔻{fc["temp_min"]}°</div>'
                    f'<div style="font-size:0.75rem;color:#787774;margin-top:2px">{rain_txt}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    st.write("")
    st.write("")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### 📅 오늘 일정")
        today_occs = get_occurrences_on_date(date.today())
        future_occs = [(s, occ) for s, occ in today_occs if occ >= now]
        past_occs = [(s, occ) for s, occ in today_occs if occ < now]
        if not today_occs:
            st.caption("오늘 일정이 없어요 🌿")
        for s, occ in future_occs:
            rec_tag = (
                f'<span class="recurrence-tag">{RECURRENCE_LABEL[s["recurrence"]]}</span>'
                if s.get("recurrence", "none") != "none" else ""
            )
            st.markdown(
                f'<div class="today-row"><div class="today-time">'
                f'🕐 {occ.strftime("%H:%M")}</div>'
                f'<div class="today-title">{s["title"]}{rec_tag}</div></div>',
                unsafe_allow_html=True,
            )
        if past_occs:
            with st.expander(f"지난 시각 ({len(past_occs)})", expanded=False):
                for s, occ in past_occs:
                    st.markdown(
                        f'<div class="today-row" style="opacity:0.55">'
                        f'<div class="today-time">🕐 {occ.strftime("%H:%M")}</div>'
                        f'<div class="today-title">{s["title"]}</div></div>',
                        unsafe_allow_html=True,
                    )

    with col_right:
        pending = [t for t in todos_all if not t["completed"]]
        st.markdown("### ✅ 진행 중인 할 일")
        if not pending:
            st.caption("할 일이 없어요 🎉")
        else:
            for t in pending[:6]:
                st.markdown(
                    f'<div class="today-row"><div class="today-title">☐ {t["title"]}</div></div>',
                    unsafe_allow_html=True,
                )
            if len(pending) > 6:
                st.caption(f"...외 {len(pending) - 6}개 (할 일 탭에서 확인)")


# ════════════════════════════════════════
#  페이지: 채팅 (이미지 첨부 + 대화 기록 영구 저장)
# ════════════════════════════════════════
elif page == "💬 채팅":
    st.title("💬 채팅")
    st.caption("AI 비서와 대화하세요. 앱을 껐다 켜도 이전 대화를 기억해요. 📎 이미지 첨부도 가능.")
    st.write("")

    # 앱 시작 시 파일에서 채팅 기록 불러오기
    if "messages" not in st.session_state:
        st.session_state.messages = load_chat_history()

    # 날짜 구분선을 넣어서 대화 기록 표시
    prev_date_label = None
    for msg in st.session_state.messages:
        ts = msg.get("timestamp", "")
        label = date_separator_label(ts) if ts else ""
        if label and label != prev_date_label:
            st.markdown(
                f'<div style="text-align:center;margin:12px 0 8px;">'
                f'<span style="background:#e9e9e7;color:#787774;font-size:0.78rem;'
                f'padding:3px 12px;border-radius:20px;">{label}</span></div>',
                unsafe_allow_html=True,
            )
            prev_date_label = label
        with st.chat_message(msg["role"]):
            st.markdown(msg.get("display", msg["content"]))

    # ── 음성 입력 (항상 표시)
    if HAS_MIC:
        st.markdown("**🎤 음성으로 말하기** — 버튼 누르고 말한 뒤 다시 누르면 전송돼요")
        voice_audio = mic_recorder(
            start_prompt="🎤 누르고 말하기",
            stop_prompt="⏹ 말하기 완료 (다시 클릭)",
            just_once=True,
            use_container_width=False,
            key=f"mic_{st.session_state.mic_key}",
        )
        if voice_audio and voice_audio.get("bytes"):
            with st.spinner("🎤 AI가 음성을 듣고 있어요..."):
                try:
                    v_text, v_answer = ask_gemini_voice(
                        voice_audio["bytes"], "audio/webm"
                    )
                    now_v = datetime.now()
                    st.session_state.messages.append({
                        "role": "user",
                        "content": v_text,
                        "display": f"🎤 {v_text}",
                        "timestamp": now_v.isoformat(timespec="minutes"),
                    })
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": v_answer,
                        "timestamp": now_v.isoformat(timespec="minutes"),
                    })
                    save_chat_history(st.session_state.messages)
                    st.session_state.mic_key += 1
                    st.rerun()
                except Exception as e:
                    st.error(f"음성 인식 오류: {e}")

    # ── 이미지 첨부
    with st.expander("📎 이미지 첨부 (선택)", expanded=False):
        st.caption("영수증·메모·사진 등 이미지를 첨부하면 AI가 분석해요")
        uploaded_file = st.file_uploader(
            "이미지",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            key=f"chat_img_{st.session_state.upload_key}",
            label_visibility="collapsed",
        )
        if uploaded_file:
            st.image(uploaded_file, width=220)

    # 채팅 입력
    user_input = st.chat_input("무엇이든 물어보세요")
    if user_input:
        # 이미지 데이터 수집
        image_data, image_mime_type = None, "image/jpeg"
        if uploaded_file:
            image_data = uploaded_file.read()
            ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
            image_mime_type = IMAGE_MIME.get(ext, "image/jpeg")

        # 타임스탬프 포함해서 메시지 저장
        now = datetime.now()
        display_text = f"📷 {user_input}" if image_data else user_input
        st.session_state.messages.append({
            "role": "user",
            "content": user_input,
            "display": display_text,
            "timestamp": now.isoformat(timespec="minutes"),
        })
        with st.chat_message("user"):
            st.markdown(display_text)

        if image_data:
            st.session_state.upload_key += 1

        system_instruction = (
            f"너는 사용자의 스마트 개인 AI 비서야. 말로 모든 걸 처리해줘.\n"
            f"오늘은 {now.strftime('%Y년 %m월 %d일 (%A)')}, 지금 시각은 {now.strftime('%H:%M')}이야.\n\n"
            f"[오늘 일정]\n{schedules_as_text()}\n\n"
            f"[할 일]\n{todos_as_text()}\n\n"
            f"[메모]\n{memos_as_text()}\n\n"
            "## 도구 사용 기준\n"
            "- '내일 3시 치과' → tool_add_schedule\n"
            "- '우유 사야해' → tool_add_todo\n"
            "- '달리기 30분 했어' → tool_log_workout\n"
            "- '어젯밤 6시간 잤어' → tool_log_sleep\n"
            "- '오늘 기분 좋아' → tool_log_mood (5:최고, 4:좋음, 3:보통, 2:조금별로, 1:별로)\n"
            "- '점심 8000원 썼어' → tool_add_expense\n"
            "- '용돈 5만원 받았어' → tool_add_income\n"
            "- '물 마시기 했어' → tool_check_habit\n"
            "- '오늘 현황 알려줘' → tool_get_today_summary\n"
            "- 이미지 첨부 시 내용 분석 후 저장 여부 물어봐\n"
            "도구 호출 후 결과를 친근하게 확인해줘. 단순 질문은 도구 없이 한국어로 답해."
        )

        # Gemini에는 최근 CHAT_CONTEXT_LIMIT개만 전달 (토큰 절약)
        context = st.session_state.messages[-CHAT_CONTEXT_LIMIT:]

        with st.chat_message("assistant"):
            with st.spinner("생각 중..."):
                try:
                    answer = ask_gemini(
                        context,
                        system_instruction,
                        image_data=image_data,
                        image_mime=image_mime_type,
                    )
                    st.markdown(answer)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "timestamp": datetime.now().isoformat(timespec="minutes"),
                    })
                    # 파일에 저장 (영구 보관)
                    save_chat_history(st.session_state.messages)
                except genai_errors.ServerError:
                    st.warning("⚠️ 구글 서버가 바쁩니다. 30초~1분 후 재시도해주세요.")
                    st.session_state.messages.pop()
                except genai_errors.ClientError as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        st.warning("⚠️ 무료 한도 초과. 잠시 후 다시 시도해주세요.")
                    else:
                        st.error(f"오류: {err}")
                    st.session_state.messages.pop()
                except Exception as e:
                    st.error(f"예상치 못한 오류: {e}")
                    st.session_state.messages.pop()


# ════════════════════════════════════════
#  페이지: 검색
# ════════════════════════════════════════
elif page == "🔍 검색":
    st.title("🔍 검색")
    st.caption("일정·할 일·메모를 한 번에 검색합니다.")
    st.write("")

    query = st.text_input("검색어를 입력하세요", placeholder="예: 회의, 치과, 책", label_visibility="collapsed")

    if query.strip():
        q = query.strip()
        q_lower = q.lower()

        sched_matches = [
            s for s in load_schedules()
            if q_lower in s["title"].lower() or q_lower in s.get("note", "").lower()
        ]
        todo_matches = [
            t for t in load_todos()
            if q_lower in t["title"].lower()
        ]
        memo_matches = [
            m for m in load_memos()
            if q_lower in m["title"].lower() or q_lower in m.get("content", "").lower()
        ]

        total = len(sched_matches) + len(todo_matches) + len(memo_matches)
        if total == 0:
            st.info(f"'{q}'에 대한 결과가 없습니다.")
        else:
            st.caption(f"총 {total}개 결과")

            if sched_matches:
                st.markdown('<div class="search-section-title">📅 일정</div>', unsafe_allow_html=True)
                for s in sched_matches:
                    rec_val = s.get("recurrence", "none")
                    rec_tag = (
                        f'<span class="recurrence-tag">{RECURRENCE_LABEL[rec_val]}</span>'
                        if rec_val != "none" else ""
                    )
                    note_html = (
                        f'<div class="item-note">{highlight(s["note"], q)}</div>'
                        if s.get("note") else ""
                    )
                    st.markdown(
                        f'<div class="item-card">'
                        f'<div class="item-meta">📅 {s["datetime"]}{rec_tag}</div>'
                        f'<div class="item-title">{highlight(s["title"], q)}</div>'
                        f'{note_html}</div>',
                        unsafe_allow_html=True,
                    )

            if todo_matches:
                st.markdown('<div class="search-section-title">✅ 할 일</div>', unsafe_allow_html=True)
                for t in todo_matches:
                    status = "☑" if t["completed"] else "☐"
                    style = "text-decoration:line-through;opacity:0.6;" if t["completed"] else ""
                    st.markdown(
                        f'<div class="item-card">'
                        f'<div class="item-title" style="{style}">'
                        f'{status} {highlight(t["title"], q)}</div></div>',
                        unsafe_allow_html=True,
                    )

            if memo_matches:
                st.markdown('<div class="search-section-title">📝 메모</div>', unsafe_allow_html=True)
                for m in memo_matches:
                    body_html = (
                        f'<div class="item-body">{highlight(m["content"][:200], q)}'
                        f'{"..." if len(m.get("content","")) > 200 else ""}</div>'
                        if m.get("content") else ""
                    )
                    st.markdown(
                        f'<div class="item-card">'
                        f'<div class="item-meta">🕒 {m["created_at"]}</div>'
                        f'<div class="item-title">{highlight(m["title"], q)}</div>'
                        f'{body_html}</div>',
                        unsafe_allow_html=True,
                    )
    else:
        st.caption("검색어를 입력하면 일정, 할 일, 메모에서 동시에 찾아줍니다.")


# ════════════════════════════════════════
#  페이지: 일정
# ════════════════════════════════════════
elif page == "📅 일정":
    st.title("📅 일정")
    st.caption("반복 일정 지원. 30/15/5분 전 알림 자동.")
    st.write("")

    with st.expander("➕ 새 일정 추가", expanded=False):
        with st.form("add_schedule_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                d = st.date_input("날짜", value=date.today())
            with col2:
                t = st.time_input("시간", value=time(9, 0))
            title = st.text_input("제목", placeholder="예: 치과 예약")
            note = st.text_area("메모 (선택)", placeholder="추가 정보", height=80)
            rec_label = st.selectbox("반복", list(RECURRENCE_OPTIONS.keys()))
            if st.form_submit_button("추가", type="primary"):
                if not title.strip():
                    st.warning("제목을 입력해주세요.")
                else:
                    add_schedule(
                        datetime.combine(d, t),
                        title.strip(), note.strip(),
                        RECURRENCE_OPTIONS[rec_label],
                    )
                    st.success("일정 추가!")
                    st.rerun()

    st.write("")
    filter_mode = st.radio(
        "보기", ["📌 예정", "📜 지난 일정", "📋 전체"],
        horizontal=True, label_visibility="collapsed",
    )

    schedules = load_schedules()
    if filter_mode == "📌 예정":
        schedules = [s for s in schedules if not is_past_schedule(s)]
    elif filter_mode == "📜 지난 일정":
        schedules = [s for s in schedules if is_past_schedule(s)]

    def _sort_key(s):
        nxt = next_occurrence(s)
        return (0, nxt) if nxt else (1, datetime.max)

    schedules.sort(key=_sort_key)
    st.write("")

    if not schedules:
        msg = {"📌 예정": "예정된 일정 없음", "📜 지난 일정": "지난 일정 없음"}.get(
            filter_mode, "등록된 일정 없음. '➕ 새 일정 추가'를 눌러보세요."
        )
        st.info(msg)
    else:
        for s in schedules:
            if st.session_state.editing_sched_id == s["id"]:
                with st.form(f"edit_sched_{s['id']}"):
                    st.markdown("**✏️ 일정 수정**")
                    try:
                        edt = datetime.fromisoformat(s["datetime"])
                    except ValueError:
                        edt = datetime.now()
                    c1, c2 = st.columns(2)
                    with c1:
                        nd = st.date_input("날짜", value=edt.date())
                    with c2:
                        nt = st.time_input("시간", value=edt.time())
                    ntitle = st.text_input("제목", value=s["title"])
                    nnote = st.text_area("메모", value=s.get("note", ""), height=80)
                    cur_rec = s.get("recurrence", "none")
                    rec_keys = list(RECURRENCE_OPTIONS.keys())
                    def_idx = next(
                        (i for i, k in enumerate(rec_keys) if RECURRENCE_OPTIONS[k] == cur_rec), 0
                    )
                    nrec = st.selectbox("반복", rec_keys, index=def_idx)
                    ca, cb = st.columns(2)
                    with ca:
                        sv = st.form_submit_button("💾 저장", type="primary", use_container_width=True)
                    with cb:
                        cx = st.form_submit_button("취소", use_container_width=True)
                    if sv:
                        if not ntitle.strip():
                            st.warning("제목을 입력해주세요.")
                        else:
                            update_schedule(
                                s["id"], datetime.combine(nd, nt),
                                ntitle.strip(), nnote.strip(), RECURRENCE_OPTIONS[nrec],
                            )
                            st.session_state.editing_sched_id = None
                            st.rerun()
                    if cx:
                        st.session_state.editing_sched_id = None
                        st.rerun()
            else:
                c1, c2, c3 = st.columns([8, 1, 1])
                with c1:
                    past_cls = " past" if is_past_schedule(s) else ""
                    rec_val = s.get("recurrence", "none")
                    if rec_val != "none":
                        nxt = next_occurrence(s)
                        disp_dt = nxt.strftime("%Y-%m-%dT%H:%M") if nxt else s["datetime"]
                        rec_tag = f'<span class="recurrence-tag">{RECURRENCE_LABEL[rec_val]}</span>'
                    else:
                        disp_dt = s["datetime"]
                        rec_tag = ""
                    note_html = f'<div class="item-note">{s["note"]}</div>' if s.get("note") else ""
                    st.markdown(
                        f'<div class="item-card{past_cls}">'
                        f'<div class="item-meta">📅 {disp_dt}{rec_tag}</div>'
                        f'<div class="item-title">{s["title"]}</div>{note_html}</div>',
                        unsafe_allow_html=True,
                    )
                with c2:
                    if st.button("✏️", key=f"edit_sch_{s['id']}", help="수정"):
                        st.session_state.editing_sched_id = s["id"]
                        st.rerun()
                with c3:
                    if st.button("🗑️", key=f"del_sch_{s['id']}", help="삭제"):
                        delete_schedule(s["id"])
                        st.rerun()


# ════════════════════════════════════════
#  페이지: 할 일
# ════════════════════════════════════════
elif page == "✅ 할 일":
    st.title("✅ 할 일")
    st.caption("채팅으로 'X 다 했어' 라고 하면 자동 완료 처리.")
    st.write("")

    with st.form("add_todo_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([5, 2, 1])
        with c1:
            new_todo = st.text_input("할 일", placeholder="예: 우유 사기", label_visibility="collapsed")
        with c2:
            new_priority = st.selectbox("우선순위", list(TODO_PRIORITY.values()),
                                        index=1, label_visibility="collapsed")
        with c3:
            submitted = st.form_submit_button("추가", type="primary", use_container_width=True)
        if submitted and new_todo.strip():
            p_key = {v: k for k, v in TODO_PRIORITY.items()}[new_priority]
            add_todo(new_todo.strip(), p_key)
            st.rerun()

    st.write("")
    todos = load_todos()
    if not todos:
        st.info("아직 할 일이 없습니다.")
    else:
        pending = [t for t in todos if not t["completed"]]
        completed = [t for t in todos if t["completed"]]

        def _toggle(tid):
            toggle_todo(tid)

        if pending:
            sort_opt = st.radio("정렬", ["우선순위순", "추가순"], horizontal=True, label_visibility="collapsed")
            if sort_opt == "우선순위순":
                pending = sorted(pending, key=lambda t: PRIORITY_ORDER.get(t.get("priority","medium"), 1))
            st.markdown(f"**📌 진행 중 ({len(pending)})**")
            for t in pending:
                c1, c2 = st.columns([10, 1])
                with c1:
                    p = t.get("priority", "medium")
                    p_label = TODO_PRIORITY.get(p, "🟡 보통")
                    st.checkbox(
                        f"{p_label}  {t['title']}",
                        value=False, key=f"chk_{t['id']}",
                        on_change=_toggle, args=(t["id"],)
                    )
                with c2:
                    if st.button("🗑️", key=f"del_todo_{t['id']}", help="삭제"):
                        delete_todo(t["id"])
                        st.rerun()
        else:
            st.success("🎉 진행 중인 할 일이 없어요!")

        if completed:
            st.write("")
            with st.expander(f"✓ 완료됨 ({len(completed)})", expanded=False):
                for t in completed:
                    c1, c2 = st.columns([10, 1])
                    with c1:
                        st.checkbox(t["title"], value=True, key=f"chk_{t['id']}",
                                    on_change=_toggle, args=(t["id"],))
                    with c2:
                        if st.button("🗑️", key=f"del_done_{t['id']}", help="삭제"):
                            delete_todo(t["id"])
                            st.rerun()


# ════════════════════════════════════════
#  페이지: 메모
# ════════════════════════════════════════
elif page == "📝 메모":
    st.title("📝 메모")
    st.caption("채팅에서 '메모에 뭐 있어?' 라고 물어볼 수 있어요.")
    st.write("")

    with st.expander("➕ 새 메모 추가", expanded=False):
        with st.form("add_memo_form", clear_on_submit=True):
            title   = st.text_input("제목", placeholder="예: 책 추천")
            content = st.text_area("내용", placeholder="자유롭게 적으세요", height=150)
            tags_input = st.text_input("태그 (쉼표로 구분)", placeholder="예: 공부, 아이디어")
            if st.form_submit_button("추가", type="primary"):
                if not title.strip():
                    st.warning("제목을 입력해주세요.")
                else:
                    tags = [t.strip() for t in tags_input.split(",") if t.strip()]
                    add_memo(title.strip(), content.strip(), tags)
                    st.success("메모 추가!")
                    st.rerun()

    # 태그 필터
    all_tags = sorted({tag for m in load_memos() for tag in m.get("tags", [])})
    sel_tag  = None
    if all_tags:
        sel_tag = st.selectbox("🏷️ 태그 필터", ["전체"] + all_tags, label_visibility="collapsed")
        if sel_tag == "전체":
            sel_tag = None

    st.write("")
    memos_filtered = load_memos()
    if sel_tag:
        memos_filtered = [m for m in memos_filtered if sel_tag in m.get("tags", [])]
    for m in memos_filtered:
        if st.session_state.editing_memo_id == m["id"]:
            with st.form(f"edit_memo_{m['id']}"):
                st.markdown("**✏️ 메모 수정**")
                ntitle = st.text_input("제목", value=m["title"])
                ncontent = st.text_area("내용", value=m.get("content", ""), height=150)
                ca, cb = st.columns(2)
                with ca:
                    sv = st.form_submit_button("💾 저장", type="primary", use_container_width=True)
                with cb:
                    cx = st.form_submit_button("취소", use_container_width=True)
                if sv:
                    if not ntitle.strip():
                        st.warning("제목을 입력해주세요.")
                    else:
                        update_memo(m["id"], ntitle.strip(), ncontent.strip())
                        st.session_state.editing_memo_id = None
                        st.rerun()
                if cx:
                    st.session_state.editing_memo_id = None
                    st.rerun()
        else:
            c1, c2, c3 = st.columns([8, 1, 1])
            with c1:
                body_html = f'<div class="item-body">{m["content"]}</div>' if m.get("content") else ""
                tags_html = "".join(f'<span class="tag-badge">#{t}</span>' for t in m.get("tags", []))
                st.markdown(
                    f'<div class="item-card">'
                    f'<div class="item-meta">🕒 {m["created_at"]}</div>'
                    f'<div class="item-title">{m["title"]}</div>'
                    f'{tags_html}{body_html}</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("✏️", key=f"edit_memo_{m['id']}", help="수정"):
                    st.session_state.editing_memo_id = m["id"]
                    st.rerun()
            with c3:
                if st.button("🗑️", key=f"del_memo_{m['id']}", help="삭제"):
                    delete_memo(m["id"])
                    st.rerun()
    if not load_memos():
        st.info("아직 등록된 메모가 없습니다. 위쪽 '➕ 새 메모 추가'를 눌러 추가하세요.")


# ════════════════════════════════════════
#  페이지: 구글 캘린더
# ════════════════════════════════════════
elif page == "🔗 구글 캘린더":
    st.title("🔗 구글 캘린더")
    st.caption("구글 캘린더 ↔ AI비서 양방향 동기화")
    st.write("")

    creds, err = get_google_creds()

    if creds:
        # ── 연결된 상태
        st.success("✅ 구글 캘린더 연결됨")
        st.write("")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 지금 동기화", type="primary", use_container_width=True):
                with st.spinner("구글 캘린더와 동기화 중..."):
                    try:
                        added, upd = sync_from_google(creds)
                        pushed = sync_to_google(creds)
                        msg_parts = []
                        if added or upd:
                            msg_parts.append(f"구글→AI비서: {added}개 추가, {upd}개 업데이트")
                        if pushed:
                            msg_parts.append(f"AI비서→구글: {pushed}개 추가")
                        if not msg_parts:
                            st.info("새로운 변경 사항이 없습니다.")
                        else:
                            st.success("✅ " + " / ".join(msg_parts))
                        st.rerun()
                    except Exception as e:
                        st.error(f"동기화 실패: {e}")
        with col2:
            if st.button("🔌 연결 해제", use_container_width=True):
                GOOGLE_TOKEN_FILE.unlink(missing_ok=True)
                st.success("연결이 해제되었습니다.")
                st.rerun()

        st.write("")
        st.divider()

        # ── 동기화된 일정 목록
        all_local = load_schedules()
        google_events = [s for s in all_local if s.get("google_id")]
        local_only = [s for s in all_local if not s.get("google_id")]

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"### 🔗 구글에서 가져온 일정 ({len([s for s in google_events if s.get('source')=='google'])}개)")
            goog = [s for s in google_events if s.get("source") == "google"]
            if not goog:
                st.caption("동기화 버튼을 눌러 가져오세요.")
            for s in goog[:15]:
                rec_tag = (f'<span class="recurrence-tag">{RECURRENCE_LABEL[s["recurrence"]]}</span>'
                           if s.get("recurrence", "none") != "none" else "")
                note_html = f'<div class="item-note">{s["note"]}</div>' if s.get("note") else ""
                st.markdown(
                    f'<div class="item-card">'
                    f'<div class="item-meta">📅 {s["datetime"]}{rec_tag}</div>'
                    f'<div class="item-title">{s["title"]}</div>'
                    f'{note_html}</div>',
                    unsafe_allow_html=True,
                )

        with col_b:
            st.markdown(f"### 📱 AI비서→구글 등록된 일정 ({len([s for s in google_events if s.get('source')=='synced'])}개)")
            synced = [s for s in google_events if s.get("source") == "synced"]
            if not synced:
                st.caption("AI비서에서 일정 추가 후 동기화하면 구글에도 등록돼요.")
            for s in synced[:15]:
                rec_tag = (f'<span class="recurrence-tag">{RECURRENCE_LABEL[s["recurrence"]]}</span>'
                           if s.get("recurrence", "none") != "none" else "")
                st.markdown(
                    f'<div class="item-card">'
                    f'<div class="item-meta">📅 {s["datetime"]}{rec_tag}</div>'
                    f'<div class="item-title">{s["title"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    else:
        # ── 미연결 상태
        if not _google_libs_ok():
            st.error("❌ 구글 라이브러리가 설치되지 않았습니다.")
            st.info("아래 명령어를 콘솔(검은 창)에 입력하고 앱을 다시 시작해주세요:")
            st.code("pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")

        elif not GOOGLE_CREDS_FILE.exists():
            st.warning("⚠️ credentials.json 파일이 없습니다.")
            with st.expander("📋 설정 방법 (클릭해서 펼치기)", expanded=True):
                st.markdown("""
**① [Google Cloud Console](https://console.cloud.google.com/) 접속**

**② 새 프로젝트 생성**
- 상단 프로젝트 선택 → "새 프로젝트"
- 이름: `내 AI비서` → 만들기

**③ Google Calendar API 활성화**
- APIs & Services → Library → `Google Calendar API` 검색 → Enable

**④ OAuth 동의 화면 설정**
- APIs & Services → OAuth consent screen
- User Type: **External** → 만들기
- 앱 이름: `내 AI비서`, 이메일 입력 → 저장 후 계속
- 테스트 사용자에 **본인 구글 이메일 추가**

**⑤ 인증 키 발급**
- APIs & Services → Credentials → Create Credentials → **OAuth client ID**
- Application type: **Desktop app** → 이름: `AI비서` → 만들기
- **⬇️ JSON 다운로드** → 파일명을 `credentials.json`으로 변경
- 이 파일을 `C:/Users/a0103/Desktop/AI비서/` 폴더에 넣기

**⑥ 설정 완료 후 이 페이지 새로고침 (Ctrl+R)**
                """)

        else:
            st.info("credentials.json 파일 확인됨 ✅ 아래 버튼으로 구글 로그인하세요.")
            st.caption("버튼을 누르면 브라우저가 열립니다. 구글 계정으로 로그인 후 허용해주세요.")
            if st.button("🔑 구글 계정으로 연결하기", type="primary", use_container_width=False):
                with st.spinner("브라우저에서 구글 로그인 중... (완료되면 자동으로 돌아옵니다)"):
                    creds, auth_err = do_google_auth()
                    if creds:
                        st.success("✅ 연결 성공! 동기화 버튼을 눌러주세요.")
                        st.rerun()
                    else:
                        st.error(f"연결 실패: {auth_err}")


# ════════════════════════════════════════
#  페이지: 🗓️ 캘린더뷰
# ════════════════════════════════════════
elif page == "🗓️ 캘린더뷰":
    st.title("🗓️ 캘린더 뷰")
    st.caption("월별 달력으로 일정을 확인하세요.")
    st.write("")

    cy, cm = st.session_state.cal_year, st.session_state.cal_month
    c_prev, c_title, c_next = st.columns([1, 4, 1])
    with c_prev:
        if st.button("◀", use_container_width=True):
            if cm == 1:
                st.session_state.cal_month = 12
                st.session_state.cal_year -= 1
            else:
                st.session_state.cal_month -= 1
            st.rerun()
    with c_title:
        st.markdown(f"<h3 style='text-align:center;margin:0'>{cy}년 {cm}월</h3>", unsafe_allow_html=True)
    with c_next:
        if st.button("▶", use_container_width=True):
            if cm == 12:
                st.session_state.cal_month = 1
                st.session_state.cal_year += 1
            else:
                st.session_state.cal_month += 1
            st.rerun()

    first_wd, num_days = calendar.monthrange(cy, cm)
    start_dt = datetime(cy, cm, 1)
    end_dt   = datetime(cy, cm, num_days, 23, 59)
    day_scheds: dict = {}
    for s in load_schedules():
        for occ in expand_schedule_in_range(s, start_dt, end_dt):
            day_scheds.setdefault(occ.day, []).append(s["title"])

    today = date.today()
    week_kr = ["월", "화", "수", "목", "금", "토", "일"]
    header_html = "".join(f"<th>{d}</th>" for d in week_kr)
    cells = ["<td></td>"] * first_wd
    for day in range(1, num_days + 1):
        is_today = (date(cy, cm, day) == today)
        today_cls = " today" if is_today else ""
        dots = "".join('<span class="cal-dot"></span>' for _ in day_scheds.get(day, [])[:4])
        cells.append(
            f'<td><div class="cal-day{today_cls}">'
            f'<div class="cal-num">{day}</div>{dots}</div></td>'
        )
    while len(cells) % 7 != 0:
        cells.append('<td><div class="cal-day other-month"><div class="cal-num"></div></div></td>')

    rows = ""
    for i in range(0, len(cells), 7):
        rows += "<tr>" + "".join(cells[i:i+7]) + "</tr>"

    st.markdown(
        f'<table class="cal-table"><tr>{header_html}</tr>{rows}</table>',
        unsafe_allow_html=True,
    )

    st.write("")
    st.markdown("### 이번 달 일정 목록")
    month_items = [(s, occ) for s in load_schedules()
                   for occ in expand_schedule_in_range(s, start_dt, end_dt)]
    month_items.sort(key=lambda x: x[1])
    if not month_items:
        st.caption("이번 달 일정이 없어요.")
    for s, occ in month_items:
        rec_tag = (f'<span class="recurrence-tag">{RECURRENCE_LABEL[s["recurrence"]]}</span>'
                   if s.get("recurrence", "none") != "none" else "")
        st.markdown(
            f'<div class="item-card">'
            f'<div class="item-meta">📅 {occ.strftime("%m월 %d일 %H:%M")}{rec_tag}</div>'
            f'<div class="item-title">{s["title"]}</div></div>',
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════
#  페이지: 🔁 습관 트래커
# ════════════════════════════════════════
elif page == "🔁 습관":
    st.title("🔁 습관 트래커")
    st.caption("매일 체크해서 스트릭을 유지하세요!")
    st.write("")

    with st.expander("➕ 습관 추가", expanded=False):
        with st.form("add_habit_form", clear_on_submit=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                h_name = st.text_input("습관 이름", placeholder="예: 물 2L 마시기")
            with col2:
                h_icon = st.text_input("아이콘", value="✅", max_chars=2)
            if st.form_submit_button("추가", type="primary"):
                if h_name.strip():
                    add_habit(h_name.strip(), h_icon.strip() or "✅")
                    st.success("습관 추가!")
                    st.rerun()

    st.write("")
    habits = load_habits()
    today_str = date.today().isoformat()
    week_kr = ["월", "화", "수", "목", "금", "토", "일"]

    if not habits:
        st.info("아직 등록된 습관이 없어요. 위에서 추가해보세요!")
    else:
        for h in habits:
            checked_today = today_str in h.get("check_dates", [])
            streak = habit_streak(h)
            week_status = habit_week_status(h)

            c1, c2, c3 = st.columns([7, 2, 1])
            with c1:
                week_dots = "".join(
                    f'<span class="habit-dot {"done" if ok else "miss"}">{week_kr[i][0]}</span>'
                    for i, ok in enumerate(week_status)
                )
                streak_badge = f'<span class="streak-badge">🔥 {streak}일</span>' if streak > 0 else ""
                st.markdown(
                    f'<div class="habit-row">'
                    f'<div><b>{h["icon"]} {h["name"]}</b>{streak_badge}</div>'
                    f'<div class="habit-week">{week_dots}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                label = "✅ 완료" if checked_today else "○ 체크"
                btn_type = "primary" if not checked_today else "secondary"
                if st.button(label, key=f"habit_{h['id']}", use_container_width=True, type=btn_type):
                    toggle_habit(h["id"])
                    st.rerun()
            with c3:
                if st.button("🗑️", key=f"del_habit_{h['id']}", help="삭제"):
                    delete_habit(h["id"])
                    st.rerun()


# ════════════════════════════════════════
#  페이지: 🎯 목표 관리
# ════════════════════════════════════════
elif page == "🎯 목표":
    st.title("🎯 목표 관리")
    st.caption("목표를 설정하면 운동·지출은 자동으로 진행률이 계산돼요.")
    st.write("")

    with st.expander("➕ 목표 추가", expanded=False):
        with st.form("add_goal_form", clear_on_submit=True):
            g_title = st.text_input("목표 제목", placeholder="예: 이번달 운동 20회")
            g_desc  = st.text_area("설명 (선택)", height=60)
            g_type_label = st.selectbox("목표 종류", list(GOAL_TYPE_OPTIONS.values()))
            g_type_key = {v: k for k, v in GOAL_TYPE_OPTIONS.items()}[g_type_label]
            g_deadline = st.date_input("목표 기한", value=date.today().replace(month=12, day=31))

            if g_type_key == "manual":
                g_target = st.number_input("목표값 (예: 100%면 100 입력)", min_value=1, max_value=100000, value=100)
                st.caption("진행률을 직접 입력하는 방식이에요.")
            elif g_type_key == "workout_count":
                g_target = st.number_input("목표 운동 횟수 (회/월)", min_value=1, max_value=200, value=20)
                st.caption("🏃 이번달 운동 기록 횟수를 자동으로 세어서 진행률을 업데이트해요.")
            elif g_type_key == "expense_limit":
                g_target = st.number_input("월 지출 한도 (원)", min_value=1000, max_value=10000000, value=500000, step=10000)
                st.caption("💰 이번달 지출 합계를 자동 추적해요. 목표 = 한도 이하 유지.")

            if st.form_submit_button("추가", type="primary"):
                if g_title.strip():
                    add_goal(g_title.strip(), g_desc.strip(), g_deadline.isoformat(),
                             int(g_target), goal_type=g_type_key)
                    st.success("목표 추가!")
                    st.rerun()

    st.write("")
    goals = load_goals()
    active = [g for g in goals if not g.get("completed")]
    done   = [g for g in goals if g.get("completed")]

    if not goals:
        st.info("등록된 목표가 없어요. 위에서 추가해보세요!\n\n예: '이번달 운동 20회' → 자동 추적 목표로 추가하면 운동할 때마다 자동으로 올라가요.")
    else:
        if active:
            st.markdown(f"**🎯 진행 중 ({len(active)})**")
            for g in active:
                gtype = g.get("goal_type", "manual")
                # 자동 추적 목표는 실시간 계산
                actual_progress = compute_auto_goal_progress(g)
                target = g.get("target", 100)
                d_left = (date.fromisoformat(g["deadline"]) - date.today()).days
                d_txt = f"D-{d_left}" if d_left >= 0 else f"D+{-d_left} 초과"

                if gtype == "expense_limit":
                    # 지출 한도: 초과하면 빨간색
                    pct = min(int(actual_progress / target * 100), 100)
                    bar_color = "#dc2626" if actual_progress > target else "#2383e2"
                    status_txt = f"{actual_progress:,}원 / 한도 {target:,}원 ({pct}%)"
                    if actual_progress > target:
                        status_txt += "  ⚠️ 한도 초과!"
                    auto_badge = '<span style="font-size:0.75rem;background:#fee2e2;color:#dc2626;padding:2px 6px;border-radius:8px;margin-left:6px">💰 자동추적</span>'
                else:
                    pct = min(int(actual_progress / target * 100), 100) if target > 0 else 0
                    bar_color = "#16a34a" if pct >= 100 else "#2383e2"
                    status_txt = f"{actual_progress} / {target} ({pct}%)"
                    if gtype == "workout_count":
                        status_txt = f"{actual_progress}회 / 목표 {target}회 ({pct}%)"
                        auto_badge = '<span style="font-size:0.75rem;background:#ede9fe;color:#7c3aed;padding:2px 6px;border-radius:8px;margin-left:6px">🏃 자동추적</span>'
                    else:
                        auto_badge = ""

                c1, c2 = st.columns([8, 2])
                with c1:
                    st.markdown(
                        f'<div class="goal-card">'
                        f'<div style="display:flex;justify-content:space-between;align-items:center">'
                        f'<b>{g["title"]}</b>{auto_badge}'
                        f'<span style="font-size:0.82rem;color:#787774">{d_txt} · ~{g["deadline"]}</span></div>'
                        f'{"<div style=\"font-size:0.85rem;color:#787774;margin-top:4px\">" + g["description"] + "</div>" if g.get("description") else ""}'
                        f'<div class="progress-bar-bg"><div class="progress-bar-fill" style="width:{pct}%;background:{bar_color}"></div></div>'
                        f'<div style="font-size:0.85rem;color:{bar_color};font-weight:600">{status_txt}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with c2:
                    if gtype == "manual":
                        new_val = st.number_input("진행", min_value=0, max_value=int(target),
                                                  value=int(g["progress"]), key=f"gp_{g['id']}", label_visibility="collapsed")
                        if st.button("저장", key=f"gsave_{g['id']}", use_container_width=True):
                            update_goal_progress(g["id"], new_val)
                            st.rerun()
                    else:
                        st.caption("자동추적 중")
                    if st.button("🗑️", key=f"gdel_{g['id']}", use_container_width=True):
                        delete_goal(g["id"])
                        st.rerun()

        if done:
            with st.expander(f"✅ 달성 완료 ({len(done)})", expanded=False):
                for g in done:
                    st.markdown(
                        f'<div class="goal-card goal-done">'
                        f'<b>✅ {g["title"]}</b>'
                        f'<div style="font-size:0.82rem;color:#787774">기한: {g["deadline"]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button("🗑️ 삭제", key=f"gdone_{g['id']}"):
                        delete_goal(g["id"])
                        st.rerun()


# ════════════════════════════════════════
#  페이지: 📊 주간 리포트
# ════════════════════════════════════════
elif page == "📊 리포트":
    st.title("📊 리포트")
    tab_week, tab_month = st.tabs(["📅 주간", "🗓️ 월간"])

  # ── 월간 리포트
    with tab_month:
        today = date.today()
        sel_m = st.selectbox("월 선택", list(range(1,13)), index=today.month-1,
                             format_func=lambda x: f"{x}월", label_visibility="collapsed")
        ml = ledger_monthly_summary(today.year, sel_m)
        prefix = f"{today.year:04d}-{sel_m:02d}"

        m_start = datetime(today.year, sel_m, 1)
        m_end_day = calendar.monthrange(today.year, sel_m)[1]
        m_end   = datetime(today.year, sel_m, m_end_day, 23, 59)
        m_scheds = [(s, occ) for s in load_schedules()
                    for occ in expand_schedule_in_range(s, m_start, m_end)]
        m_todos_done = [t for t in load_todos()
                        if t.get("completed_at","")[:7] == f"{today.year:04d}-{sel_m:02d}"]
        m_workouts = [w for w in load_workouts() if w["date"].startswith(prefix)]
        m_books_done = [b for b in load_books()
                        if b.get("finished_at","").startswith(prefix)]

        r1,r2,r3,r4 = st.columns(4)
        for col,num,label,color in [
            (r1, len(m_scheds),      f"{sel_m}월 일정",    "#2383e2"),
            (r2, len(m_todos_done),  "완료 할 일",          "#16a34a"),
            (r3, f"{sum(w['duration'] for w in m_workouts)}분", "운동",  "#8b5cf6"),
            (r4, len(m_books_done),  "완독 책",             "#f59e0b"),
        ]:
            with col:
                st.markdown(
                    f'<div class="stat-card"><div class="stat-num" style="color:{color}">{num}</div>'
                    f'<div class="stat-label">{label}</div></div>', unsafe_allow_html=True)
        st.write("")
        c1,c2 = st.columns(2)
        with c1:
            st.markdown(f"#### 💰 {sel_m}월 가계부")
            st.markdown(
                f'<div class="summary-box">'
                f'<div style="display:flex;justify-content:space-around">'
                f'<div><div style="font-size:0.8rem;color:#787774">수입</div>'
                f'<div class="income-tag">+{ml["income"]:,}원</div></div>'
                f'<div><div style="font-size:0.8rem;color:#787774">지출</div>'
                f'<div class="expense-tag">-{ml["expense"]:,}원</div></div>'
                f'<div><div style="font-size:0.8rem;color:#787774">잔액</div>'
                f'<div style="font-weight:700;color:{"#16a34a" if ml["net"]>=0 else "#dc2626"}">{ml["net"]:+,}원</div></div>'
                f'</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f"#### 🏃 {sel_m}월 운동")
            if not m_workouts:
                st.caption("운동 기록 없음")
            type_cnt = {}
            for w in m_workouts:
                type_cnt[w["type"]] = type_cnt.get(w["type"], 0) + w["duration"]
            for wt, dur in sorted(type_cnt.items(), key=lambda x: -x[1]):
                st.markdown(f'<div class="workout-row"><b>{wt}</b> — {dur}분</div>',
                            unsafe_allow_html=True)

  # ── 주간 리포트
    with tab_week:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        st.caption(f"{monday.strftime('%m월 %d일')} ~ {sunday.strftime('%m월 %d일')} 리포트")
    st.write("")

    week_dates = [(monday + timedelta(days=i)).isoformat() for i in range(7)]

    # 일정
    week_scheds = [(s, occ) for s in load_schedules()
                   for occ in expand_schedule_in_range(s,
                       datetime.combine(monday, time(0,0)),
                       datetime.combine(sunday, time(23,59)))]

    # 할 일
    todos_all = load_todos()
    todos_done_week = [t for t in todos_all if t.get("completed_at","")[:10] in week_dates]
    todos_pending = [t for t in todos_all if not t["completed"]]

    # 습관
    habits = load_habits()
    if habits:
        total_checks = sum(1 for h in habits for d in week_dates if d in h.get("check_dates",[]))
        possible_checks = len(habits) * 7
        habit_rate = int(total_checks / possible_checks * 100) if possible_checks else 0
    else:
        habit_rate = 0

    # 운동
    w_summary = workout_week_summary()

    # 가계부
    month_ledger = ledger_monthly_summary(today.year, today.month)

    # 통계 카드
    r1, r2, r3, r4 = st.columns(4)
    for col, num, label, color in [
        (r1, len(week_scheds), "이번 주 일정", "#2383e2"),
        (r2, len(todos_done_week), "완료한 할 일", "#16a34a"),
        (r3, f"{habit_rate}%", "습관 달성률", "#f59e0b"),
        (r4, f"{w_summary['total_min']}분", "운동 시간", "#8b5cf6"),
    ]:
        with col:
            st.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-num" style="color:{color}">{num}</div>'
                f'<div class="stat-label">{label}</div></div>',
                unsafe_allow_html=True,
            )

    st.write("")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### 📅 이번 주 일정")
        if not week_scheds:
            st.caption("이번 주 일정이 없어요.")
        for s, occ in sorted(week_scheds, key=lambda x: x[1])[:10]:
            st.markdown(
                f'<div class="today-row">'
                f'<div class="today-time">{occ.strftime("%m/%d %H:%M")}</div>'
                f'<div class="today-title">{s["title"]}</div></div>',
                unsafe_allow_html=True,
            )

        st.write("")
        st.markdown("### 🏃 이번 주 운동")
        if not w_summary["items"]:
            st.caption("이번 주 운동 기록이 없어요.")
        for w in w_summary["items"]:
            st.markdown(
                f'<div class="workout-row"><b>{w["type"]}</b> — {w["duration"]}분'
                f'{"  · " + w["note"] if w.get("note") else ""}</div>',
                unsafe_allow_html=True,
            )

    with col_b:
        st.markdown("### 🔁 이번 주 습관")
        if not habits:
            st.caption("등록된 습관이 없어요.")
        week_kr2 = ["월","화","수","목","금","토","일"]
        for h in habits:
            checks = sum(1 for d in week_dates if d in h.get("check_dates",[]))
            week_dots = "".join(
                f'<span class="habit-dot {"done" if d in h.get("check_dates",[]) else "miss"}">{week_kr2[i][0]}</span>'
                for i, d in enumerate(week_dates)
            )
            st.markdown(
                f'<div class="habit-row">'
                f'<div><b>{h["icon"]} {h["name"]}</b> <span style="font-size:0.82rem;color:#787774">({checks}/7)</span></div>'
                f'<div class="habit-week">{week_dots}</div></div>',
                unsafe_allow_html=True,
            )

        st.write("")
        st.markdown("### 💰 이번 달 가계부")
        st.markdown(
            f'<div class="summary-box">'
            f'<div style="display:flex;justify-content:space-around">'
            f'<div><div style="font-size:0.8rem;color:#787774">수입</div>'
            f'<div class="income-tag" style="font-size:1.2rem">+{month_ledger["income"]:,}원</div></div>'
            f'<div><div style="font-size:0.8rem;color:#787774">지출</div>'
            f'<div class="expense-tag" style="font-size:1.2rem">-{month_ledger["expense"]:,}원</div></div>'
            f'<div><div style="font-size:0.8rem;color:#787774">잔액</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{"#16a34a" if month_ledger["net"]>=0 else "#dc2626"}">'
            f'{month_ledger["net"]:+,}원</div></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        st.write("")
        if todos_pending:
            st.markdown(f"### ✅ 남은 할 일 ({len(todos_pending)})")
            for t in todos_pending[:5]:
                st.markdown(f'<div class="today-row">☐ {t["title"]}</div>', unsafe_allow_html=True)
            if len(todos_pending) > 5:
                st.caption(f"...외 {len(todos_pending)-5}개 더")


# ════════════════════════════════════════
#  페이지: 💰 가계부
# ════════════════════════════════════════
elif page == "💰 가계부":
    st.title("💰 가계부")
    st.caption("수입과 지출을 기록하고 월별 통계를 확인하세요.")
    st.write("")

    today = date.today()
    tab1, tab2, tab_receipt = st.tabs(["📋 내역", "➕ 추가", "📷 영수증 인식"])

    with tab_receipt:
        st.markdown("#### 📷 영수증 자동 인식")
        st.caption("영수증 사진을 올리면 AI가 읽어서 자동으로 가계부에 기록해요.")
        receipt_file = st.file_uploader(
            "영수증 사진 업로드",
            type=["jpg", "jpeg", "png", "webp"],
            label_visibility="collapsed",
        )
        if receipt_file:
            st.image(receipt_file, caption="업로드된 영수증", use_container_width=True)
            if st.button("🔍 AI로 분석하기", type="primary", use_container_width=True):
                ext = receipt_file.name.rsplit(".", 1)[-1].lower()
                mime = IMAGE_MIME.get(ext, "image/jpeg")
                with st.spinner("AI가 영수증을 읽는 중..."):
                    try:
                        receipt_file.seek(0)
                        result = analyze_receipt(receipt_file.read(), mime)
                        st.session_state.receipt_result = result
                    except Exception as e:
                        st.error(f"분석 실패: {e}")

        if "receipt_result" in st.session_state:
            r = st.session_state.receipt_result
            st.write("")
            st.success(f"✅ **{r.get('store','가게')}** — {r.get('date', today.isoformat())} / 총 {r.get('total',0):,}원")
            st.markdown("**인식된 항목**")
            items_r = r.get("items", [])
            if not items_r:
                st.caption("항목을 인식하지 못했어요.")
            else:
                for it in items_r:
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;'
                        f'padding:6px 0;border-bottom:1px solid #eee">'
                        f'<span>{it["name"]} <span style="color:#787774;font-size:0.82rem">({it.get("category","기타")})</span></span>'
                        f'<b>{it["amount"]:,}원</b></div>',
                        unsafe_allow_html=True,
                    )
                st.write("")
                add_cols = st.columns(2)
                with add_cols[0]:
                    if st.button("💾 전체 항목 가계부에 추가", type="primary", use_container_width=True):
                        r_date = r.get("date", today.isoformat())
                        for it in items_r:
                            add_ledger("expense", it.get("category","기타"),
                                       int(it["amount"]), it["name"], r_date)
                        del st.session_state.receipt_result
                        st.success(f"{len(items_r)}개 항목 추가 완료!")
                        st.rerun()
                with add_cols[1]:
                    if st.button("❌ 취소", use_container_width=True):
                        del st.session_state.receipt_result
                        st.rerun()

    with tab2:
        with st.form("add_ledger_form", clear_on_submit=True):
            l_type = st.radio("유형", ["지출", "수입"], horizontal=True)
            cats = EXPENSE_CATEGORIES if l_type == "지출" else INCOME_CATEGORIES
            l_cat = st.selectbox("카테고리", cats)
            l_amount = st.number_input("금액 (원)", min_value=0, step=100, value=0)
            l_note = st.text_input("메모 (선택)")
            l_date = st.date_input("날짜", value=today)
            if st.form_submit_button("기록하기", type="primary"):
                if l_amount > 0:
                    add_ledger("expense" if l_type == "지출" else "income",
                               l_cat, int(l_amount), l_note.strip(), l_date.isoformat())
                    st.success("기록 완료!")
                    st.rerun()
                else:
                    st.warning("금액을 입력해주세요.")

    with tab1:
        sel_year  = st.selectbox("연도", list(range(today.year, today.year-3, -1)), label_visibility="collapsed")
        sel_month = st.selectbox("월", list(range(1, 13)), index=today.month-1, label_visibility="collapsed")
        summary = ledger_monthly_summary(sel_year, sel_month)

        c1, c2, c3 = st.columns(3)
        for col, label, val, color in [
            (c1, "💚 수입", f"+{summary['income']:,}원", "#16a34a"),
            (c2, "❤️ 지출", f"-{summary['expense']:,}원", "#dc2626"),
            (c3, "💙 잔액", f"{summary['net']:+,}원", "#2383e2" if summary['net']>=0 else "#dc2626"),
        ]:
            with col:
                st.markdown(
                    f'<div class="summary-box">'
                    f'<div style="font-size:0.8rem;color:#787774">{label}</div>'
                    f'<div style="font-size:1.3rem;font-weight:700;color:{color}">{val}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.write("")
        prefix = f"{sel_year:04d}-{sel_month:02d}"
        month_items = [e for e in load_ledger() if e["date"].startswith(prefix)]
        if not month_items:
            st.caption("이 달 내역이 없어요.")
        for e in month_items:
            is_income = e["type"] == "income"
            sign = "+" if is_income else "-"
            color_cls = "income-tag" if is_income else "expense-tag"
            note_txt = f"  · {e['note']}" if e.get("note") else ""
            c1, c2 = st.columns([8, 1])
            with c1:
                st.markdown(
                    f'<div class="ledger-row">'
                    f'<div><span style="color:#787774;font-size:0.82rem">{e["date"]}  {e["category"]}</span>'
                    f'<span style="font-size:0.82rem;color:#787774">{note_txt}</span></div>'
                    f'<div class="{color_cls}">{sign}{e["amount"]:,}원</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("🗑️", key=f"del_ledger_{e['id']}"):
                    delete_ledger(e["id"])
                    st.rerun()


# ════════════════════════════════════════
#  페이지: 📚 독서 기록
# ════════════════════════════════════════
elif page == "📚 독서":
    st.title("📚 독서 기록")
    st.caption("읽고 싶은 책, 읽는 중인 책, 완독한 책을 관리하세요.")
    st.write("")

    with st.expander("➕ 책 추가", expanded=False):
        with st.form("add_book_form", clear_on_submit=True):
            b_title  = st.text_input("책 제목", placeholder="예: 정의란 무엇인가")
            b_author = st.text_input("저자 (선택)")
            b_status = st.selectbox("상태", list(BOOK_STATUS_MAP.values()))
            status_key = {v: k for k, v in BOOK_STATUS_MAP.items()}[b_status]
            if st.form_submit_button("추가", type="primary"):
                if b_title.strip():
                    add_book(b_title.strip(), b_author.strip(), status_key)
                    st.success("추가 완료!")
                    st.rerun()

    st.write("")
    books = load_books()
    status_badge = {"want": "badge-want", "reading": "badge-reading", "done": "badge-done"}

    for status_key, status_label in BOOK_STATUS_MAP.items():
        group = [b for b in books if b.get("status") == status_key]
        st.markdown(f"### {status_label} ({len(group)})")
        if not group:
            st.caption("없음")
            continue
        for b in group:
            c1, c2, c3 = st.columns([7, 2, 1])
            with c1:
                stars = "⭐" * b.get("rating", 0) if b.get("rating") else ""
                fin = f" · 완독 {b['finished_at']}" if b.get("finished_at") else ""
                st.markdown(
                    f'<div class="book-card">'
                    f'<span class="book-status-badge {status_badge[status_key]}">{status_label}</span><br>'
                    f'<b>{b["title"]}</b>'
                    f'{"  <span style=\"color:#787774;font-size:0.85rem\">· " + b["author"] + "</span>" if b.get("author") else ""}'
                    f'{"  " + stars if stars else ""}'
                    f'{"<div style=\"font-size:0.8rem;color:#787774\">" + fin + "</div>" if fin else ""}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                new_status = st.selectbox("상태변경", list(BOOK_STATUS_MAP.values()),
                                          index=list(BOOK_STATUS_MAP.keys()).index(status_key),
                                          key=f"bs_{b['id']}", label_visibility="collapsed")
                new_key = {v: k for k, v in BOOK_STATUS_MAP.items()}[new_status]
                if new_key != status_key:
                    update_book(b["id"], status=new_key)
                    st.rerun()
                if status_key == "done":
                    new_rating = st.selectbox("별점", [0,1,2,3,4,5],
                                              index=b.get("rating",0), key=f"br_{b['id']}", label_visibility="collapsed")
                    if new_rating != b.get("rating",0):
                        update_book(b["id"], rating=new_rating)
                        st.rerun()
            with c3:
                if st.button("🗑️", key=f"del_book_{b['id']}"):
                    delete_book(b["id"])
                    st.rerun()
        st.write("")


# ════════════════════════════════════════
#  페이지: 🏃 운동 기록
# ════════════════════════════════════════
elif page == "🏃 운동":
    st.title("🏃 운동 기록")
    st.caption("운동 기록을 남기고 습관을 만들어요.")
    st.write("")

    w_sum = workout_week_summary()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f'<div class="stat-card"><div class="stat-num" style="color:#8b5cf6">{w_sum["count"]}회</div>'
            f'<div class="stat-label">이번 주 운동</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="stat-card"><div class="stat-num" style="color:#8b5cf6">{w_sum["total_min"]}분</div>'
            f'<div class="stat-label">이번 주 총 운동 시간</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    with st.expander("➕ 운동 기록 추가", expanded=False):
        with st.form("add_workout_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                w_type = st.selectbox("운동 종류", WORKOUT_TYPES)
            with col2:
                w_dur  = st.number_input("시간 (분)", min_value=1, max_value=600, value=30)
            w_note = st.text_input("메모 (선택)")
            w_date = st.date_input("날짜", value=date.today())
            if st.form_submit_button("기록하기", type="primary"):
                add_workout(w_type, int(w_dur), w_note.strip(), w_date.isoformat())
                st.success("기록 완료!")
                st.rerun()

    st.write("")
    st.markdown("### 최근 운동 기록")
    workouts = load_workouts()
    if not workouts:
        st.info("아직 운동 기록이 없어요.")
    for w in workouts[:30]:
        c1, c2 = st.columns([9, 1])
        with c1:
            note_txt = f"  · {w['note']}" if w.get("note") else ""
            st.markdown(
                f'<div class="workout-row">'
                f'<span style="color:#787774;font-size:0.82rem">{w["date"]}</span>  '
                f'<b>{w["type"]}</b>  <span style="color:#8b5cf6;font-weight:600">{w["duration"]}분</span>'
                f'<span style="color:#787774;font-size:0.85rem">{note_txt}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("🗑️", key=f"del_w_{w['id']}"):
                delete_workout(w["id"])
                st.rerun()


# ════════════════════════════════════════
#  페이지: ⏱️ 포모도로 타이머
# ════════════════════════════════════════
elif page == "⏱️ 포모도로":
    st.title("⏱️ 포모도로 타이머")
    st.caption("25분 집중 → 5분 휴식. 4세션마다 15분 긴 휴식.")
    st.write("")

    @st.fragment(run_every=1)
    def pomo_display():
        # 벽 시계 기반으로 남은 시간 계산
        if st.session_state.pomo_running and st.session_state.pomo_end_wall:
            remaining = max(0.0, st.session_state.pomo_end_wall - time_module.time())
        else:
            remaining = float(st.session_state.pomo_remaining)

        # 타이머 완료 처리
        if st.session_state.pomo_running and remaining <= 0:
            if st.session_state.pomo_mode == "work":
                st.session_state.pomo_sessions += 1
                is_long = st.session_state.pomo_sessions % 4 == 0
                next_sec = POMO_LONG_BREAK_SEC if is_long else POMO_BREAK_SEC
                st.session_state.pomo_mode = "long_break" if is_long else "break"
                show_toast("⏱️ 집중 완료!", "😌 휴식할 시간이에요")
            else:
                next_sec = POMO_WORK_SEC
                st.session_state.pomo_mode = "work"
                show_toast("⏱️ 휴식 완료!", "💪 다시 집중할 시간!")
            st.session_state.pomo_remaining = next_sec
            st.session_state.pomo_end_wall = None
            st.session_state.pomo_running = False
            remaining = float(next_sec)

        mins = int(remaining) // 60
        secs = int(remaining) % 60

        mode_labels = {"work": "🔵 집중 시간", "break": "🟢 짧은 휴식", "long_break": "🟣 긴 휴식"}
        mode_label = mode_labels.get(st.session_state.pomo_mode, "집중 시간")
        mode_color = "pomo-work" if st.session_state.pomo_mode == "work" else "pomo-break"

        st.markdown(
            f'<div class="pomo-display">'
            f'<div class="pomo-timer">{mins:02d}:{secs:02d}</div>'
            f'<div class="pomo-mode {mode_color}">{mode_label}</div>'
            f'<div class="pomo-session">완료한 세션: {st.session_state.pomo_sessions}개</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    pomo_display()

    col1, col2, col3 = st.columns(3)
    with col1:
        if not st.session_state.pomo_running:
            if st.button("▶ 시작", type="primary", use_container_width=True):
                st.session_state.pomo_end_wall = time_module.time() + st.session_state.pomo_remaining
                st.session_state.pomo_running = True
                st.rerun()
        else:
            if st.button("⏸ 일시정지", use_container_width=True):
                st.session_state.pomo_remaining = max(0.0, st.session_state.pomo_end_wall - time_module.time())
                st.session_state.pomo_end_wall = None
                st.session_state.pomo_running = False
                st.rerun()
    with col2:
        if st.button("⏹ 초기화", use_container_width=True):
            st.session_state.pomo_running = False
            st.session_state.pomo_mode = "work"
            st.session_state.pomo_remaining = POMO_WORK_SEC
            st.session_state.pomo_end_wall = None
            st.rerun()
    with col3:
        if st.button("⏭ 다음 단계", use_container_width=True):
            st.session_state.pomo_running = False
            st.session_state.pomo_end_wall = None
            if st.session_state.pomo_mode == "work":
                st.session_state.pomo_sessions += 1
                is_long = st.session_state.pomo_sessions % 4 == 0
                st.session_state.pomo_mode = "long_break" if is_long else "break"
                st.session_state.pomo_remaining = POMO_LONG_BREAK_SEC if is_long else POMO_BREAK_SEC
            else:
                st.session_state.pomo_mode = "work"
                st.session_state.pomo_remaining = POMO_WORK_SEC
            st.rerun()

    st.write("")
    st.divider()
    st.markdown("**⏱️ 포모도로 방법**")
    st.markdown("""
- 🔵 **25분** 집중 작업
- 🟢 **5분** 짧은 휴식
- 4세션 완료 후 🟣 **15분** 긴 휴식
- 스마트폰, 메신저 끄고 한 가지만!
    """)


# ════════════════════════════════════════
#  페이지: 😊 기분/일기
# ════════════════════════════════════════
elif page == "😊 기분/일기":
    st.title("😊 기분/일기")
    st.caption("오늘 하루 기분을 기록하고 감정 변화를 확인하세요.")
    st.write("")

    today_str = date.today().isoformat()
    mood_data = load_mood()
    today_mood = next((m for m in mood_data if m["date"] == today_str), None)

    st.markdown("### 오늘 기분은 어때요?")
    cols = st.columns(5)
    selected_score = today_mood["score"] if today_mood else None
    for i, (emoji, label) in enumerate(zip(MOOD_EMOJIS, MOOD_LABELS)):
        with cols[i]:
            sel = "✅ " if selected_score == i + 1 else ""
            if st.button(f"{emoji}\n{sel}{label}", key=f"mood_btn_{i}", use_container_width=True):
                selected_score = i + 1

    if selected_score:
        with st.form("mood_note_form"):
            note = st.text_input("한 줄 메모 (선택)", value=today_mood.get("note","") if today_mood else "",
                                 placeholder="오늘 어떤 일이 있었나요?")
            if st.form_submit_button("💾 오늘 기분 저장", type="primary"):
                add_mood(selected_score, note.strip())
                st.success(f"{MOOD_EMOJIS[selected_score-1]} 기분 저장 완료!")
                st.rerun()

    st.write("")
    st.divider()
    st.markdown("### 📅 최근 기분 기록")
    if not mood_data:
        st.caption("아직 기록이 없어요.")
    for m in mood_data[:14]:
        c1, c2 = st.columns([9, 1])
        with c1:
            note_txt = f"  — {m['note']}" if m.get("note") else ""
            st.markdown(
                f'<div class="mood-history-item">'
                f'<span style="font-size:1.6rem">{m["emoji"]}</span>'
                f'<div><div style="font-weight:600">{MOOD_LABELS[m["score"]-1]}</div>'
                f'<div style="font-size:0.82rem;color:#787774">{m["date"]}{note_txt}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("🗑️", key=f"del_mood_{m['id']}"):
                delete_mood(m["id"])
                st.rerun()


# ════════════════════════════════════════
#  페이지: 🔗 링크 저장함
# ════════════════════════════════════════
elif page == "🔗 링크":
    st.title("🔗 링크 저장함")
    st.caption("나중에 볼 링크를 저장하세요.")
    st.write("")

    with st.expander("➕ 링크 추가", expanded=False):
        with st.form("add_link_form", clear_on_submit=True):
            l_url   = st.text_input("URL", placeholder="https://...")
            l_title = st.text_input("제목 (선택)", placeholder="비워두면 URL로 저장")
            l_cat   = st.selectbox("카테고리", LINK_CATEGORIES)
            l_note  = st.text_input("메모 (선택)")
            if st.form_submit_button("저장", type="primary"):
                if l_url.strip():
                    add_link(l_url.strip(), l_title.strip(), l_cat, l_note.strip())
                    st.success("링크 저장!")
                    st.rerun()
                else:
                    st.warning("URL을 입력해주세요.")

    st.write("")
    links = load_links()
    if not links:
        st.info("저장된 링크가 없어요.")
    else:
        cats = ["전체"] + LINK_CATEGORIES
        sel_cat = st.selectbox("카테고리 필터", cats, label_visibility="collapsed")
        filtered = links if sel_cat == "전체" else [lk for lk in links if lk["category"] == sel_cat]
        st.caption(f"{len(filtered)}개")
        for lk in filtered:
            c1, c2 = st.columns([9, 1])
            with c1:
                note_html = f'<div style="font-size:0.82rem;color:#787774">{lk["note"]}</div>' if lk.get("note") else ""
                st.markdown(
                    f'<div class="link-card">'
                    f'<span class="link-cat-badge">{lk["category"]}</span>'
                    f'<div style="font-weight:600">{lk["title"]}</div>'
                    f'<a class="link-url" href="{lk["url"]}" target="_blank">{lk["url"]}</a>'
                    f'{note_html}</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("🗑️", key=f"del_link_{lk['id']}"):
                    delete_link(lk["id"])
                    st.rerun()


# ════════════════════════════════════════
#  페이지: 🌙 수면 기록
# ════════════════════════════════════════
elif page == "🌙 수면":
    st.title("🌙 수면 기록")
    st.caption("수면 패턴을 기록하고 관리하세요.")
    st.write("")

    sleep_data = load_sleep()
    if sleep_data:
        recent7 = sleep_data[:7]
        avg_dur = sum(s["duration"] for s in recent7) / len(recent7)
        avg_q   = sum(s["quality"]  for s in recent7) / len(recent7)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f'<div class="stat-card"><div class="stat-num" style="color:#8b5cf6">{avg_dur:.1f}h</div>'
                f'<div class="stat-label">최근 7일 평균 수면</div></div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f'<div class="stat-card"><div class="stat-num" style="color:#8b5cf6">{avg_q:.1f}/5</div>'
                f'<div class="stat-label">평균 수면 만족도</div></div>',
                unsafe_allow_html=True,
            )
        st.write("")

    with st.expander("➕ 수면 기록 추가", expanded=not bool(sleep_data)):
        with st.form("add_sleep_form", clear_on_submit=True):
            s_date  = st.date_input("날짜 (자고 일어난 날)", value=date.today())
            c1, c2  = st.columns(2)
            with c1:
                s_bed  = st.time_input("취침 시각", value=time(23, 0))
            with c2:
                s_wake = st.time_input("기상 시각", value=time(7, 0))
            s_qual  = st.slider("수면 만족도", 1, 5, 3)
            s_note  = st.text_input("메모 (선택)")
            if st.form_submit_button("기록하기", type="primary"):
                add_sleep(s_date.isoformat(), s_bed.strftime("%H:%M"),
                          s_wake.strftime("%H:%M"), s_qual, s_note.strip())
                st.success("수면 기록 완료!")
                st.rerun()

    st.write("")
    st.markdown("### 수면 기록")
    quality_stars = {1:"⭐", 2:"⭐⭐", 3:"⭐⭐⭐", 4:"⭐⭐⭐⭐", 5:"⭐⭐⭐⭐⭐"}
    for s in sleep_data[:20]:
        c1, c2 = st.columns([9, 1])
        with c1:
            st.markdown(
                f'<div class="sleep-row">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span class="sleep-dur">{s["duration"]}h</span>'
                f'<span style="color:#787774;font-size:0.85rem">{quality_stars.get(s["quality"],"")}</span>'
                f'</div>'
                f'<div style="font-size:0.85rem;color:#787774">'
                f'{s["date"]}  💤 {s["bedtime"]} → ☀️ {s["wakeup"]}'
                f'{"  · " + s["note"] if s.get("note") else ""}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("🗑️", key=f"del_sl_{s['id']}"):
                delete_sleep_entry(s["id"])
                st.rerun()


# ════════════════════════════════════════
#  페이지: 💊 복약 알림
# ════════════════════════════════════════
elif page == "💊 복약알림":
    st.title("💊 복약 알림")
    st.caption("약 먹을 시간을 설정하면 알림이 자동으로 와요.")
    st.write("")

    with st.expander("➕ 복약 알림 추가", expanded=False):
        with st.form("add_med_form", clear_on_submit=True):
            m_name = st.text_input("약/루틴 이름", placeholder="예: 비타민, 혈압약")
            m_note = st.text_input("메모 (선택)")
            st.caption("복용 시각 (최대 4개)")
            tc = st.columns(4)
            med_times = []
            for i, col in enumerate(tc):
                with col:
                    t_val = col.time_input(f"시각 {i+1}", value=None, key=f"med_t{i}", label_visibility="collapsed")
                    if t_val:
                        med_times.append(t_val.strftime("%H:%M"))
            if st.form_submit_button("추가", type="primary"):
                if m_name.strip() and med_times:
                    add_med(m_name.strip(), list(set(med_times)), m_note.strip())
                    st.success("복약 알림 추가!")
                    st.rerun()
                else:
                    st.warning("이름과 시각을 최소 1개 입력해주세요.")

    st.write("")
    meds = load_meds()
    if not meds:
        st.info("등록된 복약 알림이 없어요.")
    for med in meds:
        c1, c2, c3 = st.columns([6, 2, 1])
        with c1:
            times_str = "  ".join(f"🕐 {t}" for t in sorted(med.get("times", [])))
            note_html = f'<div style="font-size:0.82rem;color:#787774">{med["note"]}</div>' if med.get("note") else ""
            status = "✅ 활성" if med.get("enabled", True) else "⏸ 비활성"
            st.markdown(
                f'<div class="item-card">'
                f'<div style="display:flex;justify-content:space-between">'
                f'<b>💊 {med["name"]}</b>'
                f'<span style="font-size:0.8rem;color:#787774">{status}</span></div>'
                f'<div style="margin-top:4px">{times_str}</div>'
                f'{note_html}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            label = "⏸ 끄기" if med.get("enabled", True) else "▶ 켜기"
            if st.button(label, key=f"tog_med_{med['id']}", use_container_width=True):
                toggle_med(med["id"])
                st.rerun()
        with c3:
            if st.button("🗑️", key=f"del_med_{med['id']}"):
                delete_med(med["id"])
                st.rerun()


# ════════════════════════════════════════
#  페이지: 📈 차트
# ════════════════════════════════════════
elif page == "📈 차트":
    st.title("📈 통계 차트")
    st.caption("기록들을 그래프로 한눈에 확인하세요.")
    st.write("")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["💰 가계부", "🏃 운동", "🔁 습관", "😊 기분", "🌙 수면"])

    with tab1:
        st.markdown("#### 이번 달 카테고리별 지출")
        today = date.today()
        prefix = f"{today.year:04d}-{today.month:02d}"
        ledger_items = [e for e in load_ledger() if e["date"].startswith(prefix) and e["type"] == "expense"]
        if not ledger_items:
            st.caption("이번 달 지출 내역이 없어요.")
        else:
            cat_sum = {}
            for e in ledger_items:
                cat_sum[e["category"]] = cat_sum.get(e["category"], 0) + e["amount"]
            df = pd.DataFrame({"카테고리": list(cat_sum.keys()), "금액": list(cat_sum.values())})
            df = df.sort_values("금액", ascending=False)
            st.bar_chart(df.set_index("카테고리"))
            total = sum(cat_sum.values())
            for cat, amt in sorted(cat_sum.items(), key=lambda x: -x[1]):
                pct = int(amt / total * 100)
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;margin:4px 0">'
                    f'<span>{cat}</span><span class="expense-tag">{amt:,}원 ({pct}%)</span></div>',
                    unsafe_allow_html=True,
                )

    with tab2:
        st.markdown("#### 최근 4주 운동 시간")
        rows = []
        for w in range(3, -1, -1):
            ref = date.today() - timedelta(weeks=w)
            mon = ref - timedelta(days=ref.weekday())
            wdates = [(mon + timedelta(days=i)).isoformat() for i in range(7)]
            total_min = sum(wk["duration"] for wk in load_workouts() if wk["date"] in wdates)
            rows.append({"주차": mon.strftime("%m/%d~"), "운동(분)": total_min})
        df = pd.DataFrame(rows)
        st.bar_chart(df.set_index("주차"))
        st.write("")
        st.markdown("#### 운동 종류별 누적")
        workouts_all = load_workouts()
        type_sum = {}
        for w in workouts_all:
            type_sum[w["type"]] = type_sum.get(w["type"], 0) + w["duration"]
        if type_sum:
            df2 = pd.DataFrame({"종류": list(type_sum.keys()), "분": list(type_sum.values())})
            st.bar_chart(df2.set_index("종류"))

    with tab3:
        st.markdown("#### 최근 14일 습관 달성 현황")
        habits = load_habits()
        if not habits:
            st.caption("등록된 습관이 없어요.")
        else:
            rows = []
            for i in range(13, -1, -1):
                d = (date.today() - timedelta(days=i)).isoformat()
                done = sum(1 for h in habits if d in h.get("check_dates", []))
                rows.append({"날짜": d[5:], "달성": done, "전체": len(habits)})
            df = pd.DataFrame(rows)
            st.bar_chart(df.set_index("날짜")[["달성", "전체"]])

    with tab4:
        st.markdown("#### 최근 30일 기분 추이")
        mood_data = load_mood()[:30]
        if not mood_data:
            st.caption("기분 기록이 없어요.")
        else:
            rows = [{"날짜": m["date"][5:], "기분(1~5)": m["score"]} for m in reversed(mood_data)]
            df = pd.DataFrame(rows)
            st.line_chart(df.set_index("날짜"))

    with tab5:
        st.markdown("#### 최근 14일 수면 시간")
        sleep_data = load_sleep()[:14]
        if not sleep_data:
            st.caption("수면 기록이 없어요.")
        else:
            rows = [{"날짜": s["date"][5:], "수면(시간)": s["duration"]} for s in reversed(sleep_data)]
            df = pd.DataFrame(rows)
            st.bar_chart(df.set_index("날짜"))
            avg = sum(s["duration"] for s in sleep_data) / len(sleep_data)
            st.caption(f"평균 수면: {avg:.1f}시간")


# ════════════════════════════════════════
#  페이지: 🤖 AI 분석
# ════════════════════════════════════════
elif page == "🤖 AI분석":
    st.title("🤖 AI 패턴 분석")
    st.caption("AI가 나의 생활 데이터를 연결해서 다른 앱은 절대 못 해주는 인사이트를 알려줘요.")
    st.write("")

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    # 상단 요약 카드
    col1, col2, col3 = st.columns(3)
    habits = load_habits()
    week_dates = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    habit_done  = sum(1 for h in habits for d in week_dates if d in h.get("check_dates", []))
    habit_total = len(habits) * 7
    with col1:
        st.markdown(
            f'<div class="stat-card"><div class="stat-num">{int(habit_done/habit_total*100) if habit_total else 0}%</div>'
            f'<div class="stat-label">이번 주 습관 달성률</div></div>',
            unsafe_allow_html=True,
        )
    w_sum = workout_week_summary()
    with col2:
        st.markdown(
            f'<div class="stat-card"><div class="stat-num">{w_sum["count"]}회</div>'
            f'<div class="stat-label">이번 주 운동</div></div>',
            unsafe_allow_html=True,
        )
    mood_today = next((m for m in load_mood() if m["date"] == today.isoformat()), None)
    with col3:
        st.markdown(
            f'<div class="stat-card"><div class="stat-num">{mood_today["emoji"] if mood_today else "—"}</div>'
            f'<div class="stat-label">오늘 기분</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    tab_basic, tab_cross = st.tabs(["📊 기본 AI 분석", "🔗 교차 분석 인사이트"])

    with tab_basic:
        st.write("")
        if st.button("🤖 AI 분석 시작하기", type="primary", use_container_width=True):
            with st.spinner("AI가 데이터를 분석 중이에요... 잠깐만요 🤔"):
                try:
                    result = generate_ai_analysis()
                    st.session_state.ai_analysis = result
                except Exception as e:
                    st.error(f"분석 중 오류: {e}")
        if "ai_analysis" in st.session_state and st.session_state.ai_analysis:
            st.write("")
            st.markdown(
                f'<div class="ai-analysis">{st.session_state.ai_analysis.replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True,
            )
            if st.button("🔄 다시 분석"):
                del st.session_state.ai_analysis
                st.rerun()

    with tab_cross:
        st.write("")
        st.markdown("#### 🔗 교차 분석 인사이트")
        st.caption("수면·기분·운동·지출 데이터를 서로 연결해서 패턴을 찾아요. 데이터가 많을수록 정확해져요!")
        st.write("")

        days_opt = st.select_slider("분석 기간", options=[7, 14, 30, 60, 90], value=30)

        if st.button("🔍 교차 분석 실행", type="primary", use_container_width=True):
            with st.spinner("데이터를 교차 분석 중이에요..."):
                daily = get_daily_data(days_opt)
                insights = calculate_cross_insights(daily)
                st.session_state.cross_insights = insights
                st.session_state.cross_narrative = generate_cross_narrative(insights)

        if "cross_insights" in st.session_state:
            insights = st.session_state.cross_insights
            if not insights:
                st.info("💡 아직 데이터가 부족해요. 수면·기분·운동·가계부를 더 기록해보세요!")
            else:
                # 인사이트 카드
                for ins in insights:
                    border_color = "#4CAF50" if ins["good"] else ("#F44336" if ins["good"] is False else "#2196F3")
                    body_html = ins['body'].replace('\n', '<br>').replace('**', '<strong>', 1)
                    body_html = body_html.replace('**', '</strong>', 1) if '<strong>' in body_html else body_html
                    import re as _re
                    body_html = _re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', ins['body'].replace('\n', '<br>'))
                    st.markdown(
                        f"""<div style="border-left:4px solid {border_color};background:#f8f9fa;
                        padding:14px 18px;border-radius:8px;margin-bottom:14px;">
                        <div style="font-size:1.05rem;font-weight:700;margin-bottom:6px;">
                        {ins['icon']} {ins['title']}</div>
                        <div style="font-size:0.92rem;color:#444;margin-bottom:8px;">{body_html}</div>
                        <div style="font-size:0.88rem;color:{border_color};font-weight:600;">💡 {ins['tip']}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

                # AI 종합 코멘트
                if st.session_state.get("cross_narrative"):
                    st.write("")
                    st.markdown("#### 🤖 AI 종합 코멘트")
                    st.markdown(
                        f'<div class="ai-analysis">{st.session_state.cross_narrative.replace(chr(10), "<br>")}</div>',
                        unsafe_allow_html=True,
                    )

            if st.button("🔄 다시 분석", key="cross_refresh"):
                del st.session_state.cross_insights
                del st.session_state.cross_narrative
                st.rerun()


# ════════════════════════════════════════
#  페이지: 📰 뉴스 피드
# ════════════════════════════════════════
elif page == "📰 뉴스":
    st.title("📰 뉴스 피드")
    st.caption("관심 키워드 최신 뉴스를 모아봐요. (사이드바에서 키워드 설정)")
    st.write("")

    cfg = load_settings()
    keywords = cfg.get("news_keywords", ["AI", "경제"])
    if not keywords:
        st.info("사이드바 → 📰 뉴스 키워드 설정에서 키워드를 추가해주세요.")
    else:
        if st.button("🔄 뉴스 새로고침", type="primary"):
            st.cache_data.clear()
        st.caption(f"키워드: {', '.join(keywords)}")
        st.write("")
        with st.spinner("뉴스 불러오는 중..."):
            news_items = fetch_news(keywords, max_per=6)
        if not news_items:
            st.warning("뉴스를 불러올 수 없어요. 인터넷 연결을 확인해주세요.")
        else:
            # 키워드별로 묶어서 표시
            for kw in keywords:
                kw_news = [n for n in news_items if n["keyword"] == kw]
                if not kw_news:
                    continue
                st.markdown(f"#### 🔍 {kw}")
                for n in kw_news:
                    st.markdown(
                        f'<div class="news-card">'
                        f'<span class="news-kw">{n["keyword"]}</span>'
                        f'<a href="{n["link"]}" target="_blank" style="text-decoration:none">'
                        f'<div class="news-title">{n["title"]}</div></a>'
                        f'<div class="news-meta">{n["pub_date"]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                st.write("")


# ════════════════════════════════════════
#  페이지: 🌐 번역
# ════════════════════════════════════════
elif page == "🌐 번역":
    st.title("🌐 번역")
    st.caption("AI가 자연스럽게 번역해드려요.")
    st.write("")

    col1, col2 = st.columns([3, 1])
    with col2:
        target_lang = st.selectbox("번역 언어", TRANS_LANGS, label_visibility="collapsed")
    with col1:
        src_text = st.text_area("번역할 텍스트 입력", height=180, placeholder="번역하고 싶은 내용을 입력하세요...", label_visibility="collapsed")

    if st.button("🌐 번역하기", type="primary", use_container_width=True):
        if src_text.strip():
            with st.spinner(f"{target_lang}로 번역 중..."):
                result = translate_text(src_text.strip(), target_lang)
                st.session_state.trans_result = result
        else:
            st.warning("텍스트를 입력해주세요.")

    if "trans_result" in st.session_state:
        st.write("")
        st.markdown(f"**{target_lang} 번역 결과**")
        st.markdown(
            f'<div class="trans-box">{st.session_state.trans_result}</div>',
            unsafe_allow_html=True,
        )
        if st.button("📋 결과를 메모에 저장"):
            add_memo(f"번역 ({target_lang})", st.session_state.trans_result, ["번역"])
            st.success("메모에 저장됐어요!")


# ════════════════════════════════════════
#  페이지: 🔗 URL 요약
# ════════════════════════════════════════
elif page == "🔗 URL요약":
    st.title("🔗 URL / 웹페이지 요약")
    st.caption("링크를 붙여넣으면 AI가 핵심 내용을 요약해드려요.")
    st.write("")

    url_input = st.text_input("URL 입력", placeholder="https://...")
    if st.button("📄 요약하기", type="primary", use_container_width=True):
        if url_input.strip():
            with st.spinner("페이지 읽는 중... (최대 10초)"):
                summary = fetch_and_summarize_url(url_input.strip())
                st.session_state.url_summary = {"url": url_input.strip(), "summary": summary}
        else:
            st.warning("URL을 입력해주세요.")

    if "url_summary" in st.session_state:
        st.write("")
        st.caption(f"🔗 {st.session_state.url_summary['url']}")
        st.markdown(
            f'<div class="trans-box">{st.session_state.url_summary["summary"]}</div>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📋 메모에 저장"):
                add_memo(
                    f"URL 요약",
                    f"{st.session_state.url_summary['url']}\n\n{st.session_state.url_summary['summary']}",
                    ["URL요약"]
                )
                st.success("메모에 저장!")
        with c2:
            if st.button("🔗 링크도 저장"):
                add_link(st.session_state.url_summary["url"], "URL 요약", "기타")
                st.success("링크 저장!")


# ════════════════════════════════════════
#  페이지: 💡 AI 일정 제안
# ════════════════════════════════════════
elif page == "💡 AI제안":
    st.title("💡 AI 일정 제안")
    st.caption("AI가 내 할일·목표·일정을 분석해서 오늘 뭘 해야 할지 알려줘요.")
    st.write("")

    today = date.today()
    col1, col2, col3 = st.columns(3)
    todos_p = [t for t in load_todos() if not t["completed"]]
    upcoming_week = get_upcoming_occurrences(within_days=7)
    goals_a = [g for g in load_goals() if not g.get("completed")]

    for col, num, label, color in [
        (col1, len(upcoming_week), "이번 주 남은 일정", "#2383e2"),
        (col2, len(todos_p),       "미완료 할일",        "#f59e0b"),
        (col3, len(goals_a),       "진행 중 목표",        "#8b5cf6"),
    ]:
        with col:
            st.markdown(
                f'<div class="stat-card"><div class="stat-num" style="color:{color}">{num}</div>'
                f'<div class="stat-label">{label}</div></div>', unsafe_allow_html=True)

    st.write("")
    if st.button("💡 오늘 뭐 해야 할지 AI한테 물어보기", type="primary", use_container_width=True):
        with st.spinner("AI가 분석 중이에요..."):
            try:
                suggestion = suggest_schedule()
                st.session_state.ai_suggestion = suggestion
                # 텔레그램으로도 전송
                send_telegram(f"💡 AI 일정 제안\n\n{suggestion[:300]}...")
            except Exception as e:
                st.error(f"오류: {e}")

    if "ai_suggestion" in st.session_state:
        st.write("")
        st.markdown(
            f'<div class="ai-analysis">'
            f'{st.session_state.ai_suggestion.replace(chr(10), "<br>")}'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("🔄 다시 제안받기"):
            del st.session_state.ai_suggestion
            st.rerun()
