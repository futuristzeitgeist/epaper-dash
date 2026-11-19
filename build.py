"""
build the e-paper dashboard page.

pulls:
  - today list (google keep, via gkeepapi)
  - weather + uv for brooklyn (open-meteo, no key needed)
  - exercise for the weekday + morning routine (config.yaml or keep)

writes a static 800x480 html page to ./site/<DASH_PATH>/index.html

usage:
  python build.py            # real data (needs KEEP_EMAIL + KEEP_MASTER_TOKEN env vars)
  python build.py --mock     # fake data, for previewing the layout
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
TZ = ZoneInfo(CFG["location"]["timezone"])
NOW = datetime.now(TZ)
if os.environ.get("DASH_NOW"):  # for testing other dates/times
    NOW = datetime.fromisoformat(os.environ["DASH_NOW"]).replace(tzinfo=TZ)

def secret(name):
    """read a secret, forgiving "NAME value" or "NAME=value" pasted into the value box."""
    v = (os.environ.get(name) or "").strip()
    return v.replace("=", " ").split()[-1] if v else ""


DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]


# ---------- reading the keep note ----------
#
# the note looks like:
#
#   ongoing: finish the bench
#   remember: drink water
#
#   thursday 11/19
#   kickoff call 10am
#   remember: bring the charger
#
#   friday
#   laundry
#
# "ongoing:" lines show every day at the bottom, wherever they are.
# lines above the first day header show every day.
# everything else shows only under today's header.
# "remember:" lines get bolded.

MONTH_RE = r"(?:" + "|".join(MONTHS) + r")[a-z]*\.?"
DAY_RE = r"(?:" + "|".join(DAYS) + r")[a-z]*\.?"
HEADER = re.compile(
    r"^(?P<wd>" + DAY_RE + r")?[\s,]*"
    r"(?:(?P<m>\d{1,2})[/.](?P<d>\d{1,2})(?:[/.]\d{2,4})?"
    r"|(?P<mw>" + MONTH_RE + r")\s+(?P<dw>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*\d{4})?)?"
    r"\s*[:\-]?$",
    re.I,
)
ONGOING = re.compile(r"^(?:ongoing|ongoing?)\s*:\s*", re.I)
REMEMBER = re.compile(r"^remember\s*:\s*", re.I)


def parse_header(line):
    """if the line is a day header, return (weekday_index or None, (month, day) or None)."""
    m = HEADER.match(line.strip())
    if not m or not line.strip():
        return None
    wd = DAYS.index(m["wd"][:3].lower()) if m["wd"] else None
    date = None
    if m["m"]:
        date = (int(m["m"]), int(m["d"]))
    elif m["mw"]:
        date = (MONTHS.index(m["mw"][:3].lower()) + 1, int(m["dw"]))
    if wd is None and date is None:
        return None
    return wd, date


def header_is_today(hdr, today):
    wd, date = hdr
    if date:  # a date wins over a weekday name
        return date == (today.month, today.day)
    return wd == today.weekday()


def parse_today_note(lines, today=None):
    """lines: list of (text, checked). returns (ongoing, items) where items are dicts."""
    today = today or NOW.date()
    ongoing, items = [], []
    section = "top"  # "top", "today", or "other"
    for text, checked in lines:
        text = text.strip().lstrip("-*•").strip()
        if not text:
            continue
        hdr = parse_header(text)
        if hdr:
            section = "today" if header_is_today(hdr, today) else "other"
            continue
        if checked:
            continue
        if m := ONGOING.match(text):
            ongoing.append(text[m.end():])
            continue
        if section == "other":
            continue
        if m := REMEMBER.match(text):
            items.append({"text": text[m.end():], "bold": True})
        else:
            items.append({"text": text, "bold": False})
    return ongoing, items


# ---------- google keep ----------

_keep = None


def keep_client():
    global _keep
    if _keep is None:
        import gkeepapi
        _keep = gkeepapi.Keep()
        _keep.authenticate(secret("KEEP_EMAIL"), secret("KEEP_MASTER_TOKEN"))
    return _keep


def keep_note(title):
    """(text, checked) for every line of the keep note with this title (case-insensitive)."""
    keep = keep_client()
    want = title.strip().lower()
    for note in keep.all():
        if note.trashed or note.archived or note.title.strip().lower() != want:
            continue
        if hasattr(note, "items"):  # checklist
            return [(i.text, i.checked) for i in note.items]
        return [(ln, False) for ln in note.text.splitlines()]
    print(f"warning: no keep note titled {title!r}", file=sys.stderr)
    return []


def keep_lines(title):
    return [t.strip(" -*\t") for t, c in keep_note(title) if not c and t.strip(" -*\t")]


# ---------- weather ----------

WMO = {
    0: ("clear", "sun"), 1: ("mostly clear", "sun"), 2: ("partly cloudy", "partly"),
    3: ("cloudy", "cloud"), 45: ("fog", "fog"), 48: ("fog", "fog"),
    51: ("light drizzle", "rain"), 53: ("drizzle", "rain"), 55: ("heavy drizzle", "rain"),
    56: ("freezing drizzle", "rain"), 57: ("freezing drizzle", "rain"),
    61: ("light rain", "rain"), 63: ("rain", "rain"), 65: ("heavy rain", "rain"),
    66: ("freezing rain", "rain"), 67: ("freezing rain", "rain"),
    71: ("light snow", "snow"), 73: ("snow", "snow"), 75: ("heavy snow", "snow"),
    77: ("snow grains", "snow"), 80: ("showers", "rain"), 81: ("showers", "rain"),
    82: ("heavy showers", "rain"), 85: ("snow showers", "snow"), 86: ("snow showers", "snow"),
    95: ("thunderstorm", "storm"), 96: ("thunderstorm", "storm"), 99: ("thunderstorm", "storm"),
}


def uv_label(v):
    if v < 3:
        return "low"
    if v < 6:
        return "moderate"
    if v < 8:
        return "high"
    if v < 11:
        return "very high"
    return "extreme"


def fmt_hour(h):
    return f"{h % 12 or 12}{'a' if h < 12 else 'p'}"


def fmt_time(dt):
    return f"{dt.hour % 12 or 12}:{dt.minute:02d}{'a' if dt.hour < 12 else 'p'}"


def get_weather():
    loc = CFG["location"]
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        "&current=temperature_2m,apparent_temperature,weather_code,uv_index,wind_speed_10m"
        "&hourly=uv_index,temperature_2m,precipitation_probability"
        "&daily=temperature_2m_max,temperature_2m_min,uv_index_max,"
        "precipitation_probability_max,sunrise,sunset,weather_code"
        "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&timezone={loc['timezone']}&forecast_days=1"
    )
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def shape_weather(w):
    cur, day, hr = w["current"], w["daily"], w["hourly"]
    hours = [datetime.fromisoformat(t).hour for t in hr["time"]]
    uv_hourly = [round(v or 0, 1) for v in hr["uv_index"]]

    # uv strip: 6a to 8p
    strip = [{"h": h, "label": fmt_hour(h) if h % 3 == 0 else "", "v": uv_hourly[i],
              "now": h == NOW.hour}
             for i, h in enumerate(hours) if 6 <= h <= 20]

    uv_max = round(day["uv_index_max"][0] or 0, 1)
    peak_h = hours[uv_hourly.index(max(uv_hourly))] if uv_max > 0 else None
    over3 = [h for h, v in zip(hours, uv_hourly) if v >= 3]
    if over3:
        uv_tip = f"uv 3+ from {fmt_hour(over3[0])} to {fmt_hour(over3[-1] + 1)}. sunscreen."
    else:
        uv_tip = "uv stays low today."

    desc, icon = WMO.get(cur["weather_code"], ("", "cloud"))
    # next few hours of temp + rain
    upcoming = []
    for i, h in enumerate(hours):
        if h > NOW.hour and len(upcoming) < 4 and (h - NOW.hour) % 3 == 0:
            upcoming.append({"label": fmt_hour(h), "t": round(hr["temperature_2m"][i]),
                             "rain": hr["precipitation_probability"][i] or 0})

    return {
        "temp": round(cur["temperature_2m"]),
        "feels": round(cur["apparent_temperature"]),
        "desc": desc,
        "icon": icon,
        "wind": round(cur["wind_speed_10m"]),
        "hi": round(day["temperature_2m_max"][0]),
        "lo": round(day["temperature_2m_min"][0]),
        "rain": day["precipitation_probability_max"][0] or 0,
        "sunrise": fmt_time(datetime.fromisoformat(day["sunrise"][0])),
        "sunset": fmt_time(datetime.fromisoformat(day["sunset"][0])),
        "uv_now": round(cur.get("uv_index") or 0, 1),
        "uv_now_label": uv_label(cur.get("uv_index") or 0),
        "uv_max": uv_max,
        "uv_max_label": uv_label(uv_max),
        "uv_peak": fmt_hour(peak_h) if peak_h is not None else "",
        "uv_tip": uv_tip,
        "uv_strip": strip,
        "uv_scale": max(8, max(s["v"] for s in strip) if strip else 8),
        "upcoming": upcoming,
    }


# ---------- exercise + routine ----------

def get_exercise():
    """list of {"name", "groups": [{"label", "items"}]} for today."""
    sched = CFG.get("schedule", {}).get(DAYS[NOW.weekday()], [])
    sched = sched if isinstance(sched, list) else [sched]
    workouts = {k.lower(): v for k, v in (CFG.get("workouts") or {}).items()}
    out = []
    for name in sched:
        groups = workouts.get(str(name).lower(), [])
        out.append({"name": str(name), "groups": groups})
    return out


AFFIRMATIONS = [
    "you're doing more than you think.",
    "rest counts as progress.",
    "small steps still get you there.",
    "done is better than perfect.",
    "you don't have to earn a slow morning.",
    "the plan can change. you're still on track.",
    "be as nice to yourself as you are to your friends.",
    "drink water. you're basically a houseplant with opinions.",
    "one thing at a time.",
    "you've gotten through every hard day so far.",
    "it's ok to do the easy version today.",
    "future you says thanks.",
]


def affirmation():
    pool = CFG.get("affirmations") or AFFIRMATIONS
    return str(pool[NOW.timetuple().tm_yday % len(pool)])


def get_life():
    """list of {"text", "tag"} for today. items with every: N only show every N days."""
    note = CFG["keep"].get("routine_note")
    if note:
        return [{"text": t, "tag": ""} for t in keep_lines(note)]
    out = []
    for it in CFG.get("life", []):
        if isinstance(it, str):
            it = {"text": it}
        every = it.get("every")
        if every:
            start = it.get("start", NOW.date())
            if isinstance(start, str):
                start = datetime.fromisoformat(start).date()
            if (NOW.date() - start).days % int(every):
                continue
        out.append({"text": it["text"], "tag": it.get("tag", "")})
    return out


def get_today():
    return parse_today_note(keep_note(CFG["keep"]["today_note"]))


# ---------- birds ----------
#
# recent sightings near you from ebird (free key: https://ebird.org/api/keygen).
# without a key it falls back to the list in config.yaml.

SKIP_BIRD = re.compile(r"\bsp\.|/| x |hybrid|domestic", re.I)


def http_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "epaper-dash/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def bird_photo(*names):
    """a photo url from the bird's wikipedia page, or None."""
    for n in names:
        try:
            d = http_json("https://en.wikipedia.org/api/rest_v1/page/summary/"
                          + urllib.parse.quote(n.replace(" ", "_")))
        except Exception:
            continue
        if d.get("thumbnail"):
            return re.sub(r"/\d+px-", "/480px-", d["thumbnail"]["source"])
    return None


