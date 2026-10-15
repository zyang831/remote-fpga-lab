"use strict";
// Self-check for static/app.js. No framework, no jsdom: app.js touches a small
// DOM surface (getElementById, createElement, classList, dataset, attributes),
// localStorage, fetch and setInterval, so a handful of stubs is enough to drive it.
//
// Run: node test_app.js

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = fs.readFileSync(path.join(__dirname, "static/app.js"), "utf8");

function makeElement(id) {
  const classes = new Set();
  const attrs = {};
  return {
    id,
    textContent: "",
    innerHTML: "",
    disabled: false,
    hidden: false,
    value: "",
    files: [],
    children: [],
    dataset: {},
    style: { setProperty() {} },
    handlers: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      contains: (c) => classes.has(c),
    },
    addEventListener(ev, fn) {
      this.handlers[ev] = fn;
    },
    getAttribute: (k) => attrs[k] ?? null,
    setAttribute: (k, v) => (attrs[k] = v),
    removeAttribute: (k) => delete attrs[k],
    querySelector: () => makeElement("h2"),
    get lastElementChild() { return (this._last ||= makeElement("span")); },
    focus() {},
    replaceChildren(...c) { this.children = c; },
    appendChild(c) { this.children.push(c); },
    prepend(c) { this.children.unshift(c); },
  };
}

// `routes` maps a URL substring to a response spec; a spec that throws simulates
// a network failure. Returns the loaded app's handles for driving it.
function loadApp(routes, jobId) {
  const els = {};
  const store = jobId ? { "fpga-lab-job-id": jobId } : {};
  const timers = [];

  const sandbox = {
    console,
    document: {
      getElementById: (id) => (els[id] ||= makeElement(id)),
      createElement: (tag) => makeElement(tag),
      addEventListener() {},
      hidden: false,
      title: "FPGA Remote Lab",
    },
    window: { addEventListener() {} },
    URL: { createObjectURL: () => "blob:x", revokeObjectURL() {} },
    confirm: () => true,
    localStorage: {
      getItem: (k) => store[k] ?? null,
      setItem: (k, v) => (store[k] = v),
      removeItem: (k) => delete store[k],
    },
    setInterval: (fn, ms) => timers.push({ fn, ms }),
    Date,
    Math,
    String,
    Object,
    JSON,
    FormData: class {
      append() {}
    },
    async fetch(url) {
      const spec = Object.entries(routes).find(([frag]) => url.includes(frag))?.[1];
      if (!spec) throw new Error(`no stub for ${url}`);
      if (spec.throws) throw new Error("network down");
      return { ok: spec.status === undefined || spec.status < 400, status: spec.status ?? 200, json: async () => spec.body };
    },
  };
  vm.runInNewContext(SRC, sandbox);

  return {
    els,
    timers,
    visible: () => ["idle", "queued", "active", "ended"].find((v) => els[`view-${v}`].classList.contains("visible")),
    poll: () => timers.find((t) => t.ms === 3000).fn(),
    // Everything app.js does is promise-based; a few macrotask turns drain it.
    settle: () => new Promise((r) => setTimeout(r, 0)).then(() => new Promise((r) => setTimeout(r, 0))),
  };
}

async function test_ended_view_survives_polling() {
  const app = loadApp(
    { "/config": { body: { board_stream_url: "http://cam/" } }, "/queue/status": { body: { state: "released" } } },
    "job-1",
  );
  await app.settle();
  assert.strictEqual(app.visible(), "ended", "released job should show the ended view");

  // The bug: the job id is cleared by endSession, so the next tick fell through
  // to `if (!jobId) return show("idle")` and wiped the explanation after ~3s.
  app.poll();
  await app.settle();
  assert.strictEqual(app.visible(), "ended", "ended view must survive the next poll tick");
  assert.match(app.els["ended-detail"].textContent, /default GHRD/);
}

async function test_restart_returns_to_idle() {
  const app = loadApp(
    { "/config": { body: { board_stream_url: "http://cam/" } }, "/queue/status": { body: { state: "released" } } },
    "job-1",
  );
  await app.settle();

  app.els.restart.handlers.click();
  assert.strictEqual(app.visible(), "idle");

  app.poll(); // and polling must stay unstuck afterwards
  await app.settle();
  assert.strictEqual(app.visible(), "idle");
}

async function test_config_failure_still_renders_and_polls() {
  const app = loadApp({ "/config": { throws: true }, "/queue/status": { body: { state: "queued", position: 2 } } }, "job-1");
  await app.settle();
  assert.strictEqual(app.visible(), "idle", "a failed /config must not leave a blank page");
  assert.strictEqual(app.timers.length, 3, "all intervals must start even if boot's fetch failed");

  app.poll();
  await app.settle();
  assert.strictEqual(app.visible(), "queued", "polling must recover once the backend answers");
}

