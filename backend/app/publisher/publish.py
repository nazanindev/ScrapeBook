"""ephemera CLI — wander through Ephemera and post specimens to Tumblr.

Run from the backend dir:

    python -m app.publisher.publish verify
    python -m app.publisher.publish render --experiment density-ladder --out /tmp/ephemera
    python -m app.publisher.publish run    --experiment random --state draft
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

from app.publisher import experiments as exp_mod
from app.publisher.caption import build_caption
from app.publisher.config import Settings
from app.publisher.experiments import Experiment, Shot
from app.publisher.pipeline_client import PipelineClient
from app.publisher.render import render_collage


def _resolve_experiment(name: str, rng: random.Random) -> Experiment:
    if name in ("random", "", None):
        return exp_mod.pick_experiment(rng)
    return exp_mod.build(name, rng)


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
    return 0


def cmd_render(settings: Settings, args) -> int:
    rng = random.Random(args.seed)
    exp = _resolve_experiment(args.experiment, rng)
    out_dir = Path(args.out)
    print(f"experiment: {exp.name} (#{exp.tag}) · {len(exp.shots)} shot(s)")
    rendered = _generate_and_render(settings, exp, out_dir)

    print("\n--- captions (dry run, nothing posted) ---")
    for r in rendered:
        caption, tags = build_caption(r["shot"].topic, r["collage"], r["shot"].density, exp, r["shot"].meta_topics, str(r["png"]), r["shot"].tags)
        print(caption)
        print(f"tags ({len(tags)}): {tags}\n")
    print(f"pngs in {out_dir}")
    return 0


def cmd_run(settings: Settings, args) -> int:
    from app.publisher.tumblr import TumblrPublisher
    rng = random.Random(args.seed)
    state = args.state or settings.post_state

    pub = TumblrPublisher(settings)
    pub.verify()  # fail fast on bad creds before scraping

    if args.topics:  # a themed drop: one collage per explicit topic, grouped by --tag
        topics = [t.strip() for t in re.split(r"[;\n]", args.topics) if t.strip()]
        runs = [Experiment(args.tag, args.tag, [Shot(topic=t, density="dense")]) for t in topics]
    else:
        runs = [_resolve_experiment(args.experiment, rng) for _ in range(args.count)]

    posted = 0
    for n, exp in enumerate(runs):
        print(f"\n=== run {n + 1}/{len(runs)}: {exp.name} (#{exp.tag}) · {len(exp.shots)} post(s) ===")
        try:
            with tempfile.TemporaryDirectory(prefix="ephemera-") as tmp:
                rendered = _generate_and_render(settings, exp, Path(tmp))
                for r in rendered:
                    caption, tags = build_caption(r["shot"].topic, r["collage"], r["shot"].density, exp, r["shot"].meta_topics, str(r["png"]), r["shot"].tags)
                    resp = pub.post_photo(str(r["png"]), caption, tags, state=state)
                    posted += 1
                    print(f"  posted id={resp.get('id')} state={state} tags={tags}")
        except Exception as e:  # one bad scrape/render shouldn't sink the whole batch
            print(f"  ! skipped run {n + 1} ({exp.tag}): {e}")
    print(f"\ndone: {posted} drafts posted")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ephemera", description="post Ephemera specimens to Tumblr")
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="check Tumblr credentials")
    p_verify.set_defaults(func=cmd_verify)

    p_render = sub.add_parser("render", help="generate + screenshot, print captions, post nothing")
    p_render.add_argument("--experiment", default="random",
                          help="density-ladder | seed-series | neutral-zone | domain-drift | specimen | random")
    p_render.add_argument("--out", default="./ephemera-out", help="dir for rendered pngs")
    p_render.add_argument("--seed", type=int, default=None, help="rng seed for reproducible experiment choice")
    p_render.set_defaults(func=cmd_render)

    p_run = sub.add_parser("run", help="generate + render + post to Tumblr")
    p_run.add_argument("--experiment", default="random",
                       help="density-ladder | seed-series | neutral-zone | domain-drift | specimen | random")
    p_run.add_argument("--state", default=None, help="draft | queue | published | private (overrides env)")
    p_run.add_argument("--count", type=int, default=1, help="how many posts to make this run")
    p_run.add_argument("--seed", type=int, default=None, help="rng seed for reproducible experiment choice")
    p_run.add_argument("--topics", default=None, help="themed drop: explicit topics separated by ; (overrides --experiment)")
    p_run.add_argument("--tag", default="dispatch", help="grouping tag for a --topics drop")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    settings = Settings.from_env()
    return args.func(settings, args)


if __name__ == "__main__":
    sys.exit(main())