def ago(dt_str):
    days = (NOW.date() - datetime.fromisoformat(dt_str[:10]).date()).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def get_birds():
    bcfg = CFG.get("birds", {})
    key = secret("EBIRD_KEY")
    if not key:
        names = bcfg.get("fallback", [])
        if not names:
            return None
        feat = names[NOW.timetuple().tm_yday % len(names)]
        return {"featured": {"name": feat, "sci": "", "where": "", "when": "", "rare": False,
                             "photo": bird_photo(feat)},
                "around": [n for n in names if n != feat]}

    loc = CFG["location"]
    q = f"lat={loc['lat']}&lng={loc['lon']}&dist={bcfg.get('radius_km', 5)}&back={bcfg.get('days', 3)}"
    hdr = {"X-eBirdApiToken": key}
    obs = http_json(f"https://api.ebird.org/v2/data/obs/geo/recent?{q}", hdr)
    obs = [o for o in obs if not SKIP_BIRD.search(o["comName"])]
    obs.sort(key=lambda o: -(o.get("howMany") or 1))
    try:
        notable = http_json(f"https://api.ebird.org/v2/data/obs/geo/recent/notable?{q}", hdr)
        notable = [o for o in notable if not SKIP_BIRD.search(o["comName"])]
    except Exception:
        notable = []

    if notable:  # something unusual nearby gets the spotlight
        f, rare = notable[0], True
    else:  # otherwise rotate daily, skipping the 3 most common (pigeons etc.)
        pool = obs[3:] or obs
        f, rare = (pool[NOW.timetuple().tm_yday % len(pool)] if pool else None), False
    featured = None
    if f:
        featured = {"name": f["comName"].lower(), "sci": f["sciName"], "where": f["locName"],
                    "when": ago(f["obsDt"]), "rare": rare,
                    "photo": bird_photo(f["comName"], f["sciName"])}
    around = [o["comName"].lower() for o in obs
              if not f or o["comName"] != f["comName"]][: bcfg.get("max_list", 12)]
    return {"featured": featured, "around": around, "count": len(obs)}


