"use strict";

// Thin client over the lab-backend REST API. One page, four views, swapped by
// job state. Polls because the backend has no push channel (MVP, see plan).
// Users queue for the board, then, inside their session, either program their
// own .rbf (Board mode) or drive the on-chip classifier (Edge AI mode). The mode
// is purely a client-side layout choice: the backend state is the same.

const POLL_MS = 3000;
const STREAM_RETRY_MS = 10000;
const JOB_KEY = "fpga-lab-job-id";
const BASE_TITLE = document.title;

const $ = (id) => document.getElementById(id);

const VIEWS = {
  idle: $("view-idle"),
  queued: $("view-queued"),
  active: $("view-active"),
  ended: $("view-ended"),
};

// Headlines for work the backend does while the browser waits. The live step and
// an elapsed timer are appended by busyLine(), so a long wait never looks stuck.
const MODEL_TEXT = {
  switching: "Loading onto the chip — usually under a minute",
  failed: "Switch failed — the board still runs the previous model.",
};

const UPLOAD_TEXT = {
  none: "",
  building: "Building your model — about a minute in total",
  loading: "Built — now loading it onto the chip",
  ok: "Your model is on the board and in the list above.",
  failed: "",
};

const PROGRAM_TEXT = {
  none: "",
  programming: "Programming the board — usually 5–20 s",
  ok: "",
  failed: "Programming failed — the board is unchanged.",
};

// Single point of truth for the job id, so persistence can change in one place.
const getJobId = () => localStorage.getItem(JOB_KEY);
const setJobId = (id) => (id ? localStorage.setItem(JOB_KEY, id) : localStorage.removeItem(JOB_KEY));

let streamUrl = null;      // from GET /config, fetched once
let maxBytes = Infinity;   // from GET /config; same limit the backend enforces
let model = null;          // {name, categories} from GET /session/model, fetched once per session
let catalog = null;        // model names from GET /session/models, fetched once
let builtin = [];          // the shipped ones: no delete button
let lastModelState = "none"; // previous /session/status model_state, for the switching->ok edge
let lastUploadState = "none";
let lastProgramState = "none";
let sessionEndsAt = null;  // client-clock epoch seconds, only while active
let acked = false;         // POST /session/ack fires once per session
let ended = false;         // holds the ended view until the user clicks "Join again"
let shown = "idle";        // current view name; seeded from the markup so the first paint steals no focus
let lastState = null;      // previous /queue/status state, for the queued->active edge
let programState = "none"; // latest /session/status program_state; gates the Edge AI hero
let rbf = null;            // {name, startedAt} of the .rbf last sent, for the "On the board" card
let pendingModel = null;   // chip to mark busy while /session/status says "switching"
let lastStatus = null;     // latest /session/status body, re-rendered every second for the elapsed timers
let busySince = null;      // client-clock epoch seconds the in-flight deploy/build started (from busy_seconds)
let queuedSince = null;    // client-clock epoch seconds we first saw ourselves in the queue
let uploading = null;      // "program" | "model" while that POST is in flight: its progress line owns the status
let uploaded = false;      // our upload is what the chip is switching to; clears when the switch ends

function show(name) {
  for (const [key, el] of Object.entries(VIEWS)) el.classList.toggle("visible", key === name);
  const active = name === "active";
  for (const id of ["modes", "countdown", "finish"]) $(id).hidden = !active;
  $("models").hidden = !active || VIEWS.active.dataset.mode !== "ai";
  if (name === shown) return;
  shown = name;
  // Focus follows the swap, otherwise it is left on a button that just went display:none.
  const heading = VIEWS[name].querySelector("h2");
  heading.tabIndex = -1;
  heading.focus();
}

function setMode(mode) {
  VIEWS.active.dataset.mode = mode;
  $("mode-board").setAttribute("aria-pressed", String(mode === "board"));
  $("mode-ai").setAttribute("aria-pressed", String(mode === "ai"));
  $("models").hidden = mode !== "ai";
}
$("mode-board").addEventListener("click", () => setMode("board"));
$("mode-ai").addEventListener("click", () => setMode("ai"));
setMode("ai"); // Edge AI is the demo default; the markup carries it too so the first paint matches

const fmtSize = (b) =>
  b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;

