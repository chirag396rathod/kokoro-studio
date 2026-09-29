"use strict";

const $ = (s) => document.querySelector(s);
const body = document.body;

const SAMPLE_SCRIPT =
  "I told my computer I needed a break, and now it won't stop sending me KitKat ads. " +
  "Yesterday my WiFi and I finally had the talk. It said it needed some space. " +
  "So now I'm dating a cloud. It's called OneDrive. " +
  "Honestly, my smart fridge is the only one who listens to me anymore... " +
  "and it just keeps judging my cheese intake.";

const state = {
  engines: [],
  engine: "kokoro",
  voice: null,
  lang: "all",
  audio: null,
  previewVoice: null,
  previewBtn: null,
  generating: false,
  emotions: [],
  segments: null,
};

const curEngine = () => state.engines.find((e) => e.id === state.engine);

/* ---------- Theme ---------- */

function applyTheme(t) {
  body.dataset.theme = t;
  localStorage.setItem("kokoro-theme", t);
}
applyTheme(localStorage.getItem("kokoro-theme") || "light");
$("#theme-toggle").addEventListener("click", () =>
  applyTheme(body.dataset.theme === "dark" ? "light" : "dark")
);

/* ---------- Toasts ---------- */

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

/* ---------- Script panel ---------- */

const scriptEl = $("#script");

function updateCounter() {
  const t = scriptEl.value;
  const words = t.trim() ? t.trim().split(/\s+/).length : 0;
  $("#counter").textContent = `${t.length} chars · ${words} words`;
  if (state.segments) {
    state.segments = null;
    emoSegments.classList.add("hidden");
    emoSegments.innerHTML = "";
    $("#emo-clear").classList.add("hidden");
    emoStatus.textContent = "Script edited — re-run Add emotions";
  }
  refreshGenerate();
}
scriptEl.addEventListener("input", updateCounter);

$("#clear-btn").addEventListener("click", () => {
  scriptEl.value = "";
  updateCounter();
  clearSegments();
});

$("#sample-btn").addEventListener("click", () => {
  scriptEl.value = SAMPLE_SCRIPT;
  updateCounter();
  scriptEl.focus();
});

/* ---------- Emotion director ---------- */

const emoBtn = $("#emo-btn");
const emoStatus = $("#emo-status");
const emoSegments = $("#emo-segments");

async function loadEmotions() {
  try {
    const res = await fetch("/api/emotions");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.emotions = (await res.json()).emotions.map((e) => e.emotion);
  } catch {
    state.emotions = [];
  }
}

function clearSegments() {
  state.segments = null;
  emoSegments.classList.add("hidden");
  emoSegments.innerHTML = "";
  $("#emo-clear").classList.add("hidden");
  emoStatus.textContent = "";
  refreshGenerate();
}

function renderSegments() {
  emoSegments.innerHTML = state.segments
    .map(
      (s, i) => `
      <div class="emo-row" data-emo="${s.emotion}">
        <select data-i="${i}" aria-label="Emotion for segment ${i + 1}">
          ${state.emotions
            .map(
              (e) =>
                `<option ${e === s.emotion ? "selected" : ""}>${e}</option>`
            )
            .join("")}
        </select>
        <div class="emo-text">${s.text}</div>
      </div>`
    )
    .join("");
  emoSegments.querySelectorAll("select").forEach((sel) =>
    sel.addEventListener("change", () => {
      state.segments[+sel.dataset.i].emotion = sel.value;
      sel.closest(".emo-row").dataset.emo = sel.value;
    })
  );
}

emoBtn.addEventListener("click", async () => {
  const text = scriptEl.value.trim();
  if (!text) return toast("Add your script first", "error");

  emoBtn.disabled = true;
  emoStatus.textContent = "Voice director is analyzing the script…";
  try {
    const res = await fetch("/api/enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Analysis failed");
    const data = await res.json();
    state.segments = data.segments;
    renderSegments();
    emoSegments.classList.remove("hidden");
    $("#emo-clear").classList.remove("hidden");
    const used = new Set(data.segments.map((s) => s.emotion));
    emoStatus.textContent = `${data.segments.length} segments · emotions: ${[...used].join(", ")} · script unchanged`;
    toast("Emotions added — review and generate", "ok");
  } catch (err) {
    emoStatus.textContent = "";
    toast(err.message, "error");
  } finally {
    emoBtn.disabled = false;
    refreshGenerate();
  }
});

$("#emo-clear").addEventListener("click", clearSegments);

/* Upload */

const dropzone = $("#dropzone");
const fileInput = $("#file-input");

function readFile(file) {
  if (!file) return;
  if (!/\.txt$/i.test(file.name) && file.type !== "text/plain") {
    toast("Please choose a .txt file", "error");
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    scriptEl.value = reader.result.slice(0, 8000);
    updateCounter();
    $("#drop-hint").textContent = `Loaded ${file.name}`;
    toast(`Loaded ${file.name}`, "ok");
  };
  reader.readAsText(file);
}

