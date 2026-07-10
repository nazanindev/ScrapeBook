const API = window.EPHEMERA_API_URL || "http://localhost:8000";
const POLL_INTERVAL = 1500;
const ENRICH_POLL_INTERVAL = 3000;

const promptScreen = document.getElementById("prompt-screen");
const canvasScreen = document.getElementById("canvas-screen");
const canvas = document.getElementById("canvas");
const input = document.getElementById("topic-input");
const btn = document.getElementById("generate-btn");
const statusText = document.getElementById("status-text");
const resetBtn = document.getElementById("reset-btn");
const exportBtn = document.getElementById("export-btn");
const rearrangeBtn = document.getElementById("rearrange-btn");
const progressWrap = document.getElementById("progress-wrap");
const progressBar = document.getElementById("progress-bar");
const densityBtns = document.querySelectorAll(".density-btn");

let lastCollageData = null;
let selectedDensity = null;

btn.addEventListener("click", onGenerate);
input.addEventListener("keydown", (e) => { if (e.key === "Enter") onGenerate(); });
resetBtn.addEventListener("click", onReset);
exportBtn.addEventListener("click", onExport);
rearrangeBtn.addEventListener("click", onRearrange);

densityBtns.forEach(b => {
  b.addEventListener("click", () => {
    const val = b.dataset.density;
    if (selectedDensity === val) {
      selectedDensity = null;
      b.classList.remove("active");
    } else {
      selectedDensity = val;
      densityBtns.forEach(x => x.classList.remove("active"));
      b.classList.add("active");
    }
  });
});

