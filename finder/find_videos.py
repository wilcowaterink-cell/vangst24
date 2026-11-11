#!/usr/bin/env python3
"""Vangst24 video finder.

Finds fishing videos uploaded in the last 24 hours, per world region, and
writes them to docs/data/videos.json for the website. It also writes the
fishing forecast for Dutch waters to docs/data/forecast.json and a CSV of
today's candidates to planning/ for the daily selection.

Usage:
    YOUTUBE_API_KEY=... python finder/find_videos.py      # real data
    python finder/find_videos.py --demo                     # example data, no key needed

Only the Python standard library is used, so nothing needs installing.
"""
import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "docs", "data")
PLAN_DIR = os.path.join(ROOT, "planning")
YT = "https://www.googleapis.com/youtube/v3/"

# One search per region per run. A search costs 100 of the 10,000 free daily
# quota units, so 8 regions x 8 runs a day (every 3 hours) = 6,400 units.
# The "|" means OR in a YouTube search.
REGIONS = [
    {"id": "nl", "name": "Nederland & België", "lang": "nl",
     "q": "snoek gevangen|snoekbaars vissen|karpervissen|roofvissen|zeevissen"},
    {"id": "europa", "name": "Europa & Scandinavië", "lang": "en",
     "q": "pike fishing|carp fishing|halibut norway|salmon fishing scotland|catfish ebro"},
    {"id": "noord-amerika", "name": "Noord-Amerika", "lang": "en",
     "q": "bass fishing|musky fishing|walleye fishing|tarpon fishing|salmon fishing alaska"},
    {"id": "zuid-amerika", "name": "Zuid- & Midden-Amerika", "lang": "pt",
     "q": "pesca tucunaré|pesca dourado|pesca dorado|marlin costa rica|peacock bass"},
    {"id": "afrika", "name": "Afrika", "lang": "en",
     "q": "tigerfish|nile perch fishing|fishing south africa|giant trevally fishing"},
    {"id": "midden-oosten-india", "name": "Midden-Oosten & India", "lang": "en",
     "q": "mahseer fishing|kingfish oman|fishing oman|fishing india river"},
    {"id": "azie", "name": "Azië", "lang": "en",
     "q": "snakehead fishing|mekong catfish|釣り 大物|mancing ikan|fishing thailand"},
    {"id": "oceanie", "name": "Australië & Nieuw-Zeeland", "lang": "en",
     "q": "murray cod|barramundi fishing|snapper fishing|trout fishing new zealand|marlin cairns"},
]

# Dutch fishing spots for the forecast.
SPOTS = [
    {"name": "IJsselmeer (Urk)", "lat": 52.66, "lon": 5.60},
    {"name": "Haringvliet", "lat": 51.78, "lon": 4.25},
    {"name": "Maas (Roermond)", "lat": 51.19, "lon": 5.99},
    {"name": "Noordzeekust (Scheveningen)", "lat": 52.11, "lon": 4.27},
    {"name": "Friese meren (Sneek)", "lat": 53.03, "lon": 5.66},
]

# Worldwide searches for videos that are taking off, in several languages.
# Two extra searches per run: 8 runs x 10 searches x 100 units = 8,000 of 10,000.
VIRAL_QUERIES = [
    {"q": "fishing|big fish|monster fish|pesca|angeln|pêche|vissen|釣り", "lang": None},
    {"q": "giant fish caught|record fish|shark fishing|catfish monster|fish attack lure", "lang": "en"},
]
VIRAL_HOURS = 48              # look back a bit further for viral videos
VIRAL_VIEWS_PER_HOUR = 2000   # faster than this = marked as viral
VIRAL_MIN_VIEWS = 50000
VIRAL_KEEP = 12

MIN_SECONDS = 60          # skip very short clips
PER_REGION = 12           # videos kept per region
SEARCH_RESULTS = 25       # candidates fetched per region


def get_json(url, params=None, timeout=20):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "vangst24-finder/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def iso_duration_seconds(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


# ---------------------------------------------------------------- videos