function mmss(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

const hhmm = (ms) => new Date(ms).toTimeString().slice(0, 5);

function renderCountdown() {
  if (sessionEndsAt === null) return;
  const left = sessionEndsAt - Date.now() / 1000;
  $("countdown-num").textContent = mmss(left);
  $("countdown").classList.toggle("expiring", left <= 120);
  if (rbf && programState === "ok") $("ob-state").textContent = `running · ${mmss(Date.now() / 1000 - rbf.startedAt)}`;
}

// A status line with the spinner on: text + `busy` class together, so they never drift apart.
function setStatus(el, text, busy) {
  el.textContent = text;
  el.classList.toggle("wait", !!busy && !!text);
}

// "<headline> · <what the backend is doing now> · mm:ss elapsed"
function busyLine(headline) {
  const phase = lastStatus && lastStatus.phase;
  const elapsed = busySince === null ? "" : `${mmss(Date.now() / 1000 - busySince)} elapsed`;
  return [headline, phase, elapsed].filter(Boolean).join(" · ");
}

// fetch() cannot report upload progress; an 8 MB .rbf or a 90 MB model.bin over
// Wi-Fi needs one. Same shape as a fetch Response for the bits the callers use.
function postWithProgress(url, body, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", url);
    x.upload.addEventListener("progress", (e) => e.lengthComputable && onProgress(e.loaded, e.total));
    x.addEventListener("load", () =>
      resolve({ ok: x.status >= 200 && x.status < 300, status: x.status, json: async () => JSON.parse(x.responseText) }),
    );
    x.addEventListener("error", () => reject(new TypeError("network error")));
    x.send(body);
  });
}

const uploadLine = (what, loaded, total) =>
  loaded < total
    ? `Uploading ${what} · ${fmtSize(loaded)} of ${fmtSize(total)} (${Math.round((loaded / total) * 100)} %)`
    : `Upload received · the server is checking ${what}…`;

// Every waiting state, re-rendered each second so the elapsed counters tick.
function renderBusy() {
  if (queuedSince !== null && shown === "queued") {
    $("queue-wait").textContent = `Waiting for the board · in line ${mmss(Date.now() / 1000 - queuedSince)} · this page updates by itself`;
  }
  const s = lastStatus;
  if (!s || shown !== "active") return;
  const programming = s.program_state === "programming";
  const switching = s.model_state === "switching";
  const building = s.upload_state === "building";
  if (uploading !== "program") {
    setStatus($("program-status"), programming ? busyLine(PROGRAM_TEXT.programming) : PROGRAM_TEXT[s.program_state] || "", programming);
  }
  // An upload runs building -> ok -> switching: keep the drawer's line live until the chip has it.
  if (building) setStatus($("upload-status"), busyLine(UPLOAD_TEXT.building), true);
  else if (switching && uploaded) setStatus($("upload-status"), busyLine(UPLOAD_TEXT.loading), true);
  else if (uploading !== "model") setStatus($("upload-status"), UPLOAD_TEXT[s.upload_state] || "", false);
  renderVeil(s);
}

// The MJPEG <img> fires `error` when the board camera is down or drops the
// connection. `load` never fires for a live multipart stream, so the overlay is
// hidden optimistically on each retry and comes back if that retry errors too.
function retryStream() {
  if (!streamUrl) return;
  $("stream-offline").hidden = true;
  $("board-stream").src = `${streamUrl}${streamUrl.includes("?") ? "&" : "?"}_=${Date.now()}`;
}

$("board-stream").addEventListener("error", () => {
  if ($("board-stream").getAttribute("src")) $("stream-offline").hidden = false;
});

function endSession(title, detail) {
  setLive(false);
  sessionEndsAt = null;
  acked = false;
  model = null;
  lastModelState = "none";
  lastUploadState = "none";
  lastProgramState = "none";
  programState = "none";
  rbf = null;
  pendingModel = null;
  lastStatus = null;
  busySince = null;
  queuedSince = null;
  uploaded = false;
  document.title = BASE_TITLE;
  $("stream-offline").hidden = true;
  $("board-stream").removeAttribute("src"); // stop pulling MJPEG off the board
  $("ended-title").textContent = title;
  $("ended-detail").textContent = detail;
  setJobId(null);
  ended = true; // without this the next poll() sees no job id and wipes this view
  show("ended");
}

