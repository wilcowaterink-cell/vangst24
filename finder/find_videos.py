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

# Regions shown on the site.
REGIONS = [
    {"id": "nl", "name": "Nederland & België"},
    {"id": "west-europa", "name": "West-Europa"},
    {"id": "scandinavie", "name": "Scandinavië"},
    {"id": "zuid-europa", "name": "Zuid-Europa"},
    {"id": "oost-europa", "name": "Oost-Europa"},
    {"id": "noord-amerika", "name": "Noord-Amerika"},
    {"id": "zuid-amerika", "name": "Zuid- & Midden-Amerika"},
    {"id": "afrika", "name": "Afrika"},
    {"id": "midden-oosten-india", "name": "Midden-Oosten & India"},
    {"id": "azie", "name": "Azië"},
    {"id": "oceanie", "name": "Australië & Nieuw-Zeeland"},
]

# The searches. In a YouTube search "|" means OR and only joins the words right
# next to it, so "fishing bass|pike" means: fishing AND (bass OR pike).
# Each search costs 100 of the 10,000 free daily units: 11 searches x 8 runs
# a day (every 3 hours) = 8,800 units.
# "region" is where a video goes when the maker's country is unknown.
SEARCHES = [
    {"q": "vissen|snoek|snoekbaars|karper|hengelsport|roofvissen|karpervissen|zeevissen", "lang": "nl", "region": "nl"},
    {"q": "fishing bass|pike|carp|trout|salmon|walleye|musky|catfish", "lang": "en", "region": "noord-amerika"},
    {"q": "fishing tuna|marlin|shark|tarpon|snapper|halibut|kingfish|trevally", "lang": "en", "region": "noord-amerika"},
    {"q": "angeln|pêche|fiske|kalastus|sportfiske|havfiske|lystfiskeri|carpfishing", "lang": None, "region": "west-europa"},
    {"q": "wędkarstwo|pescuit|rybolov|рыбалка|horgászat|ribolov|риболов|žvejyba", "lang": None, "region": "oost-europa"},
    {"q": "pesca tucunaré|dourado|robalo|dorado|pargo|atún|trucha|tilapia", "lang": None, "region": "zuid-amerika"},
    {"q": "釣り|낚시|ตกปลา|mancing|钓鱼|memancing", "lang": None, "region": "azie"},
    {"q": "fishing mahseer|india|kerala|oman|dubai|pakistan|bangladesh", "lang": None, "region": "midden-oosten-india"},
    {"q": "fishing africa|zambezi|tigerfish|namibia|kenya|nigeria|mozambique|tanzania", "lang": None, "region": "afrika"},
    {"q": "fishing australia|queensland|barramundi|murray|zealand|tasmania|darwin", "lang": "en", "region": "oceanie"},
]
# One extra worldwide search over a longer period, for videos that are taking off.
VIRAL_SEARCH = {"q": "fishing|pesca|angeln|pêche|vissen|釣り|рыбалка", "lang": None, "region": None}

# Maker's country -> region.
COUNTRY_REGION = {}
for _rid, _codes in {
    "nl": "NL BE",
    "west-europa": "GB IE FR DE CH AT LU",
    "scandinavie": "DK SE NO FI IS",
    "zuid-europa": "ES PT IT GR MT CY",
    "oost-europa": "PL CZ SK HU RO BG HR SI RS BA ME MK AL EE LV LT UA BY MD RU",
    "noord-amerika": "US CA",
    "zuid-amerika": "MX BR AR CL CO PE CR PA EC VE UY PY BO GT CU DO PR HN NI SV BZ JM TT BS",
    "afrika": "ZA NA KE NG GH TZ MZ ZM ZW EG MA DZ TN UG ET SN CI CM AO BW MG MU SC RW",
    "midden-oosten-india": "IN PK BD LK NP MV AE OM SA QA KW BH IR IQ IL JO LB TR",
    "azie": "JP KR CN TW HK TH VN ID MY PH SG KH LA MM MN KZ UZ",
    "oceanie": "AU NZ FJ PG",
}.items():
    for _c in _codes.split():
        COUNTRY_REGION[_c] = _rid

# Keep out things that are not real fishing: games, music, live streams, cartoons.
BLOCKED_CATEGORIES = {"10", "20", "25"}    # Music, Gaming, News
BLOCKED_WORDS = ["roblox", "minecraft", "fortnite", "gta", "gameplay", "simulator", "fisch ",
                 "cartoon", "nursery", "lyrics", "asmr", "live stream", "livestream", "🔴",
                 "aquarium", "mukbang", "recipe", "cooking", "anime", "lego", "playstation",
                 "xbox", "nintendo", "pokemon", "pokémon", "stardew", "wow classic", "genshin"]