def is_viral(v):
    return v["views"] >= VIRAL_MIN_VIEWS and v["views_per_hour"] >= VIRAL_VIEWS_PER_HOUR


def search_region(region, key, since):
    return search_videos(region["q"], region["lang"], key, since)[:PER_REGION]


def search_videos(q, lang, key, since):
    params = {
        "part": "snippet", "type": "video", "q": q,
        "publishedAfter": since, "order": "viewCount",
        "maxResults": SEARCH_RESULTS, "safeSearch": "strict",
        "videoEmbeddable": "true", "key": key,
    }
    if lang:
        params["relevanceLanguage"] = lang
    found = get_json(YT + "search", params)
    ids = [it["id"]["videoId"] for it in found.get("items", [])]
    if not ids:
        return []
    details = get_json(YT + "videos", {
        "part": "snippet,statistics,contentDetails,status",
        "id": ",".join(ids), "key": key,
    })
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for v in details.get("items", []):
        secs = iso_duration_seconds(v["contentDetails"].get("duration"))
        if secs < MIN_SECONDS or not v["status"].get("embeddable", False):
            continue
        sn, st = v["snippet"], v.get("statistics", {})
        published = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        hours = max(1.0, (now - published).total_seconds() / 3600)
        views, likes = int(st.get("viewCount", 0)), int(st.get("likeCount", 0))
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        out.append({
            "id": v["id"], "title": sn["title"], "channel": sn["channelTitle"],
            "channelId": sn["channelId"], "published": sn["publishedAt"],
            "views": views, "likes": likes, "seconds": secs, "thumb": thumb,
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "views_per_hour": round(views / hours),
            # Views per hour since upload, with a bonus for likes.
            "score": round(views / hours + likes * 2 / hours, 1),
        })
        out[-1]["viral"] = is_viral(out[-1])
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def find_viral(key, now, region_videos):
    since = (now - dt.timedelta(hours=VIRAL_HOURS)).isoformat().replace("+00:00", "Z")
    pool = {v["id"]: v for vids in region_videos.values() for v in vids if v.get("viral")}
    for vq in VIRAL_QUERIES:
        try:
            for v in search_videos(vq["q"], vq["lang"], key, since):
                if v["viral"]:
                    pool.setdefault(v["id"], v)
        except Exception as e:
            print(f"  viral search failed ({e})", file=sys.stderr)
    return sorted(pool.values(), key=lambda v: v["views_per_hour"], reverse=True)[:VIRAL_KEEP]


def demo_videos():
    """Example entries so the website can be previewed without an API key."""
    examples = {
        "nl": [("Snoek van 118 cm op shad in het Haringvliet", "Voorbeeldkanaal NL", 8400),
               ("Snoekbaars op 5 m bij Urk: dropshot uitgelegd", "Voorbeeldkanaal NL", 5100),
               ("Polderbaars op topwater in november", "Voorbeeldkanaal NL", 2300)],
        "europa": [("Heilbot van 2,1 m bij Senja", "Example Channel NO", 21000),
                   ("Wintersnoek op de Ierse meren", "Example Channel IE", 6300)],
        "noord-amerika": [("Tarpon run begins in Boca Grande", "Example Channel US", 34000),
                          ("Late fall musky on the St. Lawrence", "Example Channel CA", 12000)],
        "zuid-amerika": [("Tucunaré gigante no Rio Negro", "Canal de Exemplo BR", 15000),
                         ("Dorado en el Paraná con mosca", "Canal de Ejemplo AR", 7000)],
        "afrika": [("Tigerfish on the Zambezi at sunrise", "Example Channel ZA", 9100)],
        "midden-oosten-india": [("Golden mahseer in the Cauvery", "Example Channel IN", 4800)],
        "azie": [("Giant snakehead in a Thai reservoir", "Example Channel TH", 11000),
                 ("シーバス 80cm 東京湾", "Example Channel JP", 8800)],
        "oceanie": [("Murray cod season opener, 1.1 m", "Example Channel AU", 18000),
                    ("Black marlin off Cairns", "Example Channel AU", 13500)],
    }
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    result = {}
    for rid, items in examples.items():
        vids = []
        for i, (title, ch, views) in enumerate(items):
            published = now - dt.timedelta(hours=3 + i * 5)
            hours = (now - published).total_seconds() / 3600
            vids.append({"id": "", "title": title, "channel": ch, "channelId": "",
                         "published": published.isoformat().replace("+00:00", "Z"),
                         "views": views, "likes": views // 20, "seconds": 600 + i * 120,
                         "thumb": "", "url": "", "score": round(views / hours, 1),
                         "views_per_hour": round(views / hours), "viral": False})
        result[rid] = vids
    return result