// "On the board" card (Board mode): what design is running and since when.
function renderOnBoard(s) {
  const cls = { none: "", programming: "busy", ok: "ok", failed: "bad" }[s.program_state] || "";
  $("ob-pill").className = `pill ${cls}`;
  if (s.program_state === "none" || !rbf) {
    $("ob-name").textContent = model ? `${model.name} classifier` : "classifier";
    $("ob-state").textContent = "lab default design";
    return;
  }
  $("ob-name").textContent = rbf.name;
  $("ob-state").textContent = { programming: "programming…", ok: "running", failed: "failed" }[s.program_state];
}

function logProgram(ok) {
  const d = document.createElement("div");
  d.innerHTML = `<time></time><span></span><b></b>`;
  d.children[0].textContent = hhmm(Date.now());
  d.children[1].textContent = rbf.name;
  d.children[2].textContent = ok ? `✓ ${(Date.now() / 1000 - rbf.startedAt).toFixed(0)} s` : "✗";
  d.children[2].className = ok ? "ok" : "bad";
  $("hist-list").prepend(d);
  rbf.startedAt = Date.now() / 1000; // from here on the pill counts run time, not reconfig time
}

// The hero is unusable while the chip is switching models or running a user .rbf.
function renderVeil(s) {
  let title = "", detail = "";
  const switching = s.model_state === "switching";
  if (switching) {
    title = pendingModel ? `Loading ${pendingModel} onto the chip — usually under a minute` : MODEL_TEXT.switching;
    detail = busyLine("");
  } else if (s.program_state !== "none") {
    title = "The board is running your .rbf. Pick a model above to bring the classifier back.";
  }
  $("veil-title").textContent = title;
  $("veil-detail").textContent = detail;
  $("veil").classList.toggle("wait", switching);
  $("veil").hidden = !title;
}

async function enterActive(jobId) {
  const r = await fetch(`/session/status?job_id=${jobId}`);
  if (!r.ok) return;
  const s = await r.json();
  // Re-based on the local clock every poll, so a skewed browser clock cannot skew the timer.
  sessionEndsAt = s.seconds_left === null ? null : Date.now() / 1000 + s.seconds_left;
  busySince = s.busy_seconds == null ? null : Date.now() / 1000 - s.busy_seconds;
  lastStatus = s;

  // Only ever set once per session: a retry appends a cache-buster, so comparing
  // against streamUrl itself would restart the stream on every poll.
  if (streamUrl && !$("board-stream").getAttribute("src")) $("board-stream").src = streamUrl;
  if (!acked) {
    acked = true;
    await fetch(`/session/ack?job_id=${jobId}`, { method: "POST" });
  }

  if (!catalog) await loadCatalog();
  // A finished switch means new labels on the board: refetch them.
  if (lastModelState === "switching" && s.model_state !== "switching") {
    model = null;
    uploaded = false;
  }
  lastModelState = s.model_state;
  if (!model) await loadModel();

  const switching = s.model_state === "switching";
  const building = s.upload_state === "building";
  const programming = s.program_state === "programming";
  const busy = programming || switching || building;
  programState = s.program_state;

  $("program").disabled = busy;
  $("restore").disabled = busy || s.program_state === "none";
  $("program-error").textContent = s.program_error || "";
  if (lastProgramState === "programming" && !programming && rbf) logProgram(s.program_state === "ok");
  lastProgramState = s.program_state;
  renderOnBoard(s);

  for (const b of $("models").children) {
    b.disabled = busy;
    b.classList.toggle("busy", switching && b.dataset.name === pendingModel);
  }
  // The hero follows the board camera whenever the classifier is on the chip and in view.
  // Paused during a file upload: the camera stream and the upload can share one slow uplink.
  const wantLive = !switching && !uploading && s.program_state === "none" && VIEWS.active.dataset.mode === "ai";
  if (wantLive !== live) setLive(wantLive);
  $("model-error").textContent = s.model_error ? `${MODEL_TEXT.failed} ${s.model_error}` : "";
  $("upload-model").disabled = busy;
  if (s.upload_error) $("upload-error").textContent = s.upload_error;
  // A new catalog entry after a successful build: refresh the chips.
  if (lastUploadState === "building" && s.upload_state === "ok") await loadCatalog();
  lastUploadState = s.upload_state;

  renderCountdown();
  show("active");
  renderBusy(); // after show(): it only paints the visible view
}