# ---------- mock data ----------

def mock():
    hours = list(range(24))
    uv = [0] * 7 + [0.3, 0.9, 1.6, 2.3, 2.8, 3.1, 2.9, 2.3, 1.5, 0.8, 0.2] + [0] * 6
    w = {
        "current": {"temperature_2m": 47.3, "apparent_temperature": 42.1, "weather_code": 2,
                    "uv_index": uv[NOW.hour], "wind_speed_10m": 9.4},
        "hourly": {"time": [f"{NOW.date()}T{h:02d}:00" for h in hours], "uv_index": uv,
                   "temperature_2m": [38 + 10 * max(0, 1 - abs(h - 14) / 8) for h in hours],
                   "precipitation_probability": [5] * 15 + [20, 35, 40] + [25] * 6},
        "daily": {"temperature_2m_max": [51.2], "temperature_2m_min": [38.4], "uv_index_max": [3.1],
                  "precipitation_probability_max": [40], "weather_code": [2],
                  "sunrise": [f"{NOW.date()}T06:49"], "sunset": [f"{NOW.date()}T16:33"]},
    }
    note = [
        ("ongoing: finish the bookcase bench", False),
        ("ongoing: call the landlord about the radiator", False),
        ("remember: you can only do so much in a day", False),
        ("wednesday 11/18", False), ("old thing from yesterday", False),
        (f"{NOW.strftime('%A').lower()} {NOW.month}/{NOW.day}", False),
        ("kickoff call 10am", False), ("pick up package from the post office", False),
        ("remember: bring the charger", False), ("laundry", True),
        ("dinner w/ friends 7:30", False),
        ("saturday", False), ("farmers market", False),
    ]
    ongoing, today = parse_today_note(note)
    birds = {"featured": {"name": "red-tailed hawk", "sci": "Buteo jamaicensis",
                          "where": "Green-Wood Cemetery", "when": "yesterday", "rare": False,
                          "photo": None},
             "around": ["house sparrow", "european starling", "rock pigeon", "blue jay",
                        "northern cardinal", "white-throated sparrow", "dark-eyed junco",
                        "american robin", "mourning dove", "downy woodpecker",
                        "northern mockingbird", "ring-billed gull"], "count": 41}
    return shape_weather(w), ongoing, today, get_exercise(), get_life(), birds


