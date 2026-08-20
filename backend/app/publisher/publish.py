"""ephemera CLI — wander through Ephemera and post specimens to Tumblr.

Run from the backend dir:

    python -m app.publisher.publish verify
    python -m app.publisher.publish refresh-corpora
    python -m app.publisher.publish render --experiment lift --out /tmp/ephemera
    python -m app.publisher.publish run    --experiment random --state draft
    python -m app.publisher.publish review
    python -m app.publisher.publish metrics
    python -m app.publisher.publish steer  --toward met --pin glacier
    python -m app.publisher.publish sync

The walk is corpus-fed and steerable: `refresh-corpora` pulls evocative material from
outside the loop (museums + poetry); `steer` biases the walk; `run` records every post to
the private ledger; `sync` reads how they landed back from Tumblr; `review` shows what's
interesting and `metrics` shows the distribution the walk is actually producing. See the
module docstrings in corpora.py / ledger.py / steer.py.
"""
from __future__ import annotations
import argparse
import random
import re
import sys
import tempfile
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional; env may be set another way
    pass

from app.publisher import corpora
from app.publisher import experiments as exp_mod
from app.publisher import ledger as ledger_mod
from app.publisher import steer
from app.publisher.caption import build_caption
from app.publisher.config import Settings
from app.publisher.experiments import Experiment, Shot, WalkContext
from app.publisher.ledger import Ledger
from app.publisher.pipeline_client import PipelineClient
from app.publisher.render import render_collage


def _ledger(settings: Settings) -> Ledger:
    return Ledger(settings.api_base_url)


def _walk_context(settings: Settings) -> WalkContext:
    """Assemble the walk's inputs: exogenous corpus (entropy), ledger (anti-repeat +
    feedback + recent shape mix), and steer (direction). Every part degrades gracefully
    when absent."""
    records = _ledger(settings).recent(150)
    direction = steer.load()
    return WalkContext(
        corpus=corpora.load(),
        recent=ledger_mod.recent_topics(records),
        # pinned steer-seeds are exempt: an explicit "lean on this" should not be
        # thinned by the word-level anti-repeat it would otherwise trip every post
        recent_words=ledger_mod.recent_words(records)
        - frozenset(w.strip().lower() for w in direction.pinned),
        recent_modes=ledger_mod.recent_modes(records),
        mode_weights=ledger_mod.feedback_weights(records),
        source_weights=ledger_mod.source_weights(records),
        shape_saturation=ledger_mod.shape_saturation(records),
        source_bias=direction.source_bias,
        pinned=tuple(direction.pinned),
    )


def _resolve_experiment(name: str, rng: random.Random, ctx: WalkContext) -> Experiment:
    if name in ("random", "", None):
        return exp_mod.pick_experiment(rng, ctx)
    return exp_mod.build(name, rng, ctx)