async function test_countdown_uses_relative_seconds_left() {
  const app = loadApp(
    {
      "/config": { body: { board_stream_url: "http://cam/" } },
      "/queue/status": { body: { state: "active", position: null } },
      "/session/status": { body: { seconds_left: 65, program_state: "none", program_error: null, model_state: "none", upload_state: "none" } },
      "/session/ack": { body: {} },
      "/session/models": { body: { models: ["fruit", "flag", "mine"], builtin: ["fruit", "flag"] } },
      "/session/model": { body: { name: "fruit", categories: ["apple", "banana"] } },
    },
    "job-1",
  );
  await app.settle();
  assert.strictEqual(app.visible(), "active");
  // Rebased on the local clock, so this holds whatever the client clock reads.
  assert.strictEqual(app.els["countdown-num"].textContent, "01:05");
  assert.ok(app.els.countdown.classList.contains("expiring"), "under 2 min should flag as expiring");
  return app;
}

async function test_mode_switch_and_model_chips() {
  const app = await test_countdown_uses_relative_seconds_left();
  // Edge AI is the default: chips visible, one per catalog entry + "My model +", the live one pressed.
  assert.strictEqual(app.els["view-active"].dataset.mode, "ai");
  assert.strictEqual(app.els.models.hidden, false);
  const chips = app.els.models.children;
  // Only the user upload gets a delete button.
  assert.deepStrictEqual(chips.map((c) => c.textContent), ["fruit", "flag", "mine", "×", "My model +"]);
  assert.strictEqual(chips[0].getAttribute("aria-pressed"), "true");
  assert.strictEqual(chips[1].getAttribute("aria-pressed"), "false");

  // Board mode hides the chips; the layout swap is data-mode, the markup does the rest.
  app.els["mode-board"].handlers.click();
  assert.strictEqual(app.els["view-active"].dataset.mode, "board");
  assert.strictEqual(app.els.models.hidden, true);
  assert.strictEqual(app.els["mode-board"].getAttribute("aria-pressed"), "true");
  app.poll(); // a poll tick must not flip the mode back
  await app.settle();
  assert.strictEqual(app.els["view-active"].dataset.mode, "board");
  assert.strictEqual(app.els.models.hidden, true);
}

async function test_busy_work_shows_step_and_elapsed() {
  // A 3-minute model load must read as progress: step from the backend, elapsed ticking, spinner on.
  const status = { seconds_left: 600, program_state: "none", program_error: null, model_state: "switching", upload_state: "none",
                   phase: "board downloading the update", busy_seconds: 65 };
  const app = loadApp(
    {
      "/config": { body: { board_stream_url: "http://cam/" } },
      "/queue/status": { body: { state: "active", position: null } },
      "/session/status": { body: status },
      "/session/ack": { body: {} },
      "/session/models": { body: { models: ["fruit"], builtin: ["fruit"] } },
      "/session/model": { body: { name: "fruit", categories: ["apple"] } },
    },
    "job-1",
  );
  await app.settle();
  assert.strictEqual(app.els.veil.hidden, false);
  assert.ok(app.els.veil.classList.contains("wait"), "veil spins while switching");
  assert.match(app.els["veil-title"].textContent, /Loading .*onto the chip/);
  assert.match(app.els["veil-detail"].textContent, /board downloading the update · 01:05 elapsed/);
  assert.strictEqual(app.els.infer.disabled, true);

  // The 1 s tick re-renders from the last status, so the counter moves between polls.
  const realNow = Date.now;
  Date.now = () => realNow() + 2000;
  try {
    app.timers.find((t) => t.ms === 1000).fn();
  } finally {
    Date.now = realNow;
  }
  assert.match(app.els["veil-detail"].textContent, /01:07 elapsed/);

  // Same machinery for a .rbf deploy: the Board-mode status line carries step + elapsed.
  Object.assign(status, { model_state: "none", program_state: "programming", phase: "packaging the bitstream", busy_seconds: 3 });
  app.poll();
  await app.settle();
  assert.match(app.els["program-status"].textContent, /Programming the board.*packaging the bitstream · 00:03 elapsed/);
  assert.ok(app.els["program-status"].classList.contains("wait"));

  // Done: line clears, spinner off, hero back.
  Object.assign(status, { program_state: "ok", phase: null, busy_seconds: null });
  app.poll();
  await app.settle();
  assert.strictEqual(app.els["program-status"].textContent, "");
  assert.ok(!app.els["program-status"].classList.contains("wait"));
}

async function test_queued_wait_line_ticks() {
  const app = loadApp(
    { "/config": { body: { board_stream_url: "http://cam/" } }, "/queue/status": { body: { state: "queued", position: 2, eta_seconds: 900 } } },
    "job-1",
  );
  await app.settle();
  assert.strictEqual(app.visible(), "queued");
  assert.match(app.els["queue-wait"].textContent, /in line 00:00/);
  const realNow = Date.now;
  Date.now = () => realNow() + 61000;
  try {
    app.timers.find((t) => t.ms === 1000).fn();
  } finally {
    Date.now = realNow;
  }
  assert.match(app.els["queue-wait"].textContent, /in line 01:01/);
}

(async () => {
  for (const t of [
    test_ended_view_survives_polling,
    test_restart_returns_to_idle,
    test_config_failure_still_renders_and_polls,
    test_countdown_uses_relative_seconds_left,
    test_mode_switch_and_model_chips,
    test_busy_work_shows_step_and_elapsed,
    test_queued_wait_line_ticks,
  ]) {
    await t();
    console.log("ok:", t.name);
  }
})();
