const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const form = $("#configForm");
const toast = $("#toast");
let activePreview = null;
let statusTimer = null;
let tileOptions = [];
let selectedTiles = [];
let rowPattern = [];
const boundRanges = new Set();

function showToast(message, ok = true) {
  toast.hidden = false;
  toast.textContent = message;
  toast.className = `toast ${ok ? "ok" : "bad"}`;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    toast.hidden = true;
  }, 4200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const detail = data?.detail || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function bindRange(name, labelId) {
  const key = `${name}:${labelId}`;
  const input = form.elements.namedItem(name);
  const label = $(labelId);
  const sync = () => {
    label.textContent = input.value;
  };
  if (!boundRanges.has(key)) {
    input.addEventListener("input", sync);
    boundRanges.add(key);
  }
  sync();
}

function addFromTemplate(tplId, listId, values = {}) {
  const node = $(tplId).content.firstElementChild.cloneNode(true);
  for (const [key, val] of Object.entries(values)) {
    const input = node.querySelector(`[data-f="${key}"]`);
    if (input) input.value = val ?? "";
  }
  node.querySelector("[data-remove]")?.addEventListener("click", () => node.remove());
  $(listId).appendChild(node);
  return node;
}

function readRows(listId, fields) {
  return $$(`${listId} .card-row`).map((row) => {
    const obj = {};
    for (const f of fields) {
      obj[f] = row.querySelector(`[data-f="${f}"]`)?.value.trim() || "";
    }
    return obj;
  });
}

function labelForTile(id) {
  return tileOptions.find((o) => o.id === id)?.label || id;
}

function renderTilePicker() {
  const box = $("#tilePicker");
  box.innerHTML = "";
  const selected = new Set(selectedTiles);
  for (const opt of tileOptions) {
    const lab = document.createElement("label");
    lab.className = "chip tile-chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = opt.id;
    input.checked = selected.has(opt.id);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (!selectedTiles.includes(opt.id)) selectedTiles.push(opt.id);
      } else {
        selectedTiles = selectedTiles.filter((t) => t !== opt.id);
      }
      renderTileOrder();
    });
    lab.appendChild(input);
    const span = document.createElement("span");
    span.textContent = opt.label;
    lab.appendChild(span);
    box.appendChild(lab);
  }
  renderTileOrder();
}

function renderTileOrder() {
  const list = $("#tileOrder");
  list.innerHTML = "";
  selectedTiles.forEach((id, idx) => {
    const li = document.createElement("li");
    li.innerHTML = `<code>${escapeHtml(id)}</code> <span>${escapeHtml(labelForTile(id))}</span>`;
    const up = document.createElement("button");
    up.type = "button";
    up.className = "btn tiny";
    up.textContent = "↑";
    up.disabled = idx === 0;
    up.addEventListener("click", () => {
      [selectedTiles[idx - 1], selectedTiles[idx]] = [
        selectedTiles[idx],
        selectedTiles[idx - 1],
      ];
      renderTilePicker();
    });
    const down = document.createElement("button");
    down.type = "button";
    down.className = "btn tiny";
    down.textContent = "↓";
    down.disabled = idx === selectedTiles.length - 1;
    down.addEventListener("click", () => {
      [selectedTiles[idx], selectedTiles[idx + 1]] = [
        selectedTiles[idx + 1],
        selectedTiles[idx],
      ];
      renderTilePicker();
    });
    li.appendChild(up);
    li.appendChild(down);
    list.appendChild(li);
  });
  if (!selectedTiles.length) {
    list.innerHTML = `<li class="muted">Auto (enabled screens)</li>`;
  }
}

function renderRowPattern() {
  const list = $("#rowPatternList");
  list.innerHTML = "";
  rowPattern.forEach((cols, idx) => {
    const li = document.createElement("li");
    li.className = "row-pattern-item";
    li.innerHTML = `<span class="row-badge">${cols === 1 ? "1 · full" : "2 · split"}</span>`;
    const viz = document.createElement("span");
    viz.className = cols === 1 ? "row-viz full" : "row-viz split";
    viz.setAttribute("aria-hidden", "true");
    li.appendChild(viz);
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "btn tiny danger";
    rm.textContent = "Remove";
    rm.addEventListener("click", () => {
      rowPattern.splice(idx, 1);
      renderRowPattern();
    });
    li.appendChild(rm);
    list.appendChild(li);
  });
  if (!rowPattern.length) {
    list.innerHTML = `<li class="muted">No rows yet — add full (1) or split (2)</li>`;
  }
}