# A video must mention fishing in its title or tags, in any of these languages.
FISHING_WORDS = ["fishing", "fisher", "angler", "angling", "vissen", "visser", "hengel", "snoek",
                 "karper", "baars", "meerval", "steur", "roofvis", "angeln", "angler", "zander",
                 "hecht", "karpfen", "pêche", "pesca", "pescar", "fiske", "wędkar", "pescuit",
                 "rybolov", "kalastus", "рыбал", "釣", "낚시", "ตกปลา", "mancing", "钓", "câu cá",
                 "cauca", "मछली", "মাছ", "bass", "pike", "carp", "trout", "salmon", "walleye",
                 "musky", "catfish", "tuna", "marlin", "tarpon", "barramundi", "trevally", "lure"]

MAX_SECONDS = 3 * 3600                     # longer is almost always a (former) live stream

# Dutch fishing spots for the forecast.
SPOTS = [
    {"name": "IJsselmeer (Urk)", "lat": 52.66, "lon": 5.60},
    {"name": "Haringvliet", "lat": 51.78, "lon": 4.25},
    {"name": "Maas (Roermond)", "lat": 51.19, "lon": 5.99},
    {"name": "Noordzeekust (Scheveningen)", "lat": 52.11, "lon": 4.27},
    {"name": "Friese meren (Sneek)", "lat": 53.03, "lon": 5.66},
    {"name": "IJssel (Deventer)", "lat": 52.25, "lon": 6.16},
    {"name": "Twentekanaal (Hengelo)", "lat": 52.26, "lon": 6.79},
    {"name": "Vecht (Ommen)", "lat": 52.52, "lon": 6.42},
]

VIRAL_HOURS = 48              # look back a bit further for viral videos
VIRAL_VIEWS_PER_HOUR = 2000   # faster than this = marked as viral
VIRAL_MIN_VIEWS = 50000
VIRAL_KEEP = 12

MIN_SECONDS = 60          # skip very short clips
PER_REGION = 12           # videos kept per region
SEARCH_RESULTS = 50       # candidates fetched per search
VIRAL_MIN_SECONDS = 20    # viral clips are often short


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


def is_fishing_video(v):
    """False for games, music, live streams and other things that only mention fish."""
    sn = v["snippet"]
    if sn.get("categoryId") in BLOCKED_CATEGORIES:
        return False
    if sn.get("liveBroadcastContent", "none") != "none":
        return False
    text = (sn.get("title", "") + " " + " ".join(sn.get("tags", [])[:25])).lower()
    if any(w in text for w in BLOCKED_WORDS):
        return False
    return any(w in text for w in FISHING_WORDS)


def region_from_script(title):
    """Guess a region from the alphabet of the title, for makers with no country set."""
    for ch in title:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF or 0x0E00 <= o <= 0x0E7F:
            return "azie"                      # Japanese, Chinese, Korean, Thai
        if 0x1EA0 <= o <= 0x1EF9 or ch in "ơưăđƠƯĂĐ":
            return "azie"                      # Vietnamese
        if 0x0900 <= o <= 0x0DFF or 0x0600 <= o <= 0x06FF:
            return "midden-oosten-india"       # Indian scripts, Arabic
        if 0x0400 <= o <= 0x04FF:
            return "oost-europa"               # Cyrillic
    return None


def chunks(items, n=50):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def search_ids(search, key, since):
    params = {
        "part": "id", "type": "video", "q": search["q"],
        "publishedAfter": since, "order": "viewCount",
        "maxResults": SEARCH_RESULTS, "safeSearch": "strict",
        "videoEmbeddable": "true", "key": key,
    }
    if search.get("lang"):
        params["relevanceLanguage"] = search["lang"]
    found = get_json(YT + "search", params)
    return [it["id"]["videoId"] for it in found.get("items", [])]