$("#browse-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  fileInput.click();
});
fileInput.addEventListener("change", () => readFile(fileInput.files[0]));

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});
["dragover", "dragenter"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  })
);
["dragleave"].forEach((ev) =>
  dropzone.addEventListener(ev, () => dropzone.classList.remove("drag"))
);
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag");
  const file = e.dataTransfer.files[0];
  if (file) readFile(file);
});

/* ---------- Engines ---------- */

function renderEngines() {
  $("#engine-switch").innerHTML = state.engines
    .map(
      (e) => `
      <button class="engine-btn ${e.id === state.engine ? "active" : ""}" role="tab"
              data-engine="${e.id}" aria-selected="${e.id === state.engine}"
              ${e.enabled ? "" : 'disabled title="Needs an NVIDIA GPU — enable with QWEN_ENABLED=1"'}>
        ${e.label} <span class="count">${e.voices.length}</span>
        ${e.enabled ? "" : '<span class="lock">GPU</span>'}
      </button>`
    )
    .join("");
  $("#engine-switch").querySelectorAll(".engine-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      if (!btn.disabled) setEngine(btn.dataset.engine);
    })
  );
}

function setEngine(id) {
  const eng = state.engines.find((e) => e.id === id);
  if (!eng || !eng.enabled || state.engine === id) return;
  if (state.audio) state.audio.pause();
  resetPreview();
  state.engine = id;
  state.voice = null;
  state.lang = "all";
  const chip = $("#voice-chip");
  chip.textContent = "No voice selected";
  chip.classList.remove("set");
  $("#instruct").classList.toggle("hidden", !eng.styles);
  $(".speed-box").classList.toggle("hidden", !eng.speed);
  $("#voice-search").value = "";
  renderEngines();
  renderTabs();
  renderVoices();
  refreshGenerate();
}

/* ---------- Voices ---------- */

const PLAY_SVG =
  '<svg class="icon-play" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
const STOP_SVG =
  '<svg class="icon-stop" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
const LANG_SHORT = {
  "English (US)": "US", "English (UK)": "UK", Spanish: "ES", French: "FR",
  Hindi: "HI", Italian: "IT", Japanese: "JA", "Portuguese (BR)": "BR",
  Mandarin: "ZH", Chinese: "ZH", English: "EN", Korean: "KO", Multilingual: "24 lang",
};

async function loadVoices() {
  const grid = $("#voice-grid");
  try {
    const res = await fetch("/api/voices");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.engines = data.engines;
  } catch (err) {
    grid.innerHTML = "";
    toast(
      `Could not load voices (${err.message}). Is the server running? Open http://127.0.0.1:8000`,
      "error"
    );
    const retry = document.createElement("button");
    retry.className = "link-btn";
    retry.textContent = "Retry";
    retry.addEventListener("click", loadVoices);
    grid.appendChild(retry);
    return;
  }
  renderEngines();
  renderTabs();
  renderVoices();
}

function renderTabs() {
  const voices = curEngine().voices;
  const langs = ["all", ...new Set(voices.map((v) => v.lang))];
  if (langs.length > 12) {
    $("#lang-tabs").innerHTML = `
      <select id="lang-select" class="lang-select" aria-label="Language">
        ${langs
          .map(
            (l) =>
              `<option value="${l}" ${l === state.lang ? "selected" : ""}>${
                l === "all" ? "All languages" : l
              }</option>`
          )
          .join("")}
      </select>`;
    $("#lang-select").addEventListener("change", (e) => {
      state.lang = e.target.value;
      renderVoices();
    });
    return;
  }
  $("#lang-tabs").innerHTML = langs
    .map((l) => {
      const label = l === "all" ? "All" : l;
      return `<button class="tab ${l === state.lang ? "active" : ""}" role="tab" data-lang="${l}">${label}</button>`;
    })
    .join("");
  $("#lang-tabs").querySelectorAll(".tab").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.lang = btn.dataset.lang;
      renderTabs();
      renderVoices();
    })
  );
}

