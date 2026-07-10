"""ephemera — the publisher that wanders through Ephemera and posts specimens to Tumblr.

Pipeline:  experiment -> /generate -> render (Playwright screenshot) -> Tumblr post.
Run from the backend dir:  python -m app.publisher.publish <verify|render|run> ...
"""