function syncLayoutPanels() {
  const layout =
    $$('input[name="layout"]').find((el) => el.checked)?.value || "focus";
  const panel = $("#rowPatternPanel");
  if (panel) panel.hidden = layout !== "custom";
}

function fillConfig(cfg) {
  tileOptions = Array.isArray(cfg.tile_options) ? cfg.tile_options : [];
  form.pixoo_ip.value = cfg.pixoo_ip || "";
  form.brightness.value = cfg.brightness ?? 80;
  form.rotate_seconds.value = cfg.rotate_seconds ?? 18;
  form.preview_mode.checked = !!cfg.preview_mode;
  form.preview_dir.value = cfg.preview_dir || "/preview";
  form.enable_f1.checked = !!cfg.enable_f1;

  const scale = cfg.display?.text_scale || "normal";
  const layout = cfg.display?.layout || "focus";
  $$(`input[name="text_scale"]`).forEach((el) => {
    el.checked = el.value === scale;
  });
  $$(`input[name="layout"]`).forEach((el) => {
    el.checked = el.value === layout;
  });
  form.show_header.checked = cfg.display?.show_header !== false;
  selectedTiles = [...(cfg.display?.tiles || [])];
  // Ensure selected tiles appear in options
  for (const id of selectedTiles) {
    if (!tileOptions.some((o) => o.id === id)) {
      tileOptions.push({ id, label: id });
    }
  }
  rowPattern = [...(cfg.display?.row_pattern || [])].map(Number).filter((n) => n === 1 || n === 2);
  if (layout === "custom" && !rowPattern.length) {
    rowPattern = [1, 1, 1, 2];
  }
  renderTilePicker();
  renderRowPattern();
  syncLayoutPanels();

  $("#viewsList").innerHTML = "";
  for (const view of cfg.views || []) {
    addViewRow(view);
  }

  form.weather_enabled.checked = !!cfg.weather?.enabled;
  form.weather_label.value = cfg.weather?.label || "";
  form.weather_latitude.value = cfg.weather?.latitude ?? "";
  form.weather_longitude.value = cfg.weather?.longitude ?? "";
  form.weather_timezone.value = cfg.weather?.timezone || "";
  form.forecast_days.value = cfg.weather?.forecast_days ?? 1;
  form.weather_show_current.checked = cfg.weather?.show_current !== false;
  form.weather_show_forecast.checked = !!cfg.weather?.show_forecast;
  bindRange("forecast_days", "#forecastDaysVal");

  form.sensibo_enabled.checked = !!cfg.sensibo?.enabled;
  form.sensibo_auto_discover.checked = cfg.sensibo?.auto_discover !== false;
  form.sensibo_api_key.value = "";
  form.clear_sensibo_api_key.checked = false;
  $("#sensiboHint").textContent = cfg.sensibo_api_key_set
    ? `(set ${cfg.sensibo_api_key_hint})`
    : "(not set)";
  form.sensibo_show_temp.checked = cfg.sensibo?.show_temp !== false;
  form.sensibo_show_humidity.checked = cfg.sensibo?.show_humidity !== false;
  form.sensibo_show_power.checked = cfg.sensibo?.show_power !== false;
  form.sensibo_show_mode.checked = cfg.sensibo?.show_mode !== false;
  form.sensibo_show_target.checked = cfg.sensibo?.show_target !== false;
  form.sensibo_show_room.checked = cfg.sensibo?.show_room !== false;

  form.enable_f1.checked = cfg.f1?.enabled !== false && !!cfg.enable_f1;
  form.f1_mode.value = cfg.f1?.mode || "next";
  form.f1_show_countdown.checked = cfg.f1?.show_countdown !== false;
  form.f1_show_datetime.checked = cfg.f1?.show_datetime !== false;
  form.f1_show_race_name.checked = cfg.f1?.show_race_name !== false;
  form.f1_show_country.checked = cfg.f1?.show_country !== false;
  const sess = new Set(cfg.f1?.sessions || []);
  for (const id of ["fp1", "fp2", "fp3", "sq", "sprint", "quali", "race"]) {
    const el = form.elements.namedItem(`f1_sess_${id}`);
    if (el) el.checked = sess.size === 0 ? true : sess.has(id);
  }

  form.schedule_enabled.checked = !!cfg.schedule?.enabled;
  form.schedule_timezone.value = cfg.schedule?.timezone || "Australia/Sydney";
  form.schedule_outside.value = cfg.schedule?.outside || "off";
  $("#scheduleList").innerHTML = "";
  for (const win of cfg.schedule?.windows || []) {
    addWindowRow(win);
  }

  form.traffic_enabled.checked = !!cfg.traffic?.enabled;
  form.google_maps_api_key.value = "";
  form.clear_google_maps_api_key.checked = false;
  $("#googleHint").textContent = cfg.google_maps_api_key_set
    ? `(set ${cfg.google_maps_api_key_hint})`
    : "(not set)";

  $("#routesList").innerHTML = "";
  for (const route of cfg.traffic?.routes || []) {
    addFromTemplate("#tplRoute", "#routesList", route);
  }

  $("#sensiboList").innerHTML = "";
  for (const device of cfg.sensibo?.devices || []) {
    addFromTemplate("#tplSensibo", "#sensiboList", device);
  }

  $("#countdownList").innerHTML = "";
  for (const item of cfg.countdown || []) {
    addFromTemplate("#tplCountdown", "#countdownList", item);
  }

  bindRange("brightness", "#brightnessVal");
  bindRange("rotate_seconds", "#rotateVal");
  toggleSections();
}