// Sessions start after a 20 minute wait with the tab backgrounded, and are
// released after ACK_GRACE_SECONDS if nobody shows up. Both channels are
// best-effort: the title always changes, the notification only if permitted.
function announceTurn() {
  if (!document.hidden) return; // they are watching; the view swap already tells them
  document.title = `▶ Your turn! — ${BASE_TITLE}`;
  if (window.Notification && Notification.permission === "granted") {
    new Notification("Your board session started", {
      body: "The board is yours. Come back to the tab within 2 minutes.",
    });
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) document.title = BASE_TITLE;
});

async function poll() {
  if (ended) return; // keep the ended view up until "Join again"
  const jobId = getJobId();
  if (!jobId) return show("idle");

  let r;
  try {
    r = await fetch(`/queue/status?job_id=${jobId}`);
  } catch {
    return; // transient network blip; next tick retries
  }
  if (r.status === 404) {
    // Queue is in-memory: a backend restart forgets every job.
    return endSession("Session lost", "The lab backend restarted and forgot the queue. Please join again.");
  }
  if (!r.ok) return;

  const { state, position, eta_seconds } = await r.json();

  if (state === "active" && lastState === "queued") announceTurn();
  lastState = state;

  if (state === "queued") {
    $("position").textContent = position === null ? "—" : `#${position}`;
    $("eta").textContent =
      eta_seconds == null ? "" : `about ${Math.max(1, Math.round(eta_seconds / 60))} min to wait`;
    queuedSince ??= Date.now() / 1000;
    show("queued");
    renderBusy();
  } else if (state === "active") {
    queuedSince = null;
    await enterActive(jobId);
  } else if (state === "released") {
    endSession("Session ended", "The board has been reset to the default GHRD bitstream.");
  }
}

// Demo shortcut: front of the line, and whoever holds the board is released.
$("skip").addEventListener("click", async () => {
  const err = $("skip-error");
  err.textContent = "";
  const r = await fetch(`/queue/skip?job_id=${getJobId()}`, { method: "POST" }).catch(() => null);
  if (!r || !r.ok) return (err.textContent = `Could not skip (HTTP ${r ? r.status : "network"}).`);
  await poll();
});

$("join").addEventListener("click", async () => {
  const err = $("join-error");
  err.textContent = "";
  // Must be inside the click: browsers only grant permission from a user gesture.
  if (window.Notification && Notification.permission === "default") Notification.requestPermission();
  $("join").disabled = true;
  try {
    const r = await fetch("/queue/join", { method: "POST" });
    if (!r.ok) return (err.textContent = `Could not join the queue (HTTP ${r.status}).`);
    const { job_id } = await r.json();
    setJobId(job_id);
    await poll();
  } finally {
    $("join").disabled = false;
  }
});

// ---- Board mode: .rbf drop zone + program ---------------------------------

function setRbfFile(file) {
  $("dz-name").textContent = file ? `${file.name} · ${fmtSize(file.size)}` : "Drop a .rbf to program";
}
$("dropzone").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", () => setRbfFile($("file").files[0]));
$("dropzone").addEventListener("dragover", (e) => { e.preventDefault(); $("dropzone").classList.add("drop"); });
$("dropzone").addEventListener("dragleave", () => $("dropzone").classList.remove("drop"));
$("dropzone").addEventListener("drop", (e) => {
  e.preventDefault();
  $("dropzone").classList.remove("drop");
  if (e.dataTransfer.files.length) {
    $("file").files = e.dataTransfer.files;
    setRbfFile($("file").files[0]);
  }
});

