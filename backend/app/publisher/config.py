from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _normalize_blog(raw: str) -> str:
    """Return a 'name.tumblr.com' identifier from whatever form the user pasted."""
    raw = raw.strip().rstrip("/")
    if "//" in raw:  # a full URL like https://www.tumblr.com/ephemera-project
        u = urlparse(raw)
        if u.netloc.endswith(".tumblr.com") and u.netloc != "www.tumblr.com":
            return u.netloc  # already name.tumblr.com
        seg = u.path.strip("/").split("/")[0] if u.path.strip("/") else ""
        return f"{seg}.tumblr.com" if seg else u.netloc
    if "." in raw:  # already name.tumblr.com or a custom domain
        return raw
    return f"{raw}.tumblr.com"  # bare 'name'


@dataclass(frozen=True)
class Settings:
    # Tumblr app credentials (from tumblr.com/oauth/apps)
    consumer_key: str
    consumer_secret: str
    # Tumblr user tokens (from api.tumblr.com/console — see README)
    oauth_token: str
    oauth_token_secret: str
    blog: str  # e.g. "ephemera.tumblr.com"

    # Where the Ephemera pipeline + frontend live.
    # NOTE: the publisher injects collage JSON straight into the render page, so the
    # browser does NOT need to reach the API — only api_base_url (used here, server-side)
    # has to point at the backend where jobs are created.
    api_base_url: str
    frontend_url: str  # must serve a collage.js that has the headless render hook

    post_state: str  # "draft" | "queue" | "published" | "private"
    render_scale: int  # device pixel ratio for the screenshot (1 = 1600x2200)

    @classmethod
    def from_env(cls, require_tumblr: bool = True) -> "Settings":
        """Load settings from env. `require_tumblr=False` lets local-only commands
        (steer, refresh-corpora, review) run without Tumblr credentials configured."""
        def req(name: str) -> str:
            v = os.getenv(name, "").strip()
            if not v and require_tumblr:
                hint = " — run: python -m app.publisher.get_tokens" if "OAUTH" in name else ""
                raise RuntimeError(f"{name} is empty in app/publisher/.env{hint}")
            return v

        return cls(
            consumer_key=req("TUMBLR_CONSUMER_KEY"),
            consumer_secret=req("TUMBLR_CONSUMER_SECRET"),
            oauth_token=req("TUMBLR_OAUTH_TOKEN"),
            oauth_token_secret=req("TUMBLR_OAUTH_TOKEN_SECRET"),
            blog=_normalize_blog(req("TUMBLR_BLOG")),
            api_base_url=os.getenv("EPHEMERA_API_URL", "http://localhost:8000").rstrip("/"),
            frontend_url=os.getenv("EPHEMERA_FRONTEND_URL", "http://localhost:3000").rstrip("/"),
            post_state=os.getenv("EPHEMERA_POST_STATE", "draft"),
            render_scale=int(os.getenv("EPHEMERA_RENDER_SCALE", "1")),
        )
