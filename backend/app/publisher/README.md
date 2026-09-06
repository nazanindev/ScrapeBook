# ephemera

A bot that wanders through **Ephemera** and posts the results to a Tumblr as a
running case study of the system. Each post is a *specimen* — a collage plus a
lab-notebook caption (`vibe 0.80 · auto · seed 7f3a2c01 · 14 fragments · openverse ×9`).

```
experiment  ->  /generate  ->  Playwright screenshot  ->  Tumblr post
(quirk to       (existing      (renders the real         (caption = readout,
 demonstrate)    pipeline)      frontend, injected)        tags = the axes)
```

## How it renders

The backend already bakes the entire visual into each fragment's `layout`
(position, rotation, CSS filter, blend mode). `render.py` injects the fetched
collage JSON into the frontend page and screenshots `#canvas`, so the output is
**pixel-identical to the live app** — the same `buildFragment()` does the drawing,
no second renderer to keep in sync.

## Experiments

| experiment       | what it demonstrates                                   | post type  |
|------------------|--------------------------------------------------------|------------|
| `density-ladder` | `fog` → `fog harbor` → `fog harbor 1932`, vibe climbing | photoset   |
| `seed-series`    | one prompt, N layout seeds — deterministic vs. chance   | photoset   |
| `neutral-zone`   | near-synonyms whose vibe is decided by an md5, not meaning | photoset |
| `domain-drift`   | one ambiguous word fanning across senses               | single     |
| `specimen`       | a plain pull — ordinary behavior                       | single     |

Tags stay a small closed vocabulary: `#ephemera` + the series tag (+ a
`#sparse`/`#dense`/`#neutral-zone` band on single posts). All the numbers live in
the caption, never in tags.

## Setup

### 1. Tumblr credentials
1. **Register an app** at <https://www.tumblr.com/oauth/apps> → Consumer Key + Secret.
2. **Get user tokens** at <https://api.tumblr.com/console> — paste the consumer
   key/secret, authorize against your logged-in account, and it shows all four
   credentials including the OAuth Token + Token Secret.
3. `cp .env.example .env` and fill in the four creds + `TUMBLR_BLOG`.

### 2. Python deps
From the backend dir:
```bash
pip install -r app/publisher/requirements.txt
python -m playwright install chromium
```

### 3. Point at a pipeline
`EPHEMERA_API_URL` must reach the backend where jobs are created.
`EPHEMERA_FRONTEND_URL` must serve a `collage.js` that has the headless render
hook (this repo's does). For local dev, `docker compose up` gives you the API on
:8000 and the frontend on :3000.

## Run

```bash
# from backend/
python -m app.publisher.publish verify         # check creds
python -m app.publisher.publish render --experiment density-ladder --out /tmp/eu
python -m app.publisher.publish run    --experiment random --state published
```

- `verify` — confirms auth, prints the target blog.
- `render` — full pipeline + screenshots + prints captions and each shot's screen
  verdict, **posts nothing**. Use this first.
- `run` — also posts. Locally it defaults to `--state draft` (env `EPHEMERA_POST_STATE`);
  the GitHub Action passes `--state published`.

### The publish-time screen
There is no human in the loop any more, so `run` gates every render through
`screen.py` before posting:

- **empty-ish canvas** — the frontend drops images that fail to load, so a collage
  whose sources 404'd renders as a few text scraps on cream. Measured on the PNG:
  rejected below 40% non-background coverage or fewer than 4 distinct loaded images.
  (Real collages measured 54–89%; broken ones 12% and 35% with 2 images.)
- **inappropriate text** — a whole-word blocklist (sexual, slurs, strong profanity,
  self-harm, violence) over the topic, caption, tags, every text fragment, image
  titles, and the source page paths. Titles only: there is no image classifier, so a
  nude with a neutral title ("Torso") gets through.

Rejected shots are never posted; they are recorded to the ledger as `rejected` so
the walk won't retry the topic and `metrics` shows what gets thrown out. Tune the
thresholds and word lists in `screen.py`; `run --no-screen` bypasses it.

### Scheduling
`.github/workflows/ephemera.yml` runs the walk daily and posts straight to public.
To drip posts instead of dropping the batch at once, dispatch it with `queue` and
configure the blog's queue (Settings → Queue) to 1–3 posts/day.

## Notes
- `render` and `run` need the backend + frontend reachable; `verify` only needs Tumblr.
- `seed-series` and the `seed` shown in captions rely on the backend `layout_seed`
  plumbing (GenerateRequest.layout_seed). Older collages fall back to the topic hash.