$("program").addEventListener("click", async () => {
  const file = $("file").files[0];
  const err = $("program-error");
  err.textContent = "";
  if (!file) return (err.textContent = "Choose a .rbf file first.");
  // Same rules the backend enforces, checked here so a doomed 8 MB upload never leaves.
  if (!file.name.toLowerCase().endsWith(".rbf")) return (err.textContent = "File must be a .rbf.");
  if (file.size > maxBytes) {
    return (err.textContent = `File is ${fmtSize(file.size)} — the limit is ${fmtSize(maxBytes)}.`);
  }

  const body = new FormData();
  body.append("bitstream", file);
  // Left disabled on success: poll() re-enables it once the deploy finishes.
  $("program").disabled = true;
  uploading = "program";
  setLive(false);
  setStatus($("program-status"), uploadLine(file.name, 0, file.size), true);
  try {
    const r = await postWithProgress(`/session/program?job_id=${getJobId()}`, body, (loaded, total) =>
      setStatus($("program-status"), uploadLine(file.name, loaded, total), true),
    );
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      err.textContent = detail.detail || `Upload rejected (HTTP ${r.status}).`;
      setStatus($("program-status"), "", false);
      $("program").disabled = false;
      return;
    }
    rbf = { name: file.name, startedAt: Date.now() / 1000 };
    uploading = null;
    await poll();
  } catch {
    err.textContent = "Upload failed — network error.";
    setStatus($("program-status"), "", false);
    $("program").disabled = false;
  } finally {
    uploading = null;
  }
});

// "Restore classifier" = redeploy the model that was live; its bundle carries the DLA design.
$("restore").addEventListener("click", () => switchModel(model ? model.name : catalog && catalog[0], $("program-error")));

// ---- Edge AI mode: model chips, live camera -> board classifier ------------

async function loadModel() {
  const r = await fetch("/session/model");
  if (!r.ok) {
    $("model-error").textContent = "Model info unavailable — the board may still be loading the classifier.";
    return;
  }
  model = await r.json();
  $("model-error").textContent = "";
  renderChips();
}

async function loadCatalog() {
  const r = await fetch("/session/models");
  if (!r.ok) return;
  ({ models: catalog, builtin = [] } = await r.json());
  renderChips();
}

function renderChips() {
  if (!catalog) return;
  const chips = catalog.flatMap((name) => {
    const b = document.createElement("button");
    b.dataset.name = name;
    b.textContent = name;
    b.setAttribute("aria-pressed", String(!!model && model.name === name));
    b.addEventListener("click", () => switchModel(name, $("model-error")));
    if (builtin.includes(name)) return [b];
    const x = document.createElement("button");
    x.className = "del";
    x.textContent = "×";
    x.setAttribute("aria-label", `Delete ${name}`);
    x.addEventListener("click", () => deleteModel(name, $("model-error")));
    return [b, x];
  });
  const own = document.createElement("button");
  own.textContent = "My model +";
  own.addEventListener("click", () => {
    $("drawer").open = true;
    $("upload-name").focus();
  });
  $("models").replaceChildren(...chips, own);
}

// Demo cleanup: a user upload goes away (disk, catalog, update server); the board is untouched.
async function deleteModel(name, err) {
  err.textContent = "";
  if (!confirm(`Delete ${name}? Its files and update-server artifact are removed.`)) return;
  const r = await fetch(`/session/model?job_id=${getJobId()}&name=${encodeURIComponent(name)}`, { method: "DELETE" }).catch(() => null);
  if (!r || !r.ok) {
    const detail = r ? await r.json().catch(() => ({})) : {};
    return (err.textContent = detail.detail || `Delete failed (HTTP ${r ? r.status : "network"}).`);
  }
  await loadCatalog();
}

