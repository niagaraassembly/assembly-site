// Buildless single-page app. All record text is inserted with textContent (never innerHTML).
const $ = (s, r = document) => r.querySelector(s);
const app = $("#app");
// replaceChildren would print "null"/"false" for absent optional blocks; drop them instead.
const _rc = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function (...kids) { return _rc.apply(this, kids.flat().filter((k) => k != null && k !== false)); };
const show = (...kids) => app.replaceChildren(...kids);

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Assembly-Site": "1" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok) { const e = new Error((j.errors || ["error"]).join("; ")); e.errors = j.errors || ["error"]; throw e; }
  return j;
}

let toastT;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2600); }
const errBox = (errs) => h("ul", { class: "err" }, errs.map((e) => h("li", {}, e)));
const pill = (s) => h("span", { class: "pill " + s }, s);
const when = (iso) => (iso || "").replace("T", " ").slice(0, 16);
const LABEL = { new: "Drafts / new", dispatched: "Dispatched", running: "Running", "awaiting-confirmation": "Awaiting you", answered: "Answered", failed: "Failed", retired: "Retired" };

let kindsCache;
const kinds = async () => (kindsCache ||= await api("/api/kinds"));

// ---------- Dispatch home
async function viewDispatch() {
  const s = await api("/api/summary");
  const hb = h("div", { id: "hb" });
  const list = (rows, empty, action) => rows.length
    ? rows.map((r) => h("div", { class: "row" },
        h("div", { class: "t" }, h("a", { href: "#/r/" + r.id }, r.id), " ", pill(r.status), h("div", { class: "small muted" }, r.title || "(untitled)")),
        action ? action(r) : null))
    : h("p", { class: "muted" }, empty);
  const dispatchBtn = (r) => h("a", { class: "btn primary", href: "#/r/" + r.id + "/dispatch" }, "Review & dispatch");
  const reviewBtn = (r) => h("a", { class: "btn", href: "#/r/" + r.id }, r.status === "awaiting-confirmation" ? "Review result" : "Open");
  show(
    h("h1", {}, "Dispatch"),
    h("p", { class: "muted" }, "Capture saves a draft. Dispatch is a separate step: it writes a task document to the outbox for machine-flows. Nothing is run from this site."),
    h("div", { class: "pipe" }, s.pipeline.map((st) => h("a", { href: "#/records?status=" + st }, h("b", {}, s.by_status[st] || 0), h("span", {}, LABEL[st] || st)))),
    h("div", { class: "grid" },
      h("section", { class: "card" }, h("h2", {}, "Drafts ready to dispatch"),
        list(s.drafts, "No drafts. Capture a question to start.", dispatchBtn),
        h("div", { class: "actions" }, h("a", { class: "btn", href: "#/new" }, "Capture new"))),
      h("section", { class: "card" }, h("h2", {}, "Needs you"),
        list(s.attention, "Nothing waiting on you.", reviewBtn)),
      h("section", { class: "card" }, h("h2", {}, "In flight"),
        list(s.in_flight, "Nothing dispatched and unfinished.", reviewBtn),
        h("p", { class: "small muted" }, "In flight means a task document was written to the outbox. It does not mean machine-flows has started it.")),
      h("section", { class: "card" }, h("h2", {}, "Handback from machine-flows"),
        s.runs_present ? h("p", { class: "small muted" }, "Reads run records from " + s.runs + " (read-only).")
          : h("p", { class: "note small" }, "No runs folder at " + s.runs + ". Nothing can be reported as done until machine-flows run records exist."),
        h("div", { class: "actions" }, h("button", { onclick: () => handback(hb, false) }, "Check runs")), hb)));
}

async function handback(box, apply) {
  try {
    const r = await api("/api/handback", { apply });
    box.replaceChildren(
      r.log.length ? h("pre", {}, r.log.join("\n")) : h("p", { class: "muted" }, "No changes."),
      r.log.length && !apply ? h("div", { class: "actions" }, h("button", { class: "primary", onclick: async () => { await handback(box, true); toast("Recorded"); } }, "Record these")) : null,
      apply ? h("div", { class: "actions" }, h("button", { onclick: route }, "Refresh")) : null);
  } catch (e) { box.replaceChildren(errBox(e.errors)); }
}