function renderVoices() {
  const grid = $("#voice-grid");
  const q = $("#voice-search").value.trim().toLowerCase();
  const list = curEngine().voices.filter(
    (v) =>
      (state.lang === "all" || v.lang === state.lang) &&
      (!q ||
        v.name.toLowerCase().includes(q) ||
        v.display.toLowerCase().includes(q) ||
        v.lang.toLowerCase().includes(q) ||
        v.desc.toLowerCase().includes(q))
  );
  const MAX_RENDER = 400;
  grid.innerHTML = list
    .slice(0, MAX_RENDER)
    .map(
      (v, i) => `
      <div class="voice-card ${v.name === state.voice ? "selected" : ""}" data-voice="${v.name}" style="animation-delay:${Math.min(i * 8, 150)}ms" tabindex="0">
        <button class="play" aria-label="Preview ${v.name}">${PLAY_SVG}${STOP_SVG}</button>
        <div class="v-info">
          <span class="v-name">${v.display}</span>
          <span class="v-sub">${LANG_SHORT[v.lang] || v.lang} · ${v.desc || v.gender}</span>
        </div>
      </div>`
    )
    .join("");
  if (list.length > MAX_RENDER) {
    grid.insertAdjacentHTML(
      "beforeend",
      `<div class="grid-note">Showing ${MAX_RENDER} of ${list.length} voices — search or pick a language to narrow down</div>`
    );
  }

  grid.querySelectorAll(".voice-card").forEach((card) => {
    card.addEventListener("click", () => selectVoice(card.dataset.voice));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter") selectVoice(card.dataset.voice);
    });
    card.querySelector(".play").addEventListener("click", (e) => {
      e.stopPropagation();
      preview(card.dataset.voice, e.currentTarget);
    });
  });
}
$("#voice-search").addEventListener("input", renderVoices);

function selectVoice(name) {
  state.voice = name;
  document.querySelectorAll(".voice-card").forEach((c) =>
    c.classList.toggle("selected", c.dataset.voice === name)
  );
  const v = curEngine().voices.find((x) => x.name === name);
  const chip = $("#voice-chip");
  chip.textContent = `${v.display} — ${curEngine().label} · ${v.desc || v.gender}`;
  chip.classList.add("set");
  refreshGenerate();
}

/* ---------- Preview playback ---------- */

function ensureAudio() {
  if (!state.audio) {
    state.audio = new Audio();
    state.audio.addEventListener("ended", resetPreview);
    state.audio.addEventListener("error", resetPreview);
  }
  return state.audio;
}

function resetPreview() {
  if (state.previewBtn) {
    state.previewBtn.classList.remove("playing", "loading");
    state.previewBtn.innerHTML = PLAY_SVG + STOP_SVG;
  }
  state.previewVoice = null;
  state.previewBtn = null;
}

async function preview(name, btn) {
  if (state.previewVoice === name) {
    state.audio.pause();
    resetPreview();
    return;
  }
  if (state.audio) state.audio.pause();
  resetPreview();

  state.previewVoice = name;
  state.previewBtn = btn;
  btn.classList.add("loading");
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ engine: state.engine, voice: name }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Preview failed");
    const data = await res.json();
    const audio = ensureAudio();
    audio.src = data.url;
    btn.classList.remove("loading");
    btn.classList.add("playing");
    await audio.play();
  } catch (err) {
    resetPreview();
    toast(err.message, "error");
  }
}

/* ---------- Generate ---------- */

const genBtn = $("#generate");

function refreshGenerate() {
  genBtn.disabled = state.generating || !scriptEl.value.trim() || !state.voice;
}

$("#speed").addEventListener("input", () => {
  $("#speed-val").textContent = (+$("#speed").value).toFixed(2) + "×";
});

genBtn.addEventListener("click", async () => {
  const text = scriptEl.value.trim();
  const hasSegments = !!state.segments;
  if (!text) return toast("Add your script first", "error");
  if (!state.voice) return toast("Pick a voice", "error");
  if (hasSegments && state.engine !== "gemini")
    return toast("Switch to the Gemini engine to use emotion segments", "error");

  state.generating = true;
  refreshGenerate();
  genBtn.classList.add("busy");
  const label = genBtn.querySelector(".btn-label");
  const t0 = Date.now();
  label.textContent = hasSegments ? "Directing emotions…" : "Synthesizing…";

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        engine: state.engine,
        text,
        segments: hasSegments ? state.segments : [],
        voice: state.voice,
        speed: +$("#speed").value,
        instruct: $("#instruct").value.trim(),
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || "Generation failed");
    const data = await res.json();

    $("#player").src = data.url;
    $("#download").href = data.url;
    $("#download").download = `${data.engine}_${data.voice}.wav`;
    $("#result-meta").textContent =
      `${data.engine} · ${data.duration}s · rendered in ${((Date.now() - t0) / 1000).toFixed(1)}s`;
    $("#result").classList.remove("hidden");
    $("#result").scrollIntoView({ behavior: "smooth", block: "nearest" });
    toast(`Audio ready — ${data.duration}s`, "ok");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    state.generating = false;
    genBtn.classList.remove("busy");
    label.textContent = "Generate audio";
    refreshGenerate();
  }
});

/* ---------- Init ---------- */

$("#voice-grid").innerHTML = Array.from({ length: 8 }, () => '<div class="skeleton"></div>').join("");
loadVoices();
loadEmotions();