# ---------- render ----------

def main():
    if "--mock" in sys.argv:
        weather, ongoing, today, exercise, routine, birds = mock()
    else:
        try:
            weather = shape_weather(get_weather())
        except Exception as e:  # keep the screen useful even if weather fails
            print(f"weather failed: {e}", file=sys.stderr)
            weather = None
        if not secret("KEEP_MASTER_TOKEN"):
            ongoing, today = [], None  # keep not set up: the template shows an affirmation
        else:
            try:
                ongoing, today = get_today()
            except Exception as e:
                print(f"keep failed: {e}", file=sys.stderr)
                ongoing, today = [], [{"text": "(couldn't reach google keep)", "bold": False}]
        exercise, routine = get_exercise(), get_life()
        try:
            birds = get_birds()
        except Exception as e:
            print(f"ebird failed ({e}), using the fallback list", file=sys.stderr)
            os.environ["EBIRD_KEY"] = ""
            birds = get_birds()

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
    html = env.get_template(CFG["display"].get("template", "field.html")).render(
        cfg=CFG,
        weekday=NOW.strftime("%A").lower(),
        date=f"{MONTHS[NOW.month - 1]} {NOW.day}",
        updated=fmt_time(NOW),
        weather=weather,
        ongoing=ongoing,
        today=today,
        exercise=exercise,
        life=routine,
        affirmation=affirmation(),
        birds=birds,
    )

    path = secret("DASH_PATH").strip("/")
    out = ROOT / "site" / path
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html)
    if path:  # blank page at the root so the real one isn't easy to stumble on
        (ROOT / "site" / "index.html").write_text("<!doctype html><title>.</title>")
    print(f"wrote {out / 'index.html'}")


if __name__ == "__main__":
    main()
