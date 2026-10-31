// Buildless single-page app. All record text is inserted with textContent (never innerHTML).
const $ = (s, r = document) => r.querySelector(s);
const app = $("#app");
// replaceChildren would print "null"/"false" for absent optional blocks; drop them instead.
const _rc = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function (...kids) { return _rc.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false)); };
const show = (...kids) => app.replaceChildren(...kids);

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
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
const marks = (r) => [r.starred ? h("span", { class: "mark on", title: "starred" }, "\u2605") : null, r.flagged ? h("span", { class: "mark on", title: "flagged" }, "\u2691") : null, r.notes ? h("span", { class: "mark", title: "comments" }, "\u{1F4AC}" + r.notes) : null];
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
        h("div", { class: "t" }, h("a", { href: "#/r/" + r.id }, r.id), " ", pill(r.status), " ", marks(r), h("div", { class: "small muted" }, r.title || "(untitled)")),
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
  for (const k of ["kind", "status", "starred"]) if (params.get(k)) q.set(k, params.get(k));
  const [rows, ks] = await Promise.all([api("/api/records?" + q), kinds()]);
  const sel = (name, opts) => h("select", { onchange: (e) => { const p = new URLSearchParams(params); e.target.value ? p.set(name, e.target.value) : p.delete(name); location.hash = "#/records?" + p; } },
    h("option", { value: "" }, "all " + name + "s"), opts.map((o) => h("option", { value: o, selected: params.get(name) === o }, o)));
  show(h("h1", {}, "Records"),
    h("div", { class: "actions" }, sel("kind", ks.map((k) => k.name)), sel("status", Object.keys(LABEL)),
      h("button", { class: params.get("starred") ? "on" : "", onclick: () => { const p = new URLSearchParams(params); params.get("starred") ? p.delete("starred") : p.set("starred", "1"); location.hash = "#/records?" + p; } }, "\u2605 starred only")),
    h("div", { class: "card" }, rows.length ? rows.map((r) => h("div", { class: "row" },
      h("div", { class: "t" }, h("a", { href: "#/r/" + r.id }, r.id), " ", pill(r.status), r.creation === "draft" ? h("span", { class: "pill" }, "draft") : null, " ", marks(r),
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
      h("section", { class: "card" }, h("h2", {}, "Notes"), notesPanel(id)),
      d.creation ? h("section", { class: "card" }, h("h2", {}, "Creation steps"), d.creation.steps.map((s) => h("div", { class: "small" }, h("b", {}, s.id), " — ", s.status, s.detail ? h("div", { class: "muted" }, s.detail) : null))) : null));
  if (mode === "dispatch" && dispatchable) dispatchPanel();
}

// ---------- router
async function route() {
  const hash = location.hash.slice(1) || "/";
  const [path, qs] = hash.split("?");
  const params = new URLSearchParams(qs || "");
  const cur = path === "/" || path.startsWith("/stage") ? "map" : path.startsWith("/r/") ? "records" : path.slice(1);
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === cur));
  try {
    let m;
    if (path === "/") await viewMap();
    else if (path === "/dispatch") await viewDispatch();
    else if (path === "/activity") await viewActivity();
    else if ((m = path.match(/^\/stage\/([a-z0-9]+)$/))) await viewStage(m[1]);
    else if (path === "/new") await viewNew(params);
    else if (path === "/records") await viewRecords(params);
    else if ((m = path.match(/^\/r\/([A-Z]+-\d{4,})(?:\/(dispatch))?$/))) await viewRecord(m[1], m[2]);
    else show(h("p", {}, "Not found."));
  } catch (e) { show(errBox(e.errors || [e.message])); }
}
// ---------- notes: comments, stars, flags (site-owned annotations; they never edit records)
const actorName = () => { try { return localStorage.getItem("as-actor") || "owner"; } catch (e) { return "owner"; } };
const postNote = (target, body) => api("/api/notes", { target, actor: actorName(), ...body });
const targetHref = (t) => (t.startsWith("stage:") ? "#/stage/" + t.slice(6).split(".")[0] : "#/r/" + t);

function starButton(target, initial) {
  const b = h("button", { class: "mini" + (initial ? " on" : ""), title: "Star for you" }, initial ? "\u2605" : "\u2606");
  b.addEventListener("click", async (ev) => {
    ev.preventDefault(); ev.stopPropagation();
    try {
      const v = await api("/api/notes?target=" + encodeURIComponent(target));
      const mine = v.starred_by.includes(actorName());
      const n = await postNote(target, { op: "star", on: !mine });
      const now = n.starred_by.includes(actorName());
      b.className = "mini" + (now ? " on" : ""); b.textContent = now ? "\u2605" : "\u2606";
    } catch (e) { toast(e.message); }
  });
  return b;
}