function toggleSections() {
  $(".weather-fields").style.opacity = form.weather_enabled.checked ? "1" : "0.45";
  $("#routesList").style.opacity = form.traffic_enabled.checked ? "1" : "0.45";
  $("#sensiboList").style.opacity = form.sensibo_enabled.checked ? "1" : "0.45";
}

function collectPayload() {
  const f1Sessions = ["fp1", "fp2", "fp3", "sq", "sprint", "quali", "race"].filter(
    (id) => form.elements.namedItem(`f1_sess_${id}`)?.checked
  );
  return {
    pixoo_ip: form.pixoo_ip.value.trim(),
    brightness: Number(form.brightness.value),
    rotate_seconds: Number(form.rotate_seconds.value),
    preview_mode: form.preview_mode.checked,
    preview_dir: form.preview_dir.value.trim() || "/preview",
    enable_f1: form.enable_f1.checked,
    f1: {
      enabled: form.enable_f1.checked,
      mode: form.f1_mode.value,
      sessions: f1Sessions,
      show_countdown: form.f1_show_countdown.checked,
      show_datetime: form.f1_show_datetime.checked,
      show_race_name: form.f1_show_race_name.checked,
      show_country: form.f1_show_country.checked,
    },
    display: {
      text_scale:
        $$('input[name="text_scale"]').find((el) => el.checked)?.value || "normal",
      layout: $$('input[name="layout"]').find((el) => el.checked)?.value || "focus",
      show_header: form.show_header.checked,
      tiles: [...selectedTiles],
      row_pattern: [...rowPattern],
    },
    views: readViews(),
    weather: {
      enabled: form.weather_enabled.checked,
      label: form.weather_label.value.trim(),
      latitude: Number(form.weather_latitude.value),
      longitude: Number(form.weather_longitude.value),
      timezone: form.weather_timezone.value.trim(),
      forecast_days: Number(form.forecast_days.value),
      show_current: form.weather_show_current.checked,
      show_forecast: form.weather_show_forecast.checked,
    },
    traffic: {
      enabled: form.traffic_enabled.checked,
      routes: readRows("#routesList", ["name", "origin", "destination"]),
    },
    google_maps_api_key: form.google_maps_api_key.value,
    clear_google_maps_api_key: form.clear_google_maps_api_key.checked,
    sensibo: {
      enabled: form.sensibo_enabled.checked,
      auto_discover: form.sensibo_auto_discover.checked,
      devices: readRows("#sensiboList", ["label", "room", "pod_id"]),
      show_temp: form.sensibo_show_temp.checked,
      show_humidity: form.sensibo_show_humidity.checked,
      show_power: form.sensibo_show_power.checked,
      show_mode: form.sensibo_show_mode.checked,
      show_target: form.sensibo_show_target.checked,
      show_room: form.sensibo_show_room.checked,
    },
    sensibo_api_key: form.sensibo_api_key.value,
    clear_sensibo_api_key: form.clear_sensibo_api_key.checked,
    countdown: readRows("#countdownList", ["label", "at"]),
    schedule: {
      enabled: form.schedule_enabled.checked,
      timezone: form.schedule_timezone.value.trim() || "Australia/Sydney",
      outside: form.schedule_outside.value,
      windows: readWindows(),
    },
  };
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function setHero(name) {
  if (!name) return;
  activePreview = name;
  const url = `/api/preview/${encodeURIComponent(name)}?scale=8&t=${Date.now()}`;
  $("#heroPreview").src = url;
  $$(".thumb").forEach((el) => {
    el.classList.toggle("active", el.dataset.name === name);
  });
}

function renderThumbs(names) {
  const row = $("#thumbRow");
  const existing = new Set($$(".thumb").map((t) => t.dataset.name));
  const incoming = new Set(names);
  $$(".thumb").forEach((t) => {
    if (!incoming.has(t.dataset.name)) t.remove();
  });
  for (const name of names) {
    if (existing.has(name)) {
      const img = row.querySelector(`.thumb[data-name="${CSS.escape(name)}"]`);
      if (img) img.src = `/api/preview/${encodeURIComponent(name)}?scale=4&t=${Date.now()}`;
      continue;
    }
    const img = document.createElement("img");
    img.className = "thumb";
    img.dataset.name = name;
    img.alt = name;
    img.title = name;
    img.width = 64;
    img.height = 64;
    img.src = `/api/preview/${encodeURIComponent(name)}?scale=4&t=${Date.now()}`;
    img.addEventListener("click", () => setHero(name));
    row.appendChild(img);
  }
  if (!activePreview && names[0]) setHero(names[0]);
  if (activePreview && names.includes(activePreview)) setHero(activePreview);
  else if (names[0]) setHero(names[0]);
}

async function refreshStatus() {
  const s = await api("/api/status");
  const pill = $("#runPill");
  const running = !!s.running;
  const hasError = !!s.last_error;
  pill.dataset.state = running ? (hasError ? "error" : "running") : "stopped";
  $("#runLabel").textContent = running
    ? s.preview_mode
      ? "preview"
      : "live"
    : "stopped";

  $("#statCurrent").textContent = s.current_screen || "—";
  $("#statLast").textContent = s.last_screen || "—";
  $("#statPushes").textContent = String(s.pushes ?? 0);
  $("#statErrors").textContent = String(s.errors ?? 0);
  $("#statIp").textContent = s.pixoo_ip || "—";
  $("#statMode").textContent = s.preview_mode
    ? "Preview (PNG)"
    : s.schedule_enabled
      ? s.schedule_active
        ? "Live · in window"
        : "Scheduled off"
      : "Push to device";
  $("#statCount").textContent = `${s.screen_count ?? 0}`;
  $("#statRotate").textContent = `${s.rotate_seconds ?? "—"}s`;
  $("#statPushAt").textContent = fmtTime(s.last_push_at);
  $("#statStarted").textContent = fmtTime(s.started_at);

  const err = $("#statError");
  if (s.last_error) {
    err.hidden = false;
    err.textContent = s.last_error;
  } else {
    err.hidden = true;
  }

  if (Array.isArray(s.screen_names)) {
    renderThumbs(s.screen_names);
  }
}

async function saveConfig(event) {
  event?.preventDefault();
  try {
    const payload = collectPayload();
    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    showToast("Saved. Push loop reloading…", true);
    const cfg = await api("/api/config");
    fillConfig(cfg);
    await refreshStatus();
  } catch (err) {
    showToast(err.message || String(err), false);
  }
}

async function testPixoo() {
  const note = $("#pixooTestNote");
  note.textContent = "Testing…";
  note.className = "inline-note";
  try {
    const payload = collectPayload();
    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    const result = await api("/api/pixoo/test", { method: "POST", body: "{}" });
    note.textContent = result.message;
    note.className = `inline-note ${result.ok ? "ok" : "bad"}`;
  } catch (err) {
    note.textContent = err.message || String(err);
    note.className = "inline-note bad";
  }
}

async function discoverSensibo() {
  const box = $("#sensiboDiscover");
  box.hidden = false;
  box.textContent = "Discovering…";
  try {
    if (form.sensibo_api_key.value.trim()) {
      await api("/api/config", {
        method: "PUT",
        body: JSON.stringify(collectPayload()),
      });
    }
    const data = await api("/api/sensibo/discover");
    box.innerHTML = "";
    if (!data.devices?.length) {
      box.textContent = "No pods found on this account.";
      return;
    }
    for (const d of data.devices) {
      const row = document.createElement("div");
      row.className = "discover-item";
      const temp =
        d.temperature_c == null ? "—" : `${Math.round(d.temperature_c)}°C`;
      const hum = d.humidity == null ? "—" : `${Math.round(d.humidity)}%`;
      row.innerHTML = `
        <div>
          <strong>${escapeHtml(d.room || "Room")}</strong>
          <div style="color:var(--muted);font-size:0.75rem">${escapeHtml(d.pod_id)} · ${temp} · ${hum} · ${d.ac_on ? "ON" : "OFF"} ${escapeHtml(d.mode || "")}</div>
        </div>
      `;
      const pin = document.createElement("button");
      pin.type = "button";
      pin.className = "btn tiny";
      pin.textContent = "Pin";
      pin.addEventListener("click", () => {
        form.sensibo_auto_discover.checked = false;
        addFromTemplate("#tplSensibo", "#sensiboList", {
          label: shorten(d.room || "AC"),
          room: d.room || "",
          pod_id: d.pod_id || "",
        });
        showToast(`Pinned ${d.room}`, true);
      });
      row.appendChild(pin);
      box.appendChild(row);
    }
  } catch (err) {
    box.textContent = err.message || String(err);
  }
}

function shorten(name) {
  return name
    .toUpperCase()
    .replace(/\b(ROOM|THE|BEDROOM|LIVING)\b/g, "")
    .trim()
    .slice(0, 8) || name.slice(0, 8).toUpperCase();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function addWindowRow(values = {}) {
  const node = $("#tplWindow").content.firstElementChild.cloneNode(true);
  const days = Array.isArray(values.days) ? values.days.join(",") : values.days || "all";
  node.querySelector('[data-f="days"]').value = days;
  node.querySelector('[data-f="start"]').value = values.start || "07:00";
  node.querySelector('[data-f="end"]').value = values.end || "22:00";
  node.querySelector("[data-remove]")?.addEventListener("click", () => node.remove());
  $("#scheduleList").appendChild(node);
}

function readWindows() {
  return $$("#scheduleList .window-row").map((row) => ({
    days: (row.querySelector('[data-f="days"]')?.value || "all")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    start: row.querySelector('[data-f="start"]')?.value.trim() || "",
    end: row.querySelector('[data-f="end"]')?.value.trim() || "",
  }));
}

function parsePattern(raw) {
  if (Array.isArray(raw)) {
    return raw.map(Number).filter((n) => n === 1 || n === 2);
  }
  return String(raw || "")
    .split(/[,\s]+/)
    .map((s) => Number(s.trim()))
    .filter((n) => n === 1 || n === 2);
}

function mountViewTilePicker(node, selected) {
  const box = node.querySelector('[data-role="view-tiles"]');
  if (!box) return;
  box.innerHTML = "";
  const order = [...selected];
  const set = new Set(order);
  for (const opt of tileOptions) {
    const lab = document.createElement("label");
    lab.className = "chip tile-chip";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = opt.id;
    input.checked = set.has(opt.id);
    input.addEventListener("change", () => {
      if (input.checked) {
        if (!order.includes(opt.id)) order.push(opt.id);
      } else {
        const i = order.indexOf(opt.id);
        if (i >= 0) order.splice(i, 1);
      }
      box.dataset.tiles = JSON.stringify(order);
    });
    lab.appendChild(input);
    const span = document.createElement("span");
    span.textContent = opt.label;
    lab.appendChild(span);
    box.appendChild(lab);
  }
  box.dataset.tiles = JSON.stringify(order);
}

function addViewRow(values = {}) {
  const node = $("#tplView").content.firstElementChild.cloneNode(true);
  node.querySelector('[data-f="name"]').value = values.name || "";
  node.querySelector('[data-f="layout"]').value = values.layout || "list";
  node.querySelector('[data-f="text_scale"]').value = values.text_scale || "compact";
  const pattern = Array.isArray(values.row_pattern)
    ? values.row_pattern.join(",")
    : values.row_pattern || "";
  node.querySelector('[data-f="row_pattern"]').value = pattern;
  const tiles = Array.isArray(values.tiles)
    ? values.tiles
    : String(values.tiles || "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
  mountViewTilePicker(node, tiles);
  node.querySelector("[data-remove]")?.addEventListener("click", () => node.remove());
  $("#viewsList").appendChild(node);
}

function readViews() {
  return $$("#viewsList .view-row").map((row) => {
    let tiles = [];
    try {
      tiles = JSON.parse(row.querySelector('[data-role="view-tiles"]')?.dataset.tiles || "[]");
    } catch {
      tiles = [];
    }
    return {
      name: row.querySelector('[data-f="name"]')?.value.trim() || "",
      layout: row.querySelector('[data-f="layout"]')?.value || "list",
      text_scale: row.querySelector('[data-f="text_scale"]')?.value || "compact",
      show_header: true,
      tiles,
      row_pattern: parsePattern(row.querySelector('[data-f="row_pattern"]')?.value || ""),
    };
  });
}

function wireUi() {
  $("#btnAddRoute").addEventListener("click", () =>
    addFromTemplate("#tplRoute", "#routesList", { name: "", origin: "", destination: "" })
  );
  $("#btnAddSensibo").addEventListener("click", () =>
    addFromTemplate("#tplSensibo", "#sensiboList", { label: "", room: "", pod_id: "" })
  );
  $("#btnAddCountdown").addEventListener("click", () =>
    addFromTemplate("#tplCountdown", "#countdownList", { label: "", at: "" })
  );
  $("#btnAddView").addEventListener("click", () =>
    addViewRow({
      name: "HOME",
      layout: "rows",
      text_scale: "tiny",
      tiles: ["weather", "sensibo", "f1", "countdown"],
      row_pattern: [1, 1, 1, 2],
    })
  );
  $("#btnAddWindow").addEventListener("click", () =>
    addWindowRow({ days: "mon,tue,wed,thu,fri", start: "07:00", end: "22:00" })
  );
  $("#btnClearTiles")?.addEventListener("click", () => {
    selectedTiles = [];
    renderTilePicker();
  });
  $("#btnAddRow1")?.addEventListener("click", () => {
    rowPattern.push(1);
    renderRowPattern();
  });
  $("#btnAddRow2")?.addEventListener("click", () => {
    rowPattern.push(2);
    renderRowPattern();
  });
  $("#btnClearRows")?.addEventListener("click", () => {
    rowPattern = [];
    renderRowPattern();
  });
  $$('input[name="layout"]').forEach((el) => {
    el.addEventListener("change", () => {
      syncLayoutPanels();
      if (el.value === "custom" && !rowPattern.length) {
        rowPattern = [1, 1, 1, 2];
        renderRowPattern();
      }
    });
  });
  $("#btnSave").addEventListener("click", saveConfig);
  form.addEventListener("submit", saveConfig);
  $("#btnReload").addEventListener("click", async () => {
    try {
      await api("/api/reload", { method: "POST", body: "{}" });
      showToast("Reload requested", true);
      await refreshStatus();
    } catch (err) {
      showToast(err.message, false);
    }
  });
  $("#btnTestPixoo").addEventListener("click", testPixoo);
  $("#btnDiscoverSensibo").addEventListener("click", discoverSensibo);
  $("#btnRefreshPreviews").addEventListener("click", refreshStatus);
  form.weather_enabled.addEventListener("change", toggleSections);
  form.traffic_enabled.addEventListener("change", toggleSections);
  form.sensibo_enabled.addEventListener("change", toggleSections);
}

async function boot() {
  wireUi();
  try {
    const cfg = await api("/api/config");
    fillConfig(cfg);
    await refreshStatus();
    statusTimer = setInterval(() => {
      refreshStatus().catch(() => {});
    }, 4000);
  } catch (err) {
    showToast(err.message || String(err), false);
  }
}

boot();
