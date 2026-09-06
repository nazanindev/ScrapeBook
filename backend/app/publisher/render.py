from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

# The frontend's floating controls (15+ badge, rearrange / save png) are position:fixed
# inside #canvas-screen; at a canvas-sized viewport they land inside #canvas's box and
# get baked into the screenshot. Hide them for the capture.
_HIDE_CHROME_CSS = "#btn-col { display: none !important; }"

# Distinct image URLs that actually rendered. collage.js removes a broken image's
# wrapper on error, and the composer repeats some images on purpose, so this is the
# honest count of pictures a viewer will see.
_COUNT_LOADED_JS = (
    "() => new Set([...document.querySelectorAll('#canvas img')]"
    ".filter(i => i.complete && i.naturalWidth > 0).map(i => i.src)).size"
)


@dataclass(frozen=True)
class RenderResult:
    path: Path
    images_loaded: int    # distinct images that rendered
    images_expected: int  # distinct image URLs in the collage JSON (includes dead links)


def render_collage(
    frontend_url: str,
    collage: dict,
    out_path: str | Path,
    scale: int = 1,
    timeout_ms: int = 60_000,
) -> RenderResult:
    """Screenshot a collage exactly as the real frontend renders it.

    We inject the already-fetched collage JSON into the page (window.__EPHEMERA_COLLAGE__),
    so collage.js's headless hook renders it directly — no API round-trip from the browser,
    and pixel-identical to the live app because it's the same buildFragment().
    """
    out_path = Path(out_path)
    canvas = collage.get("canvas", {})
    width = int(canvas.get("width", 1600))
    height = int(canvas.get("height", 2200))

    init_script = "window.__EPHEMERA_COLLAGE__ = " + json.dumps(collage) + ";"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,
        )
        page = context.new_page()
        page.add_init_script(init_script)  # runs before collage.js
        page.goto(f"{frontend_url}/", wait_until="load")
        # collage.js sets this true once every image has settled.
        page.wait_for_function("() => window.__EPHEMERA_RENDER_READY__ === true", timeout=timeout_ms)
        page.add_style_tag(content=_HIDE_CHROME_CSS)
        loaded = int(page.evaluate(_COUNT_LOADED_JS))
        page.locator("#canvas").screenshot(path=str(out_path))
        browser.close()

    expected = len({f.get("content") for f in collage.get("fragments", [])
                    if f.get("type") in ("image", "archive_screenshot")})  # distinct, like `loaded`
    return RenderResult(out_path, loaded, expected)
