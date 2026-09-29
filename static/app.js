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
  refreshGenerate();
}
scriptEl.addEventListener("input", updateCounter);

$("#clear-btn").addEventListener("click", () => {
  scriptEl.value = "";
  updateCounter();
});

$("#sample-btn").addEventListener("click", () => {
  scriptEl.value = SAMPLE_SCRIPT;
  updateCounter();
  scriptEl.focus();
});

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
  grid.innerHTML = list
    .map(
      (v, i) => `
      <div class="voice-card ${v.name === state.voice ? "selected" : ""}" data-voice="${v.name}" style="animation-delay:${Math.min(i * 12, 200)}ms" tabindex="0">
        <button class="play" aria-label="Preview ${v.name}">${PLAY_SVG}${STOP_SVG}</button>
        <div class="v-info">
          <span class="v-name">${v.display}</span>
          <span class="v-sub">${LANG_SHORT[v.lang] || v.lang} · ${v.desc || v.gender}</span>
        </div>
      </div>`
    )
    .join("");

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
  if (!text) return toast("Add your script first", "error");
  if (!state.voice) return toast("Pick a voice", "error");

  state.generating = true;
  refreshGenerate();
  genBtn.classList.add("busy");
  const label = genBtn.querySelector(".btn-label");
  const t0 = Date.now();
  label.textContent = "Synthesizing…";

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        engine: state.engine,
        text,
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