def _generate_and_render(settings: Settings, exp: Experiment, out_dir: Path) -> list[dict]:
    """Run each shot through the pipeline + screenshot. Returns rendered shot records."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict] = []
    with PipelineClient(settings.api_base_url) as pc:
        for i, shot in enumerate(exp.shots):
            print(f"  [{i + 1}/{len(exp.shots)}] generating {shot.topic!r}"
                  + (f" (seed {shot.layout_seed:08x})" if shot.layout_seed is not None else ""))
            collage = pc.run(shot.topic, shot.density, shot.layout_seed, want_enriched=True)
            png = out_dir / f"{exp.tag}-{i:02d}.png"
            render_collage(settings.frontend_url, collage, png, scale=settings.render_scale)
            print(f"      rendered -> {png}")
            rendered.append({"shot": shot, "collage": collage, "png": png})
    return rendered


def cmd_verify(settings: Settings, _args) -> int:
    from app.publisher.tumblr import TumblrPublisher  # imported lazily so render/verify don't both need pytumblr
    user = TumblrPublisher(settings).verify()
    blogs = ", ".join(b.get("name", "?") for b in user.get("blogs", []))
    print(f"authed as {user.get('name')!r} · blogs: {blogs}")
    print(f"posting target: {settings.blog} · default state: {settings.post_state}")
    led = _ledger(settings)
    print(f"ledger: {'enabled' if led.enabled else 'disabled (set LEDGER_SECRET)'} · "
          f"corpus: {corpora.summary(corpora.load())}")
    return 0


def cmd_refresh_corpora(settings: Settings, _args) -> int:
    print("fetching exogenous corpora (museums + poetry) — this hits the network...")
    corpus = corpora.refresh()
    print(f"cached: {corpora.summary(corpus)}")
    if corpus.phrases:
        sample = random.sample(corpus.phrases, k=min(8, len(corpus.phrases)))
        print("  e.g. " + " · ".join(sample))
    return 0


def cmd_render(settings: Settings, args) -> int:
    rng = random.Random(args.seed)
    ctx = _walk_context(settings)
    exp = _resolve_experiment(args.experiment, rng, ctx)
    out_dir = Path(args.out)
    print(f"experiment: {exp.name} (#{exp.tag}) · {len(exp.shots)} shot(s)")
    rendered = _generate_and_render(settings, exp, out_dir)

    print("\n--- captions (dry run, nothing posted) ---")
    for r in rendered:
        caption, tags = build_caption(r["shot"].topic, r["collage"], r["shot"].density, exp, r["shot"].meta_topics, str(r["png"]), r["shot"].tags, note=r["shot"].note)
        print(caption)
        print(f"tags ({len(tags)}): {tags}\n")
    print(f"pngs in {out_dir}")
    return 0


def cmd_run(settings: Settings, args) -> int:
    from app.publisher.tumblr import TumblrPublisher
    rng = random.Random(args.seed)
    state = args.state or settings.post_state
    ctx = _walk_context(settings)
    led = _ledger(settings)

    pub = TumblrPublisher(settings)
    pub.verify()  # fail fast on bad creds before scraping

    if args.topics:  # a themed drop: one collage per explicit topic, grouped by --tag
        topics = [t.strip() for t in re.split(r"[;\n]", args.topics) if t.strip()]
        runs = [Experiment(args.tag, args.tag, [Shot(topic=t, density="dense")]) for t in topics]
    else:
        runs = []
        for _ in range(args.count):
            exp = _resolve_experiment(args.experiment, rng, ctx)
            runs.append(exp)
            ctx = exp_mod.note_pick(ctx, exp)   # later picks see this batch's earlier ones

    posted = 0
    for n, exp in enumerate(runs):
        print(f"\n=== run {n + 1}/{len(runs)}: {exp.name} (#{exp.tag}) · {len(exp.shots)} post(s) ===")
        try:
            with tempfile.TemporaryDirectory(prefix="ephemera-") as tmp:
                rendered = _generate_and_render(settings, exp, Path(tmp))
                for r in rendered:
                    shot = r["shot"]
                    caption, tags = build_caption(shot.topic, r["collage"], shot.density, exp, shot.meta_topics, str(r["png"]), shot.tags, note=shot.note)
                    resp = pub.post_photo(str(r["png"]), caption, tags, state=state)
                    posted += 1
                    print(f"  posted id={resp.get('id')} state={state} tags={tags}")
                    led.record(topic=shot.topic, mode=exp.tag, source=shot.source,
                               shape=exp_mod.topic_shape(shot.topic),
                               components=list(shot.tags), tags=tags,
                               post_id=resp.get("id"), state=state)
        except Exception as e:  # one bad scrape/render shouldn't sink the whole batch
            print(f"  ! skipped run {n + 1} ({exp.tag}): {e}")
    print(f"\ndone: {posted} posts to {state}")
    return 0


def cmd_review(settings: Settings, args) -> int:
    led = _ledger(settings)
    if not led.enabled:
        print("ledger not configured — set LEDGER_SECRET (and configure it on the API).")
        return 1
    records = led.recent(args.n)
    print(f"{len(records)} recent records · direction: {steer.describe(steer.load())}\n")
    interesting = ledger_mod.interesting(records, k=args.top)
    if interesting:
        print("-- most interesting (by engagement) --")
        for r in interesting:
            print(f"  {r.get('notes') or 0:>4} notes  [{r.get('state') or '?':<9}] "
                  f"{r['topic']}  (#{r.get('mode') or '?'})")
    print("\n-- recent walk --")
    for r in records[-args.recent:]:
        print(f"  {(r.get('mode') or ''):12} {r['topic']}")
    return 0


def _print_breakdown(title: str, rows: list[dict]) -> None:
    if not rows:
        return
    print(f"\n-- by {title} --")
    print(f"  {'':16} {'picks':>6} {'share':>7} {'posted':>7} {'kept':>6} {'keep%':>7} {'notes':>7}")
    for r in rows:
        print(f"  {r['name'][:16]:16} {r['count']:>6} {r['share']:>6.0%} "
              f"{r['posted']:>7} {r['published']:>6} {r['keep_rate']:>6.0%} "
              f"{r['avg_notes']:>7.1f}")


def cmd_metrics(settings: Settings, args) -> int:
    """What the walk is actually doing, and what's actually landing.

    `review` shows individual posts; this shows the distribution — the surface that
    makes convergence visible (e.g. one shape at 80% share) instead of something you
    have to notice by eye in the feed.
    """
    led = _ledger(settings)
    if not led.enabled:
        print("ledger not configured — set LEDGER_SECRET (and configure it on the API).")
        return 1
    records = led.recent(args.n)
    if not records:
        print("ledger is empty — nothing has been recorded yet.\n"
              "If the walk has been running, check that the API exposes /ledger and that "
              "LEDGER_SECRET matches on both sides; the client fails soft by design.")
        return 1

    posted = [r for r in records if r.get("post_id")]
    published = [r for r in posted if r.get("state") == "published"]
    kept = f" · {len(published)} published ({len(published) / len(posted):.0%} kept)" if posted else ""
    print(f"{len(records)} records · {len(posted)} posted{kept}")
    print(f"direction: {steer.describe(steer.load())}")
    print(f"corpus: {corpora.summary(corpora.load())}")

    for key, label in (("shape", "topic shape"), ("mode", "mode"), ("source", "corpus source")):
        _print_breakdown(label, ledger_mod.breakdown(records, key))

    sat = ledger_mod.shape_saturation(records)
    if sat:
        hot = max(sat.items(), key=lambda kv: kv[1])
        print(f"\nrecent shape mix (last 40): "
              + ", ".join(f"{s} {v:.0%}" for s, v in sorted(sat.items())))
        if hot[1] > exp_mod.SHAPE_CAP:
            print(f"  ! {hot[0]} is at {hot[1]:.0%} (cap {exp_mod.SHAPE_CAP:.0%}) "
                  f"— the shape governor is thinning it")
    return 0


def cmd_steer(settings: Settings, args) -> int:
    if args.clear:
        steer.clear()
        print("direction cleared — pure walk")
        return 0
    d = steer.load()
    for src in (args.toward or []):
        d.source_bias[src] = args.weight
    for word in (args.pin or []):
        if word not in d.pinned:
            d.pinned.append(word)
    for word in (args.unpin or []):
        d.pinned = [w for w in d.pinned if w != word]
    if args.note is not None:
        d.note = args.note
    steer.save(d)
    print("direction:", steer.describe(d))
    return 0


def cmd_sync(settings: Settings, args) -> int:
    from app.publisher.tumblr import TumblrPublisher
    led = _ledger(settings)
    if not led.enabled:
        print("ledger not configured — set LEDGER_SECRET.")
        return 1
    posts = TumblrPublisher(settings).recent_posts(limit=args.limit)
    updated = 0
    for p in posts:
        updated += led.set_fate(p.get("id"), state=p.get("state"), notes=p.get("note_count"))
    print(f"synced {len(posts)} Tumblr posts · updated {updated} ledger records")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ephemera", description="post Ephemera specimens to Tumblr")
    sub = parser.add_subparsers(dest="command", required=True)
    modes = "lift | single | graft | frame | calque | parallax | atlas | seed-series | density-ladder | diptych | specimen | wander | random"

    p_verify = sub.add_parser("verify", help="check Tumblr credentials + ledger/corpus status")
    p_verify.set_defaults(func=cmd_verify)

    p_corp = sub.add_parser("refresh-corpora", help="pull fresh evocative material into the corpus cache")
    p_corp.set_defaults(func=cmd_refresh_corpora, needs_tumblr=False)

    p_render = sub.add_parser("render", help="generate + screenshot, print captions, post nothing")
    p_render.add_argument("--experiment", default="random", help=modes)
    p_render.add_argument("--out", default="./ephemera-out", help="dir for rendered pngs")
    p_render.add_argument("--seed", type=int, default=None, help="rng seed for reproducible experiment choice")
    p_render.set_defaults(func=cmd_render)

    p_run = sub.add_parser("run", help="generate + render + post to Tumblr")
    p_run.add_argument("--experiment", default="random", help=modes)
    p_run.add_argument("--state", default=None, help="draft | queue | published | private (overrides env)")
    p_run.add_argument("--count", type=int, default=1, help="how many posts to make this run")
    p_run.add_argument("--seed", type=int, default=None, help="rng seed for reproducible experiment choice")
    p_run.add_argument("--topics", default=None, help="themed drop: explicit topics separated by ; (overrides --experiment)")
    p_run.add_argument("--tag", default="dispatch", help="grouping tag for a --topics drop")
    p_run.set_defaults(func=cmd_run)

    p_review = sub.add_parser("review", help="show recent topics + what's interesting")
    p_review.add_argument("--n", type=int, default=100, help="how many recent records to pull")
    p_review.add_argument("--top", type=int, default=15, help="how many interesting topics to show")
    p_review.add_argument("--recent", type=int, default=25, help="how many recent-walk lines to show")
    p_review.set_defaults(func=cmd_review, needs_tumblr=False)

    p_metrics = sub.add_parser("metrics", help="what the walk is producing + what's landing")
    p_metrics.add_argument("--n", type=int, default=200, help="how many recent records to analyse")
    p_metrics.set_defaults(func=cmd_metrics, needs_tumblr=False)

    p_steer = sub.add_parser("steer", help="inject a direction into the walker")
    p_steer.add_argument("--toward", action="append", help="bias a corpus source (aic | met | text); repeatable")
    p_steer.add_argument("--weight", type=float, default=2.0, help="bias weight for --toward sources (default 2.0)")
    p_steer.add_argument("--pin", action="append", help="seed word to lean on; repeatable")
    p_steer.add_argument("--unpin", action="append", help="remove a pinned seed word; repeatable")
    p_steer.add_argument("--note", default=None, help="free-text reminder of the direction's intent")
    p_steer.add_argument("--clear", action="store_true", help="clear the direction (pure walk)")
    p_steer.set_defaults(func=cmd_steer, needs_tumblr=False)

    p_sync = sub.add_parser("sync", help="read post states/notes back from Tumblr into the ledger")
    p_sync.add_argument("--limit", type=int, default=50, help="how many recent posts to read per state")
    p_sync.set_defaults(func=cmd_sync)

    args = parser.parse_args(argv)
    settings = Settings.from_env(require_tumblr=getattr(args, "needs_tumblr", True))
    return args.func(settings, args)


if __name__ == "__main__":
    sys.exit(main())
