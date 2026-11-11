# Vangst24

A website that shows the newest fishing videos from all over the world (last 24 hours) plus a fishing forecast for Dutch waters. It updates itself every 4 hours, for free.

```
finder/find_videos.py        finds new videos per region + makes the forecast
docs/index.html              the website (Dutch)
docs/data/*.json             the data the website shows (written by the finder)
planning/kandidaten-*.csv    daily list of candidate clips for the episode
.github/workflows/update.yml runs the finder every 4 hours on GitHub
```

## Step 1: Get a free YouTube API key (10 minutes)

1. Go to https://console.cloud.google.com and sign in with a Google account.
2. Create a new project, for example "Vangst24".
3. Open **APIs & Services → Library**, search for **YouTube Data API v3** and click **Enable**.
4. Open **APIs & Services → Credentials → Create credentials → API key**.
5. Copy the key. Keep it secret: never paste it into the website or a public file.

The free quota is 10,000 units a day. One run does 12 searches plus 1 worldwide "viral" search (about 1,300 units), so every 4 hours (7,800 units a day) fits.

## Step 2: Put it on GitHub (free hosting + automatic updates)

1. Create a free account at https://github.com and make a new repository called `vangst24`.
2. Upload all the files in this folder (keep the folder structure, including `.github`).
3. In the repository: **Settings → Secrets and variables → Actions → New repository secret**.
   Name: `YOUTUBE_API_KEY`, value: your key.
4. **Settings → Pages**: Source "Deploy from a branch", branch `main`, folder `/docs`. Save.
5. **Actions** tab → "Update Vangst24" → **Run workflow** to fill it the first time.

After a minute the site is live at `https://<your-username>.github.io/vangst24/`, and it refreshes every 4 hours by itself.

## Running it on your own computer

```bash
python finder/find_videos.py --demo        # example data, no key needed
YOUTUBE_API_KEY=your-key python finder/find_videos.py
cd docs && python -m http.server 8000      # then open http://localhost:8000
```

## Changing what it searches for

Edit the `SEARCHES` list at the top of `finder/find_videos.py`. In a search text `|` means "or" and only joins the words next to it: `fishing bass|pike` means fishing and (bass or pike). Videos are sorted into regions by the maker's country; if that is unknown, the search's own `region` is used. Words that should never appear (games, cartoons) are in `BLOCKED_WORDS`. The Dutch fishing spots for the forecast are in `SPOTS`.

## About rights

The website plays videos through YouTube's own player, which YouTube allows. The views count for the creator and their name and channel are shown. For the TV channel or a 24/7 stream you need the creator's permission before you use their clip. Track that in the planning sheet.

## Viral videos

The finder also searches worldwide for fishing videos that are taking off: more than 50,000 views and over 2,000 views per hour, uploaded in the last 48 hours. They appear in the "Viraal" section and are marked "ja" in the `viraal` column of the planning list. Change the limits at the top of `finder/find_videos.py` (`VIRAL_...`).

The website may show them (embedded). For the TV channel you need permission first: see `planning/toestemming-vragen.md`.

## Checking videos before they appear

Every video is checked before it reaches the site. It is rejected when:

- it is on the block list (`finder/blokkeerlijst.txt`: words, channel names or video links, one per line);
- YouTube labels it as music, gaming or news, or its topics are games, music, film, TV, politics or religion;
- it is a live stream, or its title has a forbidden word (`BLOCKED_WORDS`);
- it is about food and not also a hobby or sports video;
- its title has no fishing word in any language (`FISHING_WORDS`);
- it has fewer than 20 views.

What was rejected, and why, is written to `planning/afgewezen-<date>.csv` on every run.

## The bite score

A rule of thumb for predator fishing (pike, zander, perch), from 0 to 10: falling air pressure, a light wind (2 to 4 Bft), cloud cover and new or full moon raise it. Strong wind and fast-rising pressure lower it. It is meant as a fun guide, not a guarantee.