function notesPanel(target, hint) {
  const box = h("div", { class: "notes" });
  const render = (v) => {
    const me = actorName(), mine = v.starred_by.includes(me);
    const byParent = {};
    v.comments.forEach((c) => (byParent[c.parent || ""] ||= []).push(c));
    const act = async (body) => { try { render(await postNote(target, body)); } catch (e) { box.prepend(errBox(e.errors || [e.message])); } };
    const form = (parent, after) => {
      const ta = h("textarea", { placeholder: parent ? "Reply" : "Add a comment", maxlength: "4000" });
      const post = h("button", { class: "primary mini", disabled: true, onclick: () => act({ op: "comment", text: ta.value, parent }) }, "Post");
      ta.addEventListener("input", () => (post.disabled = !ta.value.trim()));
      ta.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && ta.value.trim()) post.click(); });
      return h("div", {}, ta, h("div", { class: "actions" }, post, after));
    };
    const node = (c) => {
      const reply = h("div", { class: "kids" });
      const replyBtn = h("button", { class: "mini", onclick: () => { reply.prepend(form(c.id, h("button", { class: "mini", onclick: () => render(v) }, "Cancel"))); replyBtn.disabled = true; } }, "Reply");
      return h("div", { class: "cm" + (c.retracted ? " gone" : "") },
        h("div", { class: "meta" }, h("b", {}, c.actor), " ", when(c.at)),
        h("div", { class: "txt" }, c.retracted ? "(retracted by author)" : c.text),
        h("div", { class: "actions" }, c.retracted ? null : replyBtn, !c.retracted && c.actor === me ? h("button", { class: "mini", onclick: () => act({ op: "retract", id: c.id }) }, "Retract") : null),
        reply, (byParent[c.id] || []).map(node));
    };
    const flagBtn = v.flag
      ? h("button", { class: "mini on", onclick: () => act({ op: "flag", on: false }) }, "\u2691 Clear flag")
      : h("button", { class: "mini", onclick: () => {
          const r = h("input", { type: "text", placeholder: "why needs attention?" });
          flagBtn.replaceWith(h("span", {}, r, " ", h("button", { class: "mini primary", onclick: () => act({ op: "flag", on: true, reason: r.value }) }, "Flag")));
        } }, "\u2691 Flag");
    box.replaceChildren(
      h("div", { class: "bar" },
        h("button", { class: "mini" + (mine ? " on" : ""), onclick: () => act({ op: "star", on: !mine }) }, (mine ? "\u2605 Starred" : "\u2606 Star") + (v.starred_by.length ? " \u00b7 " + v.starred_by.length : "")),
        flagBtn, hint ? h("span", { class: "small muted" }, hint) : null),
      v.flag ? h("p", { class: "note small" }, "Flagged by " + v.flag.actor + " " + when(v.flag.at) + (v.flag.reason ? ": " + v.flag.reason : "")) : null,
      (byParent[""] || []).map(node), form(null));
  };
  api("/api/notes?target=" + encodeURIComponent(target)).then(render).catch((e) => box.replaceChildren(errBox(e.errors || [e.message])));
  return box;
}

// ---------- stage map
const STATE_TEXT = { built: "built", partial: "partial (v0)", unbuilt: "not built" };
const statePill = (s) => h("span", { class: "pill " + s }, STATE_TEXT[s] || s);
const bucketHref = (b) => "#/records?kind=" + b.kind + (b.statuses.length === 1 ? "&status=" + b.statuses[0] : b.draft ? "&status=new" : "");

async function viewMap() {
  const { stages, gates } = await api("/api/stages");
  const groups = [...new Set(stages.map((s) => s.group))];
  show(h("h1", {}, "Assembly map"),
    h("p", { class: "muted" }, "Every stage and substage of the flow, from the Dispatch briefing. State is probed from the core: a stage the core cannot do yet is shown as not built and offers no actions. Counts are the site's reading of v0 record statuses."),
    h("section", { class: "card" }, h("h2", {}, "Human gates"),
      gates.map((g) => h("div", { class: "row" },
        h("div", { class: "t" }, h("a", { href: "#/stage/" + g.at.split(".")[0] }, g.title), " ", statePill(g.state), g.pending ? h("span", { class: "chip" }, g.pending + " waiting") : null,
          h("div", { class: "small muted" }, g.summary)),
        g.actions.length ? h("a", { class: "btn", href: g.actions[0].route }, g.actions[0].label) : null))),
    h("div", { class: "flow" }, groups.map((g) => [h("div", { class: "grp" }, g),
      h("div", { class: "grid" }, stages.filter((s) => s.group === g).map((s) =>
        h("a", { class: "scard " + s.state + " " + s.key, href: "#/stage/" + s.key },
          h("h3", {}, s.title, statePill(s.state), " ", marks({ starred: s.starred, flagged: s.flagged, notes: s.notes })),
          h("div", { class: "small muted" }, s.summary),
          h("div", { class: "subs" }, s.substages.map((u) => h("span", { class: "chip " + u.state, title: u.reason || u.summary },
            u.title, u.buckets.length ? [" ", h("b", {}, String(u.buckets.reduce((n, b) => n + b.count, 0)))] : null, u.gate ? " \u25C6" : "")))))) ])),
    h("p", { class: "small muted" }, "\u25C6 marks a named human gate. Dashed means not built in the core yet."));
}

