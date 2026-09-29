"use strict";

/* ---------- Video Studio tab ---------- */

const $v = (s) => document.querySelector(s);

const vstate = { images: [], jobId: null, pollTimer: null };

/* Tabs */

document.querySelectorAll(".tab-btn").forEach((btn) =>
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $("#tab-tts").classList.toggle("hidden", btn.dataset.tab !== "tts");
    $("#tab-video").classList.toggle("hidden", btn.dataset.tab !== "video");
    if (btn.dataset.tab === "video") loadAudioLibrary();
  })
);

/* Audio source */

async function loadAudioLibrary() {
  const sel = $v("#vs-audio-select");
  const current = sel.value;
  try {
    const res = await fetch("/api/audio/library");
    const files = await res.json();
    sel.innerHTML =
      `<option value="">— pick a generated voiceover —</option>` +
      files
        .map((f) => `<option value="${f.name}">${f.name}</option>`)
        .join("");
    if (current) sel.value = current;
  } catch {
    sel.innerHTML = `<option value="">library unavailable</option>`;
  }
}
$v("#vs-audio-refresh").addEventListener("click", loadAudioLibrary);

/* Images */

const vsDrop = $v("#vs-drop");
const vsInput = document.createElement("input");
vsInput.type = "file";
vsInput.accept = "image/*";
vsInput.multiple = true;

function renderThumbs() {
  $v("#vs-thumbs").innerHTML = vstate.images
    .map(
      (src, i) => `
      <div class="vs-thumb">
        <img src="${src}" alt="scene ${i + 1}">
        <div class="vs-thumb-actions">
          <button data-act="up" data-i="${i}" title="Move earlier" ${i === 0 ? "disabled" : ""}>↑</button>
          <button data-act="down" data-i="${i}" title="Move later" ${i === vstate.images.length - 1 ? "disabled" : ""}>↓</button>
          <button data-act="del" data-i="${i}" title="Remove">×</button>
        </div>
        <span class="vs-num">${i + 1}</span>
      </div>`
    )
    .join("");
  $v("#vs-thumbs").querySelectorAll("button").forEach((btn) =>
    btn.addEventListener("click", () => {
      const i = +btn.dataset.i;
      if (btn.dataset.act === "del") {
        vstate.images.splice(i, 1);
      } else if (btn.dataset.act === "up" && i > 0) {
        [vstate.images[i - 1], vstate.images[i]] = [vstate.images[i], vstate.images[i - 1]];
      } else if (btn.dataset.act === "down" && i < vstate.images.length - 1) {
        [vstate.images[i + 1], vstate.images[i]] = [vstate.images[i], vstate.images[i + 1]];
      }
      renderThumbs();
    })
  );
}

function addImages(files) {
  for (const f of files) {
    if (!f.type.startsWith("image/")) continue;
    vstate.files.push(f);
    vstate.images.push(URL.createObjectURL(f));
  }
  renderThumbs();
}

$v("#vs-browse").addEventListener("click", (e) => {
  e.stopPropagation();
  vsInput.click();
});
vsDrop.addEventListener("click", () => vsInput.click());
vsDrop.addEventListener("keydown", (e) => {
  if (e.key === "Enter") vsInput.click();
});
vsInput.addEventListener("change", () => {
  addImages([...vsInput.files]);
  vsInput.value = "";
});
["dragover", "dragenter"].forEach((ev) =>
  vsDrop.addEventListener(ev, (e) => {
    e.preventDefault();
    vsDrop.classList.add("drag");
  })
);
vsDrop.addEventListener("dragleave", () => vsDrop.classList.remove("drag"));
vsDrop.addEventListener("drop", (e) => {
  e.preventDefault();
  vsDrop.classList.remove("drag");
  addImages([...e.dataTransfer.files]);
});

/* Build + poll */

$v("#vs-create").addEventListener("click", async () => {
  const audioId = $v("#vs-audio-select").value;
  const audioFile = $v("#vs-audio-file").files[0];
  if (!audioId && !audioFile) return toast("Pick or upload audio first", "error");
  if (!vstate.files.length) return toast("Upload at least one story image", "error");

  const fd = new FormData();
  if (audioFile) fd.append("audio", audioFile);
  else fd.append("audio_id", audioId);
  fd.append("script", $v("#vs-script").value);
  vstate.files.forEach((f) => fd.append("images", f, f.name || "scene.jpg"));
  fd.append(
    "options",
    JSON.stringify({
      ratio: $v("#vs-ratio").value,
      resolution: +$v("#vs-res").value,
      transition: $v("#vs-transition").value,
      motion: true,
      captions: $v("#vs-captions").value === "on",
    })
  );

  const btn = $v("#vs-create");
  btn.disabled = true;
  $v("#vs-progress-wrap").classList.remove("hidden");
  $v("#vs-result").classList.add("hidden");
  $v("#vs-stage").textContent = "Uploading…";

  try {
    const res = await fetch("/api/video/build", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || "Build failed");
    const { job_id } = await res.json();
    poll(job_id);
  } catch (err) {
    toast(err.message, "error");
    btn.disabled = false;
    $v("#vs-progress-wrap").classList.add("hidden");
  }
});

function poll(jobId) {
  vstate.pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/video/status/${jobId}`);
      const s = await res.json();
      $v("#vs-stage").textContent = `${s.stage} (${s.pct}%)`;
      $v("#vs-bar").style.width = s.pct + "%";
      if (!s.done) return;
      clearInterval(vstate.pollTimer);
      $v("#vs-create").disabled = false;
      if (s.error) {
        toast(s.error, "error");
        $v("#vs-progress-wrap").classList.add("hidden");
        return;
      }
      $v("#vs-player").src = `/api/video/download/${jobId}`;
      $v("#vs-dl").href = `/api/video/download/${jobId}`;
      $v("#vs-vn").href = `/api/video/vnpack/${jobId}`;
      $v("#vs-result").classList.remove("hidden");
      $v("#vs-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
      toast("Video ready!", "ok");
    } catch (err) {
      clearInterval(vstate.pollTimer);
      $v("#vs-create").disabled = false;
      toast(err.message, "error");
    }
  }, 1500);
}