def demo_viral():
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    rows = [("Giant catfish pulls kayak across the river", "Example Channel ES", 2400000, 20),
            ("Shark steals tuna right at the boat", "Example Channel ZA", 1300000, 30),
            ("Kid lands a 1 m pike from the shore", "Voorbeeldkanaal NL", 640000, 26),
            ("Marlin jumps INTO the boat", "Example Channel CR", 980000, 40)]
    out = []
    for title, ch, views, h in rows:
        published = now - dt.timedelta(hours=h)
        out.append({"id": "", "title": title, "channel": ch, "channelId": "",
                    "published": published.isoformat().replace("+00:00", "Z"),
                    "views": views, "likes": views // 25, "seconds": 75, "thumb": "", "url": "",
                    "score": round(views / h, 1), "views_per_hour": round(views / h), "viral": True})
    return out


# ---------------------------------------------------------------- forecast

def beaufort(kmh):
    limits = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
    return next((i for i, lim in enumerate(limits) if kmh < lim), 12)


def moon_phase(when):
    """Fraction of the lunar cycle: 0 = new moon, 0.5 = full moon."""
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
    days = (when - ref).total_seconds() / 86400
    return (days / 29.530588853) % 1.0


def moon_name(p):
    names = ["Nieuwe maan", "Wassende sikkel", "Eerste kwartier", "Wassende maan",
             "Volle maan", "Afnemende maan", "Laatste kwartier", "Afnemende sikkel"]
    return names[int((p * 8) + 0.5) % 8]


def bite_score(pressure_change, bft, cloud, moon):
    """Rule-of-thumb score from 0 to 10 for predator fishing. Not science."""
    s = 5.0
    if pressure_change <= -2: s += 2          # falling pressure: fish feed
    elif pressure_change >= 4: s -= 1.5       # fast rising pressure: slow
    if 2 <= bft <= 4: s += 1                  # some ripple on the water
    elif bft >= 6: s -= 2                     # too rough
    if cloud >= 60: s += 1                    # overcast: predators bolder
    if min(moon, 1 - moon) < 0.07 or abs(moon - 0.5) < 0.07: s += 0.5
    return max(0, min(10, round(s, 1)))


def forecast():
    now = dt.datetime.now(dt.timezone.utc)
    moon = moon_phase(now)
    spots = []
    for spot in SPOTS:
        try:
            d = get_json("https://api.open-meteo.com/v1/forecast", {
                "latitude": spot["lat"], "longitude": spot["lon"],
                "hourly": "temperature_2m,pressure_msl,wind_speed_10m,wind_direction_10m,cloud_cover",
                "past_days": 1, "forecast_days": 1, "timezone": "UTC",
            })
        except Exception as e:  # keep going if one spot fails
            print(f"  forecast {spot['name']}: {e}", file=sys.stderr)
            continue
        h = d["hourly"]
        times = [dt.datetime.fromisoformat(t).replace(tzinfo=dt.timezone.utc) for t in h["time"]]
        i = min(range(len(times)), key=lambda k: abs((times[k] - now).total_seconds()))
        j = max(0, i - 24)
        change = h["pressure_msl"][i] - h["pressure_msl"][j]
        bft = beaufort(h["wind_speed_10m"][i])
        spots.append({
            "name": spot["name"], "temp": round(h["temperature_2m"][i], 1),
            "pressure": round(h["pressure_msl"][i]), "pressure_change": round(change, 1),
            "bft": bft, "wind_dir": compass(h["wind_direction_10m"][i]),
            "cloud": h["cloud_cover"][i],
            "score": bite_score(change, bft, h["cloud_cover"][i], moon),
        })
    return {"moon": moon_name(moon), "moon_phase": round(moon, 3), "spots": spots}