// ---------- schema-driven form
function fieldInput(f, value) {
  let el;
  if (f.type === "enum") el = h("select", { name: f.name }, h("option", { value: "" }, "—"), f.values.map((v) => h("option", { value: v, selected: v === value }, v)));
  else if (f.type === "bool") el = h("select", { name: f.name }, h("option", { value: "" }, "—"), h("option", { value: "true", selected: value === true }, "true"), h("option", { value: "false", selected: value === false }, "false"));
  else if (f.type === "list") el = h("textarea", { name: f.name, placeholder: "one per line" });
  else if (f.type === "date") el = h("input", { name: f.name, type: "date" });
  else if (f.type === "int") el = h("input", { name: f.name, type: "number", step: "1" });
  else if (f.name === "text" || f.name === "procedure" || (f.description || "").length > 90) el = h("textarea", { name: f.name });
  else el = h("input", { name: f.name, type: "text" });
  if (value != null && f.type !== "enum" && f.type !== "bool") el.value = Array.isArray(value) ? value.join("\n") : String(value);
  el.dataset.type = f.type;
  return el;
}

function buildField(f, value) {
  return h("div", {}, h("label", {}, f.name, f.required ? h("span", { class: "req" }, " *") : null, " ", h("span", { class: "hint" }, f.description || "")), fieldInput(f, value));
}

function readForm(form, fields) {
  const out = {};
  for (const f of fields) {
    const el = form.elements[f.name];
    if (!el) continue;
    let v = el.value.trim();
    if (v === "") continue;
    if (f.type === "int") v = parseInt(v, 10);
    else if (f.type === "bool") v = v === "true";
    else if (f.type === "list") v = v.split("\n").map((x) => x.trim()).filter(Boolean);
    out[f.name] = v;
  }
  return out;
}

// ---------- capture
async function viewNew(params) {
  const ks = await kinds();
  const kind = ks.find((k) => k.name === (params.get("kind") || "question")) || ks[0];
  const form = h("form", {}, kind.fields.filter((f) => f.editable).map((f) => buildField(f)));
  const out = h("div", {});
  const run = async (apply) => {
    try {
      const body = { kind: kind.name, fields: readForm(form, kind.fields), apply };
      const r = await api("/api/captures", body);
      if (!apply) {
        out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Preview"), h("p", { class: "muted small" }, r.note),
          h("dl", { class: "kv" }, Object.entries(r.fields).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, Array.isArray(v) ? v.join(", ") : String(v))])),
          h("p", { class: "small" }, "Steps: " + r.steps.map((s) => s.id + " (" + s.do + ")").join(", ")),
          h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => run(true) }, "Save draft"))));
      } else {
        toast("Saved " + r.record.id);
        location.hash = "#/r/" + r.record.id;
      }
    } catch (e) { out.replaceChildren(errBox(e.errors || [e.message])); }
  };
  form.addEventListener("submit", (ev) => { ev.preventDefault(); run(false); });
  show(h("h1", {}, "Capture"),
    h("p", { class: "muted" }, "Fields and choices come from the Assembly System's schema. Saving creates a draft with a newly minted ID; it is not dispatched."),
    h("div", { class: "tabs" }, ks.map((k) => h("button", { class: k.name === kind.name ? "on" : "", onclick: () => (location.hash = "#/new?kind=" + k.name) }, k.name))),
    h("p", { class: "small muted" }, kind.description),
    h("div", { class: "card" }, form, h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => run(false) }, "Preview"))), out);
}