def video_details(ids, key, now, min_seconds):
    out = []
    for part in chunks(ids):
        details = get_json(YT + "videos", {
            "part": "snippet,statistics,contentDetails,status",
            "id": ",".join(part), "key": key,
        })
        for v in details.get("items", []):
            secs = iso_duration_seconds(v["contentDetails"].get("duration"))
            if not (min_seconds <= secs <= MAX_SECONDS):
                continue
            if not v["status"].get("embeddable", False) or not is_fishing_video(v):
                continue
            sn, st = v["snippet"], v.get("statistics", {})
            published = dt.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
            hours = max(1.0, (now - published).total_seconds() / 3600)
            views, likes = int(st.get("viewCount", 0)), int(st.get("likeCount", 0))
            thumbs = sn.get("thumbnails", {})
            thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
            item = {
                "id": v["id"], "title": sn["title"], "channel": sn["channelTitle"],
                "channelId": sn["channelId"], "published": sn["publishedAt"],
                "views": views, "likes": likes, "seconds": secs, "thumb": thumb,
                "url": f"https://www.youtube.com/watch?v={v['id']}",
                "views_per_hour": round(views / hours),
                # Views per hour since upload, with a bonus for likes.
                "score": round(views / hours + likes * 2 / hours, 1),
            }
            item["viral"] = is_viral(item)
            out.append(item)
    return out


def channel_countries(channel_ids, key):
    countries = {}
    for part in chunks(sorted(set(channel_ids))):
        try:
            data = get_json(YT + "channels", {"part": "snippet", "id": ",".join(part), "key": key})
        except Exception as e:
            print(f"  channel lookup failed ({e})", file=sys.stderr)
            continue
        for c in data.get("items", []):
            if c["snippet"].get("country"):
                countries[c["id"]] = c["snippet"]["country"].upper()
    return countries


def find_all(key, now):
    """Run every search, then sort the videos into regions by the maker's country."""
    since = (now - dt.timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    fallback = {}                                  # video id -> region of the search that found it
    for s in SEARCHES:
        try:
            ids = search_ids(s, key, since)
            print(f"  search '{s['q'][:40]}': {len(ids)} found")
            for vid in ids:
                fallback.setdefault(vid, s["region"])
        except Exception as e:
            print(f"  search '{s['q'][:40]}' failed ({e})", file=sys.stderr)
    videos = video_details(list(fallback), key, now, MIN_SECONDS)

    viral_ids = []
    try:
        viral_since = (now - dt.timedelta(hours=VIRAL_HOURS)).isoformat().replace("+00:00", "Z")
        viral_ids = search_ids(VIRAL_SEARCH, key, viral_since)
        print(f"  viral search: {len(viral_ids)} found")
    except Exception as e:
        print(f"  viral search failed ({e})", file=sys.stderr)
    extra = video_details([i for i in viral_ids if i not in fallback], key, now, VIRAL_MIN_SECONDS)

    countries = channel_countries([v["channelId"] for v in videos], key)
    by_region = {r["id"]: [] for r in REGIONS}
    for v in videos:
        region = (COUNTRY_REGION.get(countries.get(v["channelId"], ""))
                  or region_from_script(v["title"]) or fallback[v["id"]])
        by_region[region].append(v)
    for rid in by_region:
        by_region[rid] = sorted(by_region[rid], key=lambda v: v["score"], reverse=True)[:PER_REGION]

    pool = {v["id"]: v for v in videos + extra if v["viral"]}
    viral = sorted(pool.values(), key=lambda v: v["views_per_hour"], reverse=True)[:VIRAL_KEEP]
    return by_region, viral


def demo_videos():
    """Example entries so the website can be previewed without an API key."""
    examples = {
        "nl": [("Snoek van 118 cm op shad in het Haringvliet", "Voorbeeldkanaal NL", 8400),
               ("Snoekbaars op 5 m bij Urk: dropshot uitgelegd", "Voorbeeldkanaal NL", 5100),
               ("Polderbaars op topwater in november", "Voorbeeldkanaal NL", 2300)],
        "scandinavie": [("Heilbot van 2,1 m bij Senja", "Example Channel NO", 21000)],
        "west-europa": [("Wintersnoek op de Ierse meren", "Example Channel IE", 6300)],
        "oost-europa": [("Szczupak 105 cm z Mazur", "Przykładowy kanał PL", 5200)],
        "zuid-europa": [("Siluro gigante en el Ebro", "Canal de Ejemplo ES", 7400)],
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
            ("Friese meren (Sneek)", 8.7, 1005, -3.5, 3, "W", 80),
            ("IJssel (Deventer)", 8.4, 1008, -2.2, 2, "ZW", 85),
            ("Twentekanaal (Hengelo)", 8.0, 1009, -1.9, 2, "Z", 90),
            ("Vecht (Ommen)", 8.3, 1008, -2.4, 3, "ZW", 80)]
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
        by_region, viral = find_all(key, now)
        for r in REGIONS:
            print(f"  {r['name']}: {len(by_region[r['id']])} videos")
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