def demo_forecast():
    moon = moon_phase(dt.datetime.now(dt.timezone.utc))
    rows = [("IJsselmeer (Urk)", 9.1, 1006, -3.2, 3, "ZW", 85),
            ("Haringvliet", 9.8, 1007, -2.6, 4, "ZW", 70),
            ("Maas (Roermond)", 8.2, 1009, -1.4, 2, "Z", 90),
            ("Noordzeekust (Scheveningen)", 10.4, 1006, -3.0, 5, "ZW", 60),
            ("Friese meren (Sneek)", 8.7, 1005, -3.5, 3, "W", 80)]
    spots = [{"name": n, "temp": t, "pressure": p, "pressure_change": c, "bft": b,
              "wind_dir": wd, "cloud": cl, "score": bite_score(c, b, cl, moon)}
             for n, t, p, c, b, wd, cl in rows]
    return {"moon": moon_name(moon), "moon_phase": round(moon, 3), "spots": spots}


def compass(deg):
    return ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"][int((deg % 360) / 45 + 0.5) % 8]


# ---------------------------------------------------------------- output

def write_planning_csv(regions, viral, stamp):
    os.makedirs(PLAN_DIR, exist_ok=True)
    path = os.path.join(PLAN_DIR, f"kandidaten-{stamp:%Y-%m-%d}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["datum", "regio", "rang", "titel", "kanaal", "link", "views",
                    "geupload", "score", "viraal", "gekozen", "toestemming"])
        groups = [("Viraal", viral)] + [(r["name"], r["videos"]) for r in regions]
        for name, vids in groups:
            for n, v in enumerate(vids, 1):
                w.writerow([f"{stamp:%Y-%m-%d}", name, n, v["title"], v["channel"],
                            v["url"], v["views"], v["published"], v["score"],
                            "ja" if v.get("viral") else "", "", "onbekend"])
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", action="store_true", help="write example data, no API key needed")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    demo = args.demo or not key
    if demo and not args.demo:
        print("No YOUTUBE_API_KEY set: writing example data instead.", file=sys.stderr)

    if demo:
        by_region = demo_videos()
        viral = demo_viral()
    else:
        since = (now - dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z")
        by_region = {}
        for r in REGIONS:
            try:
                by_region[r["id"]] = search_region(r, key, since)
                print(f"  {r['name']}: {len(by_region[r['id']])} videos")
            except Exception as e:
                print(f"  {r['name']}: failed ({e})", file=sys.stderr)
                by_region[r["id"]] = []
        viral = find_viral(key, now, by_region)
        print(f"  Viraal: {len(viral)} videos")

    regions = [{"id": r["id"], "name": r["name"], "videos": by_region.get(r["id"], [])}
               for r in REGIONS]
    os.makedirs(DATA_DIR, exist_ok=True)
    stamp = now.isoformat().replace("+00:00", "Z")
    with open(os.path.join(DATA_DIR, "videos.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, "demo": demo, "viral": viral, "regions": regions}, f,
                  ensure_ascii=False, indent=1)

    fc = demo_forecast() if args.demo else forecast()
    if not fc["spots"] and not args.demo:
        print("Forecast unavailable; keeping previous forecast.json.", file=sys.stderr)
    else:
        fc.update({"generated_at": stamp, "demo": args.demo})
        with open(os.path.join(DATA_DIR, "forecast.json"), "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False, indent=1)

    csv_path = write_planning_csv(regions, viral, now)
    total = sum(len(r["videos"]) for r in regions)
    print(f"Done: {total} videos{' (example data)' if demo else ''}. Planning list: {csv_path}")


if __name__ == "__main__":
    main()