async function switchModel(name, err) {
  err.textContent = "";
  if (!name) return (err.textContent = "No model catalog loaded.");
  if (model && model.name === name && programState === "none") return;
  for (const b of $("models").children) b.disabled = true;
  try {
    const r = await fetch(`/session/model?job_id=${getJobId()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      err.textContent = detail.detail || `Switch rejected (HTTP ${r.status}).`;
      for (const b of $("models").children) b.disabled = false;
      return;
    }
    pendingModel = name;
    await poll();
  } catch {
    err.textContent = "Switch failed — network error.";
    for (const b of $("models").children) b.disabled = false;
  }
}

// The notebook writes model.xml, model.bin, categories.txt; users drop all three at
// once and each lands in its slot by extension. A later drop replaces only its slot.
const upload = { xml: null, bin: null, cats: null };
const SLOT_BY_EXT = { xml: "xml", bin: "bin", txt: "cats" };

function takeUploadFiles(files) {
  for (const f of files) {
    const slot = SLOT_BY_EXT[f.name.toLowerCase().split(".").pop()];
    if (slot) upload[slot] = f;
  }
  for (const slot of ["xml", "bin", "cats"]) {
    const li = $(`slot-${slot}`);
    li.classList.toggle("ok", !!upload[slot]);
    li.lastElementChild.textContent = upload[slot] ? fmtSize(upload[slot].size) : "";
  }
  $("upload-error").textContent = "";
}
$("upload-zone").addEventListener("click", () => $("upload-files").click());
$("upload-files").addEventListener("change", () => {
  takeUploadFiles([...$("upload-files").files]);
  $("upload-files").value = "";
});
$("upload-zone").addEventListener("dragover", (e) => { e.preventDefault(); $("upload-zone").classList.add("drop"); });
$("upload-zone").addEventListener("dragleave", () => $("upload-zone").classList.remove("drop"));
$("upload-zone").addEventListener("drop", (e) => {
  e.preventDefault();
  $("upload-zone").classList.remove("drop");
  takeUploadFiles([...e.dataTransfer.files]);
});

$("upload-model").addEventListener("click", async () => {
  const err = $("upload-error");
  err.textContent = "";
  const name = $("upload-name").value.trim();
  const { xml, bin, cats } = upload;
  if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(name)) return (err.textContent = "Name: 1-32 chars of a-z, 0-9, -.");
  if (!xml || !bin || !cats) {
    const missing = ["xml", "bin", "cats"].filter((s) => !upload[s]).map((s) => ({ xml: "model.xml", bin: "model.bin", cats: "categories.txt" })[s]);
    return (err.textContent = `Still missing ${missing.join(", ")}.`);
  }

  const body = new FormData();
  body.append("name", name);
  body.append("model_xml", xml);
  body.append("model_bin", bin);
  body.append("categories", cats);
  $("upload-model").disabled = true;
  uploading = "model";
  setLive(false);
  const total = xml.size + bin.size + cats.size;
  setStatus($("upload-status"), uploadLine("your model", 0, total), true);
  try {
    const r = await postWithProgress(`/session/model/upload?job_id=${getJobId()}`, body, (loaded, tot) =>
      setStatus($("upload-status"), uploadLine("your model", loaded, tot), true),
    );
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      err.textContent = detail.detail || `Upload rejected (HTTP ${r.status}).`;
      setStatus($("upload-status"), "", false);
      $("upload-model").disabled = false;
      return;
    }
    pendingModel = name;
    uploaded = true;
    uploading = null;
    await poll();
  } catch {
    err.textContent = "Upload failed — network error.";
    setStatus($("upload-status"), "", false);
    $("upload-model").disabled = false;
  } finally {
    uploading = null;
  }
});

function resetHero() {
  $("h-label").className = "label";
  $("h-conf").textContent = "";
  $("h-bar").style.width = "0";
  $("h-top5").replaceChildren();
  $("h-lat").textContent = "—";
}

// Hero for one live camera frame: the picture, then top-5 and latency once classified.
function renderHero(url, caption, res) {
  $("h-img").src = url;
  $("h-file").textContent = caption;
  resetHero();
  const label = $("h-label");
  if (!res) {
    label.textContent = "…";
    return;
  }
  const [top, ...rest] = res.top5;
  label.textContent = top.label;
  label.className = "label plain";
  $("h-conf").textContent = `${(top.prob * 100).toFixed(1)}%`;
  $("h-bar").style.width = `${Math.max(1, top.prob * 100)}%`;
  $("h-top5").replaceChildren(
    ...rest.map((t) => {
      const d = document.createElement("div");
      d.innerHTML = `<span></span><i></i><b></b>`;
      d.children[0].textContent = t.label;
      d.children[0].title = t.label;
      d.children[1].style.setProperty("--w", `${Math.max(1, t.prob * 100)}%`);
      d.children[2].textContent = `${(t.prob * 100).toFixed(1)}%`;
      return d;
    }),
  );
  $("h-lat").textContent = res.latency_ms.toFixed(0);
}

// Live camera: the hero follows the board's camera stream (~14 fps picture,
// ~4 Hz classification). enterActive() turns it on and off; a dropped stream is
// retried by the next poll.
let live = false;
let liveSrc = null;
function setLive(on) {
  live = on;
  liveSrc?.close();
  liveSrc = on ? liveStream() : null;
}
function liveStream() {
  const src = new EventSource(`/session/camera/stream?job_id=${getJobId()}`);
  // Frames arrive in bursts over the relayed ssh (a stall, then its backlog at
  // once), so arrival times overstate the rate; count frames per >=1 s of the
  // board's own write times instead.
  let t0 = 0, n = 0, fps = 0;
  src.addEventListener("frame", (e) => {
    const data = JSON.parse(e.data);
    const t = data.board_ms;
    if (!t0) t0 = t;
    else n++;
    if (t - t0 >= 1000) {
      fps = (n * 1000) / (t - t0);
      t0 = t;
      n = 0;
    }
    $("infer-error").textContent = "";
    const dla = data.infer_fps ? ` · DLA ${data.infer_fps.toFixed(1)} Hz` : "";
    renderHero(data.image, `LIVE · ${fps.toFixed(1)} fps${dla}`, data.top5 ? data : null);
  });
  src.addEventListener("problem", (e) => ($("infer-error").textContent = JSON.parse(e.data).detail));
  src.addEventListener("fatal", (e) => {
    $("infer-error").textContent = JSON.parse(e.data).detail;
    setLive(false);
  });
  // A refused request (409: not the active session / user .rbf) closes it for good; a dropped one retries.
  src.onerror = () => {
    if (src.readyState !== EventSource.CLOSED || liveSrc !== src) return;
    $("infer-error").textContent = "live camera unavailable for this session";
    setLive(false);
  };
  return src;
}
function clearHero() {
  $("h-img").removeAttribute("src");
  $("h-file").textContent = "";
  $("h-label").textContent = "—";
  resetHero();
  $("infer-error").textContent = "";
}

$("finish").addEventListener("click", async () => {
  // Irreversible: the slot is gone and rejoining puts you at the back of the queue.
  if (!confirm("Release the board now? Your session ends and rejoining puts you at the back of the queue.")) return;
  $("finish").disabled = true;
  await fetch(`/session/finish?job_id=${getJobId()}`, { method: "POST" });
  $("finish").disabled = false;
  await poll();
});

$("restart").addEventListener("click", () => {
  $("file").value = "";
  setRbfFile(null);
  upload.xml = upload.bin = upload.cats = null;
  takeUploadFiles([]);
  $("upload-name").value = "";
  $("hist-list").replaceChildren();
  clearHero();
  setMode("ai");
  ended = false;
  show("idle");
});

// A closed tab holds the board idle until the 20 minute timeout, blocking the
// whole queue. No sendBeacon auto-release: a plain reload would then kill the session.
window.addEventListener("beforeunload", (e) => {
  if (sessionEndsAt === null) return;
  e.preventDefault();
  e.returnValue = "";
});

// Polling must start even if the first requests fail, or a blip leaves a dead page.
(async function boot() {
  try {
    const cfg = await fetch("/config").then((r) => r.json());
    streamUrl = cfg.board_stream_url;
    maxBytes = cfg.max_rbf_bytes ?? Infinity;
    const mp = $("mender-problems");  // from the backend's startup Mender check
    mp.textContent = (cfg.mender_problems ?? []).join(" · ");
    mp.hidden = !mp.textContent;
    if (cfg.max_rbf_bytes) $("dz-limit").textContent = `core .rbf · ≤ ${fmtSize(cfg.max_rbf_bytes)}`;
    await poll();
  } catch {
    show("idle");
  }
  setInterval(poll, POLL_MS);
  setInterval(() => { renderCountdown(); renderBusy(); }, 1000);
  setInterval(() => $("stream-offline").hidden || retryStream(), STREAM_RETRY_MS);
})();

// Single-key shortcuts: a visible, enabled [data-key] button is clicked. Typing in a
// field or holding a modifier is left alone.
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || !/^[a-z0-9]$/i.test(e.key) || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const btn = [...document.querySelectorAll(`[data-key="${e.key.toLowerCase()}"]`)].find((b) => b.offsetParent && !b.disabled);
  if (btn) { e.preventDefault(); btn.click(); }
});