async function viewStage(key) {
  const s = await api("/api/stages/" + key);
  show(h("p", { class: "small" }, h("a", { href: "#/" }, "\u2190 Map")),
    h("h1", {}, s.title, " ", statePill(s.state), " ", starButton(s.target, s.starred)),
    h("p", { class: "muted" }, s.summary + " (briefing section " + s.ref + ")"),
    h("section", { class: "card" }, h("h2", {}, "Notes on this stage"), notesPanel(s.target)),
    h("section", { class: "card" }, s.substages.map((u) => {
      const panel = h("div", {});
      return h("div", { class: "sub", id: "sub-" + u.key },
        h("h3", {}, u.title, statePill(u.state), u.gate ? h("span", { class: "gate" }, "\u25C6 gate: " + u.gate) : null, starButton(u.target, u.starred), marks({ flagged: u.flagged, notes: u.notes })),
        h("p", { class: "small muted" }, u.summary),
        u.reason ? h("p", { class: "note small" }, u.reason + " You can still comment, star or flag it; that records a request and starts no work.") : null,
        u.buckets.length ? h("div", { class: "bk" }, u.buckets.map((b) => h("a", { href: bucketHref(b) }, h("b", {}, String(b.count)), b.label))) : null,
        u.actions.length ? h("div", { class: "actions" }, u.actions.map((x, i) => h("a", { class: "btn" + (i === 0 ? " primary" : ""), href: x.route }, x.label))) : null,
        h("div", { class: "actions" }, h("button", { class: "mini", onclick: (e) => { if (panel.firstChild) { panel.replaceChildren(); e.target.textContent = "Notes" + (u.notes ? " (" + u.notes + ")" : ""); } else { panel.append(notesPanel(u.target)); e.target.textContent = "Hide notes"; } } }, "Notes" + (u.notes ? " (" + u.notes + ")" : ""))),
        panel);
    })));
}

async function viewActivity() {
  const d = await api("/api/activity?limit=100");
  const verb = (e) => ({ comment: "commented", star: e.on ? "starred" : "unstarred", flag: e.on ? "flagged" : "cleared flag on" })[e.op] || e.op;
  show(h("h1", {}, "Activity"), h("p", { class: "muted" }, "Comments, stars and flags across records and stages. They are notes about the work and do not change any record."),
    h("div", { class: "two" },
      h("section", { class: "card feed" }, h("h2", {}, "Recent"), d.activity.length ? d.activity.map((e) => h("div", { class: "row" },
        h("div", { class: "t" }, h("b", {}, e.actor), " " + verb(e) + " ", h("a", { href: targetHref(e.target) }, e.title),
          e.op === "comment" ? h("div", { class: "cm" }, h("div", { class: "txt" }, e.retracted ? "(retracted)" : e.text)) : null,
          e.op === "flag" && e.on && e.reason ? h("div", { class: "small muted" }, e.reason) : null),
        h("span", { class: "small muted" }, when(e.at)))) : h("p", { class: "muted" }, "Nothing yet.")),
      h("section", { class: "card" }, h("h2", {}, "Starred"), d.starred.length ? d.starred.map((x) => h("div", { class: "row" },
        h("div", { class: "t" }, h("a", { href: targetHref(x.target) }, x.title), " ", marks({ flagged: x.flagged, notes: x.comments }))))
        : h("p", { class: "muted" }, "Nothing starred."))));
}

try { $("#actor").value = localStorage.getItem("as-actor") || ""; } catch (e) { /* no storage */ }
$("#actor").addEventListener("change", (e) => { try { localStorage.setItem("as-actor", e.target.value.trim().slice(0, 40)); } catch (x) { /* ignore */ } });
addEventListener("hashchange", route);
route();