async function onGenerate() {
  const topic = input.value.trim();
  if (!topic) return;

  btn.disabled = true;
  progressWrap.hidden = false;
  setProgress(0);
  setStatus("gathering fragments...");

  try {
    const res = await fetch(`${API}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, density: selectedDensity }),
    });
    if (!res.ok) throw new Error("generate failed");
    const { job_id } = await res.json();
    pollJob(job_id);
  } catch (err) {
    setStatus("something went wrong. try again.");
    btn.disabled = false;
  }
}

function pollJob(jobId) {
  let phase1Done = false;

  async function tick() {
    try {
      const res = await fetch(`${API}/job/${jobId}`);
      if (!res.ok) throw new Error();
      const { status, progress } = await res.json();

      if (!phase1Done) {
        setProgress(progress);
        setStatus(progressLabel(progress));
      }

      if (status === "done" && !phase1Done) {
        phase1Done = true;
        await renderCollage(jobId);
        setTimeout(tick, ENRICH_POLL_INTERVAL);
      } else if (status === "enriched") {
        if (!phase1Done) {
          // Pipeline finished before we polled — render everything at once
          phase1Done = true;
          await renderCollage(jobId);
        } else {
          await enrichCollage(jobId);
          setStatus("");
          progressWrap.hidden = true;
        }
      } else if (status === "failed") {
        btn.disabled = false;
        setStatus("pipeline failed. try again.");
      } else if (status === "running" && phase1Done) {
        setStatus("adding more...");
        setTimeout(tick, ENRICH_POLL_INTERVAL);
      } else {
        setTimeout(tick, POLL_INTERVAL);
      }
    } catch {
      if (!phase1Done) {
        setStatus("lost connection.");
        btn.disabled = false;
      }
    }
  }

  setTimeout(tick, POLL_INTERVAL);
}

function progressLabel(p) {
  if (p < 30) return "scraping images...";
  if (p < 60) return "pulling archive fragments...";
  if (p < 80) return "extracting metadata...";
  if (p < 95) return "composing collage...";
  return "almost there...";
}

async function renderCollage(jobId) {
  const res = await fetch(`${API}/collage/${jobId}`);
  const data = await res.json();
  renderCollageData(data);
}

function renderCollageData(data) {
  lastCollageData = data;

  canvas.innerHTML = "";
  canvas.style.width = `${data.canvas.width}px`;
  canvas.style.height = `${data.canvas.height}px`;

  for (const frag of data.fragments) {
    const el = buildFragment(frag);
    if (el) canvas.appendChild(el);
  }

  promptScreen.hidden = true;
  canvasScreen.hidden = false;
  progressWrap.hidden = true;
  setStatus("");
}

async function enrichCollage(jobId) {
  const res = await fetch(`${API}/collage/${jobId}`);
  const data = await res.json();
  lastCollageData = data;

  const existingIds = new Set(
    [...canvas.querySelectorAll(".fragment[data-id]")].map((el) => el.dataset.id)
  );

  for (const frag of data.fragments) {
    if (existingIds.has(frag.id)) continue;
    const el = buildFragment(frag);
    if (!el) continue;
    el.classList.add("fragment--incoming");
    canvas.appendChild(el);
  }
}

function buildFragment(frag) {
  const { id, layout, type, content, source_url, og, captured_at } = frag;
  if (!layout) return null;

  const { x, y, width, rotation, z_index, css_filter, blend_mode } = layout;

  const wrapper = document.createElement("div");
  wrapper.className = "fragment";
  wrapper.dataset.id = id;
  wrapper.style.cssText = [
    `left: ${x}px`,
    `top: ${y}px`,
    `width: ${width}px`,
    `--frag-rotation: ${rotation}deg`,
    `transform: rotate(${rotation}deg)`,
    `z-index: ${z_index}`,
    css_filter ? `filter: ${css_filter}` : "",
    blend_mode && blend_mode !== "normal" ? `mix-blend-mode: ${blend_mode}` : "",
  ].filter(Boolean).join(";");

  if (type === "image") {
    const img = document.createElement("img");
    img.className = "fragment-image";
    img.src = content;
    img.alt = "";
    img.loading = "lazy";
    img.style.width = `${width}px`;
    img.style.height = `${layout.height ?? Math.round(width * 0.7)}px`;
    img.style.objectFit = "cover";
    img.onerror = () => wrapper.remove();
    wrapper.appendChild(img);

  } else if (type === "archive_screenshot") {
    const fig = document.createElement("figure");
    fig.className = "fragment-archive";
    fig.style.width = `${width}px`;

    const img = document.createElement("img");
    img.src = content;
    img.alt = "";
    img.loading = "lazy";
    img.style.width = `${width}px`;
    img.style.height = `${layout.height ?? Math.round(width * 0.65)}px`;
    img.style.objectFit = "cover";
    img.onerror = () => wrapper.remove();

    const cap = document.createElement("figcaption");
    const year = (og && og.year) ? og.year : (captured_at ? captured_at.slice(0, 4) : "");
    const origDomain = (og && og.original_url) ? new URL(og.original_url).hostname.replace(/^www\./, "") : "";
    cap.textContent = [year, origDomain].filter(Boolean).join(" · ");

    fig.appendChild(img);
    fig.appendChild(cap);
    wrapper.appendChild(fig);

  } else if (type === "headline") {
    const div = document.createElement("div");
    div.className = "fragment-headline";
    div.style.width = `${width}px`;
    div.style.color = layout.text_color || "";
    div.style.textShadow = _textShadowFor(layout.text_color);
    div.textContent = content;
    wrapper.appendChild(div);

  } else if (type === "snippet") {
    const div = document.createElement("div");
    div.className = "fragment-snippet";
    div.style.width = `${width}px`;
    div.style.color = layout.text_color || "";
    div.style.textShadow = _textShadowFor(layout.text_color);
    div.textContent = content;
    wrapper.appendChild(div);

  } else if (type === "metadata") {
    const span = document.createElement("span");
    span.className = "fragment-metadata";
    span.style.color = layout.text_color || "";
    span.style.textShadow = _textShadowFor(layout.text_color);
    span.textContent = content;
    wrapper.appendChild(span);

  } else {
    return null;
  }

  return wrapper;
}

const TEXT_COLORS = ["#ffffff", "#ffffff", "#ffffff", "#f5e6d3", "#f5e6d3", "#ffd700", "#ffffff", "#1a1208"];

function _textShadowFor(color) {
  if (!color) {
    return "0 0 5px rgba(255,255,255,0.8), 0 1px 2px rgba(255,255,255,0.6)";
  }
  const hex = color.replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.5
    ? "0 1px 4px rgba(0,0,0,0.85), 0 2px 8px rgba(0,0,0,0.45)"
    : "0 0 6px rgba(255,255,255,0.85), 0 1px 3px rgba(255,255,255,0.7)";
}
const TEXT_TYPES = new Set(["headline", "snippet", "metadata"]);

function onRearrange() {
  if (!lastCollageData) return;
  rearrangeBtn.disabled = true;

  const cw = lastCollageData.canvas.width;
  const ch = lastCollageData.canvas.height;

  const reshuffled = {
    ...lastCollageData,
    fragments: lastCollageData.fragments.map((frag) => {
      if (!frag.layout) return frag;
      const w = frag.layout.width;
      const h = frag.layout.height ?? Math.round(w * 0.7);
      const maxX = Math.max(0, cw - w);
      const maxY = Math.max(0, ch - h);
      const newColor = TEXT_TYPES.has(frag.type)
        ? TEXT_COLORS[Math.floor(Math.random() * TEXT_COLORS.length)]
        : frag.layout.text_color;
      return {
        ...frag,
        layout: {
          ...frag.layout,
          x: Math.round(Math.random() * maxX),
          y: Math.round(Math.random() * maxY),
          rotation: (Math.random() * 16 - 8).toFixed(2) * 1,
          z_index: Math.floor(Math.random() * 20) + 1,
          text_color: newColor,
        },
      };
    }),
  };

  lastCollageData = reshuffled;
  canvas.innerHTML = "";

  for (const frag of reshuffled.fragments) {
    const el = buildFragment(frag);
    if (el) {
      el.classList.add("fragment--incoming");
      canvas.appendChild(el);
    }
  }

  setTimeout(() => { rearrangeBtn.disabled = false; }, 600);
}

function onReset() {
  canvasScreen.hidden = true;
  promptScreen.hidden = false;
  canvas.innerHTML = "";
  input.value = "";
  btn.disabled = false;
  progressWrap.hidden = true;
  lastCollageData = null;
  setProgress(0);
  setStatus("");
}

async function onExport() {
  exportBtn.disabled = true;
  exportBtn.textContent = "rendering...";

  const isMobile = window.matchMedia("(hover: none) and (pointer: coarse)").matches;
  // Open the window now, synchronously, so iOS Safari doesn't block it as a popup.
  const mobileWin = isMobile ? window.open("", "_blank") : null;

  // html2canvas doesn't support mix-blend-mode or CSS animations — strip them
  // from the live DOM synchronously (html2canvas snapshots the DOM on call),
  // then restore afterward so the page is unaffected.
  const frags = [...canvas.querySelectorAll(".fragment")];
  const savedBlend = frags.map(el => el.style.mixBlendMode);
  const savedAnim  = frags.map(el => el.style.animation);
  frags.forEach(el => {
    el.style.mixBlendMode = "normal";
    el.style.animation = "none";
    el.classList.remove("fragment--incoming");
  });

  try {
    const bg = "#ede5d8";
    const canvasEl = await html2canvas(canvas, {
      backgroundColor: bg,
      useCORS: true,
      allowTaint: true,
      scale: 1,
      width: canvas.offsetWidth,
      height: canvas.offsetHeight,
    });

    const topic = (input.value.trim() || "ephemera").replace(/\s+/g, "-").toLowerCase();

    if (mobileWin) {
      // On mobile, open the image directly so the user can long-press to save to their library.
      canvasEl.toBlob(blob => {
        const url = URL.createObjectURL(blob);
        mobileWin.location.href = url;
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      }, "image/png");
    } else {
      const link = document.createElement("a");
      link.download = `${topic}.png`;
      link.href = canvasEl.toDataURL("image/png");
      link.click();
    }
  } catch (err) {
    if (mobileWin) mobileWin.close();
    console.error("export failed", err);
  } finally {
    frags.forEach((el, i) => {
      el.style.mixBlendMode = savedBlend[i];
      el.style.animation = savedAnim[i];
    });
    exportBtn.disabled = false;
    exportBtn.textContent = "↓ save png";
  }
}

function setProgress(pct) {
  progressBar.style.width = `${pct}%`;
}

function setStatus(msg) {
  statusText.textContent = msg;
}

// ── headless render hook ────────────────────────────────────────────────────
// Inert during normal use. The ephemera publisher injects a collage as
// window.__EPHEMERA_COLLAGE__ (via Playwright add_init_script), or you can open
// ?job=<id> to render an existing job. Either way we render, wait for every
// image to settle, then flip window.__EPHEMERA_RENDER_READY__ so the
// screenshotter knows it's safe to capture #canvas.
(async function headlessRender() {
  const injected = window.__EPHEMERA_COLLAGE__;
  const jobId = new URLSearchParams(location.search).get("job");
  if (!injected && !jobId) return;

  try {
    const data = injected || await (await fetch(`${API}/collage/${jobId}`)).json();
    renderCollageData(data);

    // Force eager loading and wait for each image to load or error out.
    // (buildFragment's own onerror removes broken ones — we listen additively.)
    const imgs = [...canvas.querySelectorAll("img")];
    imgs.forEach((img) => { img.loading = "eager"; });
    await Promise.all(imgs.map((img) =>
      img.complete
        ? Promise.resolve()
        : new Promise((res) => {
            img.addEventListener("load", res, { once: true });
            img.addEventListener("error", res, { once: true });
          })
    ));
    // Let layout/paint settle for a couple of frames before signalling.
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  } finally {
    window.__EPHEMERA_RENDER_READY__ = true;
  }
})();