// ---------- records list
async function viewRecords(params) {
  const q = new URLSearchParams();
  for (const k of ["kind", "status"]) if (params.get(k)) q.set(k, params.get(k));
  const [rows, ks] = await Promise.all([api("/api/records?" + q), kinds()]);
  const sel = (name, opts) => h("select", { onchange: (e) => { const p = new URLSearchParams(params); e.target.value ? p.set(name, e.target.value) : p.delete(name); location.hash = "#/records?" + p; } },
    h("option", { value: "" }, "all " + name + "s"), opts.map((o) => h("option", { value: o, selected: params.get(name) === o }, o)));
  show(h("h1", {}, "Records"),
    h("div", { class: "actions" }, sel("kind", ks.map((k) => k.name)), sel("status", Object.keys(LABEL))),
    h("div", { class: "card" }, rows.length ? rows.map((r) => h("div", { class: "row" },
      h("div", { class: "t" }, h("a", { href: "#/r/" + r.id }, r.id), " ", pill(r.status), r.creation === "draft" ? h("span", { class: "pill" }, "draft") : null,
        h("div", { class: "small muted" }, r.title || "(untitled)")),
      h("span", { class: "small muted" }, when(r.created)))) : h("p", { class: "muted" }, "No records.")));
}

// ---------- record detail
async function viewRecord(id, mode) {
  const [d, ks] = await Promise.all([api("/api/records/" + id), kinds()]);
  const rec = d.record, kind = ks.find((k) => k.name === rec.kind);
  const retired = rec.status === "retired";
  const panel = h("div", { id: "panel" });

  const dispatchPanel = async () => {
    try {
      const p = await api("/api/records/" + id + "/dispatch");
      const ok = h("input", { type: "checkbox", id: "ok" });
      const go = h("button", { class: "primary", disabled: true, onclick: async () => { try { await api("/api/records/" + id + "/dispatch", { apply: true }); toast("Task document written"); viewRecord(id); } catch (e) { panel.prepend(errBox(e.errors)); } } }, "Write to outbox");
      ok.addEventListener("change", () => (go.disabled = !ok.checked));
      panel.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Dispatch preview"), h("p", { class: "muted small" }, p.meaning),
        p.tasks.map((t) => h("div", {}, h("p", { class: "small" }, "File: ", h("code", {}, t.file), t.written ? " (already in outbox; identical rewrite is a no-op)" : ""), h("pre", {}, t.markdown))),
        p.errors.length ? errBox(p.errors) : h("div", { class: "actions" }, h("label", { class: "inline" }, ok, " I have read the task and its approval/permission tags"), go)));
    } catch (e) { panel.replaceChildren(errBox(e.errors)); }
  };

  const editPanel = () => {
    const fields = kind.fields.filter((f) => f.editable);
    const form = h("form", {}, fields.map((f) => buildField(f, rec.fields[f.name])));
    const out = h("div");
    const collect = () => {
      const now = readForm(form, fields), set = {}, unset = [];
      for (const f of fields) {
        const was = rec.fields[f.name], v = now[f.name];
        if (v === undefined) { if (was != null && was !== "" ) unset.push(f.name); }
        else if (JSON.stringify(v) !== JSON.stringify(was)) set[f.name] = v;
      }
      return { set, unset };
    };
    const preview = async () => {
      try {
        const c = collect(), p = await api("/api/records/" + id + "/set", c);
        if (!p.diff.length) return out.replaceChildren(h("p", { class: "muted" }, "No changes."));
        out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Changes"), h("dl", { class: "kv" }, p.diff.flatMap((x) => [h("dt", {}, x.field), h("dd", {}, (x.old == null ? "(unset)" : String(x.old)) + " → " + (x.new == null ? "(unset)" : String(x.new)))])),
          p.redispatch ? h("p", { class: "note small" }, "This record was dispatched. After saving, dispatch again to write a revised task document beside the earlier one.") : null,
          h("div", { class: "actions" }, h("button", { class: "primary", onclick: async () => { try { await api("/api/records/" + id + "/set", { ...c, apply: true }); toast("Saved (rev bumped)"); viewRecord(id); } catch (e) { out.prepend(errBox(e.errors)); } } }, "Save change"))));
      } catch (e) { out.replaceChildren(errBox(e.errors)); }
    };
    form.addEventListener("submit", (ev) => { ev.preventDefault(); preview(); });
    panel.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Edit metadata"), form, h("div", { class: "actions" }, h("button", { class: "primary", onclick: preview }, "Preview change"))), out);
  };

  const retirePanel = () => {
    const reason = h("input", { type: "text", placeholder: "reason" });
    panel.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Retire " + id), h("p", { class: "muted small" }, "Nothing is deleted. A retired record is read-only and is never dispatched."), reason,
      h("div", { class: "actions" }, h("button", { class: "danger", onclick: async () => { try { await api("/api/records/" + id + "/retire", { reason: reason.value, apply: true }); toast("Retired"); viewRecord(id); } catch (e) { panel.prepend(errBox(e.errors)); } } }, "Retire"))));
  };

  const dispatchable = kind.dispatchable && d.tasks.length > 0 && !retired;
  const actions = h("div", { class: "actions" },
    dispatchable ? h("button", { class: "primary", onclick: dispatchPanel }, rec.status === "new" ? "Review & dispatch" : "Dispatch again") : null,
    rec.status === "awaiting-confirmation" ? h("button", { class: "primary", onclick: async () => { try { await api("/api/records/" + id + "/confirm", {}); toast("Marked answered"); viewRecord(id); } catch (e) { panel.prepend(errBox(e.errors)); } } }, "Confirm answered") : null,
    !retired ? h("button", { onclick: editPanel }, "Edit metadata") : null,
    !retired ? h("button", { class: "danger", onclick: retirePanel }, "Retire") : null);

  show(
    h("p", { class: "small" }, h("a", { href: "#/records" }, "← Records")),
    h("h1", {}, id, " ", pill(rec.status), d.creation && d.creation.state === "draft" ? h("span", { class: "pill" }, "draft") : null),
    h("p", { class: "muted small" }, rec.kind + " · rev " + (rec.rev || 0) + " · created " + when(rec.created)),
    rec.status === "awaiting-confirmation" ? h("p", { class: "note" }, "machine-flows reports this run as done. Read the result, then confirm; only you mark a question answered.") : null,
    rec.status === "dispatched" ? h("p", { class: "note small" }, "A task document was written. It stays dispatched until a machine-flows run record says otherwise (use Check runs on the Dispatch page).") : null,
    actions, panel,
    h("div", { class: "grid" },
      h("section", { class: "card" }, h("h2", {}, "Fields"), h("dl", { class: "kv" },
        Object.entries(rec.fields).sort().flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, Array.isArray(v) ? v.join(", ") : String(v))]))),
      h("section", { class: "card" }, h("h2", {}, "History"), h("ul", { class: "tl" },
        [...rec.history].reverse().map((e) => h("li", {}, h("b", {}, e.event), " ", h("span", { class: "muted small" }, when(e.at)), e.detail ? h("div", { class: "small" }, e.detail) : null)))),
      d.creation ? h("section", { class: "card" }, h("h2", {}, "Creation steps"), d.creation.steps.map((s) => h("div", { class: "small" }, h("b", {}, s.id), " — ", s.status, s.detail ? h("div", { class: "muted" }, s.detail) : null))) : null));
  if (mode === "dispatch" && dispatchable) dispatchPanel();
}

// ---------- router
async function route() {
  const hash = location.hash.slice(1) || "/";
  const [path, qs] = hash.split("?");
  const params = new URLSearchParams(qs || "");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", (path === "/" && a.dataset.r === "dispatch") || path.startsWith("/" + a.dataset.r)));
  try {
    let m;
    if (path === "/") await viewDispatch();
    else if (path === "/new") await viewNew(params);
    else if (path === "/records") await viewRecords(params);
    else if ((m = path.match(/^\/r\/([A-Z]+-\d{4,})(?:\/(dispatch))?$/))) await viewRecord(m[1], m[2]);
    else show(h("p", {}, "Not found."));
  } catch (e) { show(errBox(e.errors || [e.message])); }
}
addEventListener("hashchange", route);
route();
