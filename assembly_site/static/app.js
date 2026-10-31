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

const cleanups = [];
const diffView = (d) => d === null || d === undefined ? null
  : d === "" ? h("p", { class: "small muted" }, "Identical to the earlier task document, so writing it again changes nothing.")
  : h("div", {}, h("p", { class: "small" }, "Changes from the earlier task document:"), h("pre", { class: "diff" }, d.split("\n").map((l) => h("span", { class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "" }, l + "\n"))));

let toastT;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 2600); }
const errBox = (errs) => h("ul", { class: "err" }, errs.map((e) => h("li", {}, e)));
const pill = (s) => h("span", { class: "pill " + s }, s);
const marks = (r) => [r.starred ? h("span", { class: "mark on", title: "starred" }, "\u2605") : null, r.flagged ? h("span", { class: "mark on", title: "flagged" }, "\u2691") : null, r.notes ? h("span", { class: "mark", title: "comments" }, "\u{1F4AC}" + r.notes) : null];
const when = (iso) => (iso || "").replace("T", " ").slice(0, 16);
const LABEL = { new: "Drafts / new", dispatched: "Dispatched", running: "Running", "awaiting-confirmation": "Awaiting you", answered: "Answered", failed: "Failed", retired: "Retired" };

let kindsCache;
const kinds = async () => (kindsCache ||= await api("/api/kinds"));

// ---------- Dispatch workbench: what to do next, in order
const today = () => new Date().toLocaleDateString("en-CA");
const READY_TEXT = { held: "held", ready: "ready", "in-flight": "in flight", "needs-you": "needs you", failed: "failed", manual: "manual filing", blocked: "blocked", done: "done" };
const readyPill = (r) => h("span", { class: "pill rd-" + r }, READY_TEXT[r] || r);

async function viewDispatch() {
  const w = await api("/api/workbench?on=" + today());
  const hb = h("div", { id: "hb" });
  const qrow = (r, btn) => h("div", { class: "row" },
    h("div", { class: "t" }, h("a", { href: "#/r/" + r.id }, r.id), " ", pill(r.status), " ", marks(r), h("div", { class: "small muted" }, r.title || "(untitled)")), btn);
  const open = (label) => (r) => h("a", { class: "btn", href: "#/r/" + r.id }, label);
  const empty = (t) => h("p", { class: "muted small" }, t);
  const lane = (title, sub, n, ...body) => h("section", { class: "card lane" }, h("h2", {}, title, " ", h("span", { class: "count" }, String(n))), h("p", { class: "small muted" }, sub), body);

  const auto = (() => { try { return localStorage.getItem("as-auto") === "1"; } catch (e) { return false; } })();
  const banner = h("div", { id: "autobanner" });
  const poll = async () => { try { const r = await api("/api/handback", { apply: false }); if (r.log.length) banner.replaceChildren(h("div", { class: "note" }, r.log.length + " run update(s) available: ", h("button", { class: "mini primary", onclick: () => handback(hb, false) }, "Review them"))); } catch (e) { /* ignore */ } };
  if (auto) { poll(); const t = setInterval(poll, 60000); cleanups.push(() => clearInterval(t)); }
  show(h("h1", {}, "Dispatch"), banner,
    h("p", { class: "muted" }, "Capture saves a draft. Dispatching writes a task document to the outbox for machine-flows. Nothing is run from this site."),
    h("ol", { class: "steps" }, w.steps.map((s) => h("li", { class: s.count ? "has" : "" },
      h("a", { href: s.route || "#/dispatch", onclick: s.route ? null : (e) => { e.preventDefault(); hb.scrollIntoView({ behavior: "smooth" }); } }, h("span", { class: "lab" }, s.label), h("b", {}, String(s.count)), h("span", { class: "hint" }, s.hint))))),
    h("section", { class: "card nextup" }, h("h2", {}, "Next up"),
      w.next.map((n, i) => h("div", { class: "next" + (i === 0 ? " first" : "") },
        h("div", {}, h("b", {}, n.label), h("div", { class: "small muted" }, n.detail)),
        n.route ? h("a", { class: "btn" + (i === 0 ? " primary" : ""), href: n.route }, n.cta) : h("button", { class: i === 0 ? "primary" : "", onclick: () => handback(hb, false) }, n.cta)))),
    h("div", { class: "grid" },
      lane("Ready to dispatch", "Grouped by bundle. Preview the task documents, then write them.", w.ready_bundles.reduce((n, b) => n + b.counts.ready, 0),
        w.ready_bundles.length ? w.ready_bundles.map((b) => h("div", { class: "row" },
          h("div", { class: "t" }, h("b", {}, bundleTitle(b)), h("div", { class: "small muted" }, keyLine(b.key))),
          h("a", { class: "btn primary", href: "#/bundles?open=" + b.key_id }, "Dispatch " + b.counts.ready))) : empty("Nothing is ready. Capture a question, or see Bundles.")),
      lane("Needs you", "Finished runs wait for your confirmation. Only you mark a question answered.", w.needs_you.length,
        w.needs_you.length ? w.needs_you.map((r) => qrow(r, open("Review result")(r))) : empty("Nothing waiting on you.")),
      lane("In flight", "A task document was written. It does not mean machine-flows has started it.", w.in_flight.length,
        w.in_flight.length ? w.in_flight.map((r) => qrow(r, open("Open")(r))) : empty("Nothing dispatched and unfinished."),
        w.runs_present ? h("p", { class: "small muted" }, "Reads run records from " + w.runs + " (read-only).")
          : h("p", { class: "note small" }, "No runs folder at " + w.runs + ". Nothing can be reported as done until machine-flows run records exist."),
        h("div", { class: "actions" }, h("button", { onclick: () => handback(hb, false) }, "Check runs"),
          h("label", { class: "inline" }, h("input", { type: "checkbox", checked: auto, onchange: (e) => { try { localStorage.setItem("as-auto", e.target.checked ? "1" : "0"); } catch (x) { /* none */ } route(); } }), " Look for updates every minute")), hb),
      lane("Failed", "machine-flows reports these runs failed or were cancelled.", w.failed.length,
        w.failed.length ? w.failed.map((r) => qrow(r, open("Look")(r))) : empty("No failures."))),
    w.excluded.length ? h("p", { class: "small muted" }, w.excluded.length + " question(s) are not planned (retired or already answered). See Bundles.") : null);
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

// ---------- Bundles
const KEY_LABEL = { region: "Region", cadence: "Cadence", intake: "Intake", origin: "Origin", sensitivity: "Sensitivity", trust: "Trust", effort: "Effort" };
const KEY_WHY = { region: "Where the question is about", cadence: "How often it runs", intake: "Scan runs automatically; file needs a person", origin: "Internal or external asker",
  sensitivity: "Who may see results", trust: "External text is untrusted and needs approval", effort: "Depth of the run (not stated in v0)" };
const bundleTitle = (b) => b.key_id + (b.of > 1 ? " \u00b7 part " + b.part + " of " + b.of : "");
const keyLine = (k) => Object.keys(KEY_LABEL).map((f) => KEY_LABEL[f] + " " + (k[f] || "unstated")).join(" \u00b7 ");

async function viewSchedule(params) {
  const from = params.get("on") || today();
  const s = await api("/api/schedule?days=7&from=" + from);
  const shift = (n) => { const d = new Date(from + "T12:00:00"); d.setDate(d.getDate() + n); const p = new URLSearchParams(params); p.set("on", d.toLocaleDateString("en-CA")); location.hash = "#/bundles?" + p; };
  show(h("h1", {}, "Bundles"), viewTabs("schedule", params),
    h("p", { class: "muted" }, "Which bundles come due each day, from the questions' cadence. Click one to open it on that day."),
    h("div", { class: "actions" }, h("button", { onclick: () => shift(-7) }, "\u2190 Earlier"), h("button", { onclick: () => { const p = new URLSearchParams(params); p.delete("on"); location.hash = "#/bundles?" + p; } }, "This week"), h("button", { onclick: () => shift(7) }, "Later \u2192")),
    h("div", { class: "week" }, s.days.map((d) => h("section", { class: "card day" + (d.on === today() ? " today" : "") }, h("h2", {}, d.weekday + " ", h("span", { class: "muted small" }, d.on.slice(5))), h("div", { class: "small muted" }, d.period),
      d.bundles.length ? d.bundles.map((b) => h("a", { class: "dayb", href: "#/bundles?view=bundles&on=" + d.on + "&open=" + b.key_id }, h("b", {}, b.questions + "q"), " " + [b.key.region || "no region", b.key.cadence || "unstated", b.key.intake].join(" \u00b7 ") + (b.of > 1 ? " (part " + b.part + ")" : ""))) : h("p", { class: "muted small" }, "Nothing due.")))));
}

const viewTabs = (cur, params) => h("div", { class: "tabs" }, ["bundles", "schedule"].map((t) => h("button", { class: cur === t ? "on" : "", onclick: () => { const p = new URLSearchParams(params); p.set("view", t); location.hash = "#/bundles?" + p; } }, t === "bundles" ? "Bundles" : "Week schedule")));

async function viewBundles(params) {
  if (params.get("view") === "schedule") return viewSchedule(params);
  const on = params.get("on") || today();
  const v = await api("/api/bundles?on=" + on);
  const t = v.totals;
  const setOn = (d) => { const p = new URLSearchParams(params); p.set("on", d); location.hash = "#/bundles?" + p; };
  const stat = (n, label, cls) => h("div", { class: "stat " + (cls || "") }, h("b", {}, String(n)), h("span", {}, label));
  show(h("h1", {}, "Bundles"), viewTabs("bundles", params),
    h("p", { class: "muted" }, "Questions grouped by region and cadence. A bundle is defined by its labelled key, so one question can be a bundle. Sources do not split bundles. Different keys never mix. Grouping is a preview; dispatching is the action."),
    h("div", { class: "actions" }, h("label", { class: "inline" }, "Planning day ", h("input", { type: "date", value: on, onchange: (e) => e.target.value && setOn(e.target.value) })),
      h("button", { onclick: () => setOn(today()) }, "Today"), h("span", { class: "small muted" }, "News week " + v.period + " (Sunday starts the week)")),
    h("div", { class: "stats" }, stat(v.bundles.length, "bundles"), stat(t.ready, "ready to dispatch", "ok"), stat(t["in-flight"], "in flight"), stat(t["needs-you"], "need you", "warn"),
      stat(t.failed, "failed", "bad"), stat(t.manual + t.blocked, "manual / blocked"), stat(v.excluded.length, "not planned")),
    v.bundles.length ? v.bundles.map((b) => bundleCard(b, on, params.get("open") === b.key_id)) : h("section", { class: "card" }, h("p", { class: "muted" }, "No questions to bundle."), h("a", { class: "btn primary", href: "#/new?kind=question" }, "Capture a question")),
    v.excluded.length ? h("section", { class: "card" }, h("h2", {}, "Not planned"), v.excluded.map((x) => h("div", { class: "row" }, h("a", { href: "#/r/" + x.id }, x.id), h("span", { class: "small muted" }, x.reason)))) : null);
  const o = params.get("open");
  if (o) { const el = document.getElementById(o); if (el) el.scrollIntoView(); }
}

async function holdIt(id, on) {
  let reason = "";
  if (on) { reason = prompt("Why hold " + id + "? (shown to everyone on the site)") ; if (reason === null) return; }
  try { await postNote(id, { op: "hold", on, reason }); toast(on ? "Held " + id : "Released " + id); route(); } catch (e) { toast(e.message); }
}

function bundleCard(b, on, expanded) {
  const picks = new Set(b.members.filter((m) => m.readiness === "ready").map((m) => m.id));
  const out = h("div", { class: "bout" });
  const bar = h("div", { class: "actions bar" });
  const selCount = () => h("span", { class: "small" }, picks.size + " of " + b.counts.ready + " ready selected");
  const renderBar = () => bar.replaceChildren(
    b.counts.ready ? h("button", { class: "primary", disabled: !picks.size, onclick: preview }, "Preview dispatch (" + picks.size + ")") : h("span", { class: "muted small" }, "Nothing ready in this bundle."),
    b.counts.ready ? selCount() : null,
    b.counts.ready ? h("button", { disabled: !picks.size, onclick: async () => { const r = prompt("Why hold these " + picks.size + " questions?"); if (r === null) return; for (const id of picks) await postNote(id, { op: "hold", on: true, reason: r }); toast("Held " + picks.size); route(); } }, "Hold selected") : null);
  const preview = async () => {
    try {
      const p = await api("/api/bundles/" + b.key_id + "/dispatch", { on, ids: [...picks], apply: false });
      const ok = h("input", { type: "checkbox" });
      const go = h("button", { class: "primary", disabled: true, onclick: async () => {
        go.disabled = true;
        try {
          const r = await api("/api/bundles/" + b.key_id + "/dispatch", { on, ids: [...picks], apply: true });
          out.replaceChildren(h("div", { class: "card inner" }, h("h2", {}, "Dispatch result"),
            r.results.map((x) => h("div", { class: "row" }, h("a", { href: "#/r/" + x.id }, x.id), x.ok ? h("span", { class: "pill answered" }, "task document written") : errBox(x.errors))),
            h("div", { class: "actions" }, h("button", { class: "primary", onclick: route }, "Refresh bundles"))));
          toast("Dispatched " + r.results.filter((x) => x.ok).length);
        } catch (e) { out.prepend(errBox(e.errors)); go.disabled = false; }
      } }, "Write " + p.members.length + " task document" + (p.members.length === 1 ? "" : "s"));
      ok.addEventListener("change", () => (go.disabled = !ok.checked));
      out.replaceChildren(h("div", { class: "card inner" }, h("h2", {}, "Dispatch preview"), h("p", { class: "small muted" }, p.meaning),
        p.members.map((m) => {
          const md = m.tasks[0].markdown;
          const tag = (k) => (md.match(new RegExp("^" + k + ":\\s*(.*)$", "m")) || [])[1];
          return h("details", {}, h("summary", {}, h("b", {}, m.id), " ", h("code", {}, m.tasks[0].file), " ",
            h("span", { class: "chip" }, "permission " + (tag("permission") || "?")), h("span", { class: "chip" + (tag("approval") === "none" ? "" : " partial") }, "approval " + (tag("approval") || "?"))), diffView(m.tasks[0].diff), h("pre", {}, md));
        }),
        h("div", { class: "actions" }, h("label", { class: "inline" }, ok, " I have read these task documents, including approval and permission"), go, h("button", { onclick: () => out.replaceChildren() }, "Cancel"))));
    } catch (e) { out.replaceChildren(errBox(e.errors)); }
  };
  renderBar();
  const rows = b.members.map((m) => {
    const cb = h("input", { type: "checkbox", checked: m.readiness === "ready", disabled: m.readiness !== "ready", "aria-label": "include " + m.id });
    cb.addEventListener("change", () => { cb.checked ? picks.add(m.id) : picks.delete(m.id); renderBar(); });
    return h("tr", {}, h("td", {}, cb), h("td", {}, h("a", { href: "#/r/" + m.id }, m.id)), h("td", { class: "qt" }, m.title || "(untitled)", h("div", { class: "small muted" }, m.why)),
      h("td", {}, readyPill(m.readiness), m.needs_approval && m.readiness === "ready" ? h("span", { class: "chip partial", title: "The run will wait for your approval" }, "approval needed") : null),
      h("td", {}, pill(m.status)), h("td", {}, h("span", { class: "chip " + (m.due ? "built" : "") }, m.due ? "due" : "not due"), " ", marks(m)),
      h("td", {}, m.readiness === "blocked" ? h("a", { class: "btn mini", href: "#/r/" + m.id + "/edit" }, "Fix") : null,
        m.readiness === "ready" ? h("button", { class: "mini", onclick: () => holdIt(m.id, true) }, "Hold") : null,
        m.readiness === "held" ? h("button", { class: "mini", onclick: () => holdIt(m.id, false) }, "Release") : null));
  });
  return h("section", { class: "card bundle", id: b.key_id },
    h("div", { class: "bh" }, h("h2", {}, "Bundle ", h("code", {}, bundleTitle(b))), h("span", { class: "chip " + (b.due ? "built" : "") }, b.due ? "due " + on : "not due " + on), h("span", { class: "small muted" }, "period " + b.period + " \u00b7 " + b.members.length + " question" + (b.members.length === 1 ? "" : "s"))),
    h("dl", { class: "key" }, Object.keys(KEY_LABEL).map((f) => h("div", { class: "kc" + (b.key[f] ? "" : " unstated"), title: KEY_WHY[f] }, h("dt", {}, KEY_LABEL[f]), h("dd", {}, b.key[f] || "unstated")))),
    h("div", { class: "tw" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "Question"), h("th", {}, "What it says"), h("th", {}, "Can I act?"), h("th", {}, "Status"), h("th", {}, "Schedule"), h("th", {}, ""))), h("tbody", {}, rows))),
    bar, out,
    b.history && b.history.length ? h("details", {}, h("summary", {}, "History (" + b.history.length + ")"), b.history.map((e) => h("div", { class: "small" }, h("span", { class: "muted" }, when(e.at) + " "), h("a", { href: "#/r/" + e.id }, e.id), " " + e.event + (e.detail ? " \u2014 " + e.detail : "")))) : null);
}

// ---------- schema-driven form
async function linkOptions(kind) {
  const out = {};
  for (const f of kind.fields) if (f.type === "link" && f.editable !== false) out[f.name] = (await api("/api/records?per=100&kind=" + f.target)).rows;
  return out;
}

function fieldInput(f, value, opts) {
  let el;
  if (f.type === "link" && opts && opts[f.name]) el = h("select", { name: f.name }, h("option", { value: "" }, "\u2014"), opts[f.name].filter((r) => r.status !== "retired" || r.id === value).map((r) => h("option", { value: r.id, selected: r.id === value }, r.id + " \u2014 " + (r.title || "(untitled)").slice(0, 60))));
  else if (f.type === "enum") el = h("select", { name: f.name }, h("option", { value: "" }, "—"), f.values.map((v) => h("option", { value: v, selected: v === value }, v)));
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

function buildField(f, value, opts) {
  return h("div", {}, h("label", {}, f.name, f.required ? h("span", { class: "req" }, " *") : null, " ", h("span", { class: "hint" }, f.description || "")), fieldInput(f, value, opts));
}

const ROUTING = new Set(["region", "horizon", "raised_by", "origin", "cadence", "due", "lifespan", "expires"]);
function groupedForm(fields, values, opts) {
  const f = (list) => list.map((x) => buildField(x, values && values[x.name], opts));
  const req = fields.filter((x) => x.required), links = fields.filter((x) => !x.required && x.type === "link");
  const routing = fields.filter((x) => !x.required && x.type !== "link" && ROUTING.has(x.name));
  const adv = fields.filter((x) => !x.required && x.type !== "link" && !ROUTING.has(x.name));
  const sect = (title, list, open) => list.length ? h("details", { class: "fg", open }, h("summary", {}, title, h("span", { class: "hint" }, " (" + list.length + ")")), f(list)) : null;
  return h("form", {}, sect("Required", req, true), sect("Routing and schedule", routing, true), sect("Links", links, links.some((x) => values && values[x.name])), sect("Advanced", adv, adv.some((x) => values && values[x.name] != null)));
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
  const bulk = params.get("mode") === "bulk" && kind.fields.some((f) => f.name === "text" || f.name === "name");
  const opts = await linkOptions(kind);
  const prim = kind.fields.some((f) => f.name === "text") ? "text" : "name";
  const editable = kind.fields.filter((f) => f.editable);
  const form = groupedForm(bulk ? editable.filter((f) => f.name !== prim) : editable, null, opts);
  const lines = bulk ? h("textarea", { class: "bulk", placeholder: "One " + prim + " per line (up to 50)" }) : null;
  const out = h("div", {});
  const simBox = (sim) => sim && sim.length ? h("div", { class: "note small" }, "Possible duplicates (you can still save): ", sim.map((x) => h("span", {}, h("a", { href: "#/r/" + x.id }, x.id), " " + x.title.slice(0, 50) + " (" + Math.round(x.score * 100) + "% alike) "))) : null;
  const run = async (apply) => {
    try {
      if (bulk) {
        const r = await api("/api/captures/bulk", { kind: kind.name, common: readForm(form, kind.fields), texts: lines.value.split("\n").map((x) => x.trim()).filter(Boolean), apply });
        if (!apply) {
          out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Preview: " + r.items.length + " drafts"), h("p", { class: "muted small" }, r.note),
            r.items.map((i) => h("div", { class: "row" }, h("div", { class: "t" }, h("span", { class: "muted small" }, "line " + i.line + " "), i.fields[prim], simBox(i.similar)))),
            h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => run(true) }, "Save " + r.items.length + " drafts"))));
        } else { toast("Saved " + r.created.length + " drafts"); location.hash = "#/records?kind=" + kind.name; }
        return;
      }
      const r = await api("/api/captures", { kind: kind.name, fields: readForm(form, kind.fields), apply });
      if (!apply) {
        out.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Preview"), h("p", { class: "muted small" }, r.note), simBox(r.similar),
          h("dl", { class: "kv" }, Object.entries(r.fields).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, Array.isArray(v) ? v.join(", ") : String(v))])),
          h("p", { class: "small" }, "Steps: " + r.steps.map((s) => s.id + " (" + s.do + ")").join(", ")),
          h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => run(true) }, "Save draft"))));
      } else { toast("Saved " + r.record.id); location.hash = "#/r/" + r.record.id; }
    } catch (e) { out.replaceChildren(errBox(e.errors || [e.message])); }
  };
  form.addEventListener("submit", (ev) => { ev.preventDefault(); run(false); });
  const mode = (m) => "#/new?kind=" + kind.name + (m ? "&mode=" + m : "");
  show(h("h1", {}, "Capture"),
    h("p", { class: "muted" }, "Fields and choices come from the Assembly System's schema. Saving creates a draft with a newly minted ID; it is not dispatched."),
    h("div", { class: "tabs" }, ks.map((k) => h("button", { class: k.name === kind.name ? "on" : "", onclick: () => (location.hash = "#/new?kind=" + k.name) }, k.name))),
    h("div", { class: "tabs" }, h("button", { class: bulk ? "" : "on", onclick: () => (location.hash = mode("")) }, "One"),
      ks.length && kind.fields.some((f) => f.name === prim) ? h("button", { class: bulk ? "on" : "", onclick: () => (location.hash = mode("bulk")) }, "Several at once") : null),
    h("p", { class: "small muted" }, kind.description),
    h("div", { class: "card" }, bulk ? [h("label", {}, prim + "s ", h("span", { class: "hint" }, "one per line; the fields below apply to all of them")), lines] : null, form,
      h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => run(false) }, "Preview"))), out);
}

// ---------- records list: search, filter, sort, page, export
async function viewRecords(params) {
  const q = new URLSearchParams();
  for (const k of ["kind", "status", "starred", "q", "sort", "order", "page"]) if (params.get(k)) q.set(k, params.get(k));
  const [d, ks] = await Promise.all([api("/api/records?" + q), kinds()]);
  const go = (patch) => { const p = new URLSearchParams(params); for (const [k, v] of Object.entries(patch)) v ? p.set(k, v) : p.delete(k); if (!("page" in patch)) p.delete("page"); location.hash = "#/records?" + p; };
  const sel = (name, label, opts) => h("select", { "aria-label": label, onchange: (e) => go({ [name]: e.target.value }) },
    h("option", { value: "" }, "all " + label), opts.map((o) => h("option", { value: o, selected: params.get(name) === o }, o)));
  const search = h("input", { type: "search", id: "search", placeholder: "Search id, text or any field (press /)", value: params.get("q") || "" });
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") go({ q: search.value.trim() }); });
  const sort = params.get("sort") || "created", order = params.get("order") || "desc";
  const csvq = new URLSearchParams(q); csvq.delete("page");
  show(h("h1", {}, "Records"),
    h("div", { class: "actions" }, search, h("button", { onclick: () => go({ q: search.value.trim() }) }, "Search")),
    h("div", { class: "actions" }, sel("kind", "kinds", ks.map((k) => k.name)), sel("status", "statuses", Object.keys(LABEL)),
      h("select", { "aria-label": "sort", onchange: (e) => go({ sort: e.target.value }) }, ["created", "id", "status", "kind", "title"].map((o) => h("option", { value: o, selected: sort === o }, "sort: " + o))),
      h("button", { onclick: () => go({ order: order === "asc" ? "desc" : "asc" }) }, order === "asc" ? "\u2191 oldest/A first" : "\u2193 newest/Z first"),
      h("button", { class: params.get("starred") ? "on" : "", onclick: () => go({ starred: params.get("starred") ? "" : "1" }) }, "\u2605 starred only"),
      h("a", { class: "btn", href: "/api/records.csv?" + csvq, download: "assembly-records.csv" }, "Export CSV")),
    h("p", { class: "small muted" }, d.total + " record" + (d.total === 1 ? "" : "s") + (params.get("q") ? " matching \u201c" + params.get("q") + "\u201d" : "")),
    h("div", { class: "card" }, d.rows.length ? d.rows.map((r) => h("div", { class: "row" },
      h("div", { class: "t" }, h("a", { href: "#/r/" + r.id }, r.id), " ", pill(r.status), r.creation === "draft" ? h("span", { class: "pill" }, "draft") : null, " ", marks(r),
        h("div", { class: "small muted" }, r.title || "(untitled)")),
      h("span", { class: "small muted" }, when(r.created)))) : h("p", { class: "muted" }, "No records.")),
    d.pages > 1 ? h("div", { class: "actions" }, h("button", { disabled: d.page <= 1, onclick: () => go({ page: String(d.page - 1) }) }, "\u2190 Previous"),
      h("span", { class: "small" }, "Page " + d.page + " of " + d.pages), h("button", { disabled: d.page >= d.pages, onclick: () => go({ page: String(d.page + 1) }) }, "Next \u2192")) : null);
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
        p.tasks.map((t) => h("div", {}, h("p", { class: "small" }, "File: ", h("code", {}, t.file), t.written ? " (already in outbox; identical rewrite is a no-op)" : ""), diffView(t.diff), h("details", {}, h("summary", {}, "Full task document"), h("pre", {}, t.markdown)))),
        p.errors.length ? errBox(p.errors) : h("div", { class: "actions" }, h("label", { class: "inline" }, ok, " I have read the task and its approval/permission tags"), go)));
    } catch (e) { panel.replaceChildren(errBox(e.errors)); }
  };

  const editPanel = async () => {
    const fields = kind.fields.filter((f) => f.editable);
    const form = groupedForm(fields, rec.fields, await linkOptions(kind));
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

  const resultPanel = h("div", { class: "res" });
  const showResult = async () => {
    try {
      const r = await api("/api/records/" + id + "/result");
      if (!r.result) return resultPanel.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Run result"), h("p", { class: "note small" }, r.runs_present ? "No machine-flows run carries " + id + " yet." : "No runs folder at " + r.runs + ". There is no result to read.")));
      const x = r.result;
      resultPanel.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Run result"),
        h("p", { class: "small muted" }, "Run " + x.run_id + " \u00b7 " + x.status + " \u00b7 " + (x.machine || "?") + " via " + (x.tool || "?") + (x.older_runs ? " \u00b7 " + x.older_runs + " earlier run(s)" : "")),
        Object.entries(x.files).map(([n, t]) => h("div", {}, h("h3", {}, n, x.truncated.includes(n) ? " (cut)" : ""), h("pre", {}, t))),
        x.skipped.length ? h("p", { class: "small muted" }, "Not shown (binary or unreadable): " + x.skipped.join(", ")) : null));
    } catch (e) { resultPanel.replaceChildren(errBox(e.errors || [e.message])); }
  };
  const supersedePanel = () => {
    const by = h("input", { type: "text", placeholder: "replacement ID, e.g. " + id.split("-")[0] + "-0002" });
    const out = h("div");
    const go = async (apply) => {
      try {
        const r = await api("/api/records/" + id + "/supersede", { by: by.value.trim(), apply });
        if (!apply) out.replaceChildren(h("p", { class: "note small" }, "This retires " + id + " and links " + r.by + " to it. " + id + " becomes read-only."), h("div", { class: "actions" }, h("button", { class: "danger", onclick: () => go(true) }, "Retire " + id + " and link " + r.by)));
        else { toast("Superseded"); viewRecord(id); }
      } catch (e) { out.replaceChildren(errBox(e.errors)); }
    };
    panel.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Replace " + id), h("p", { class: "muted small" }, "Use when a newer record takes over. Nothing is deleted."), by, h("div", { class: "actions" }, h("button", { onclick: () => go(false) }, "Preview"))), out);
  };
  const dispatchable = kind.dispatchable && d.tasks.length > 0 && !retired;
  const actions = h("div", { class: "actions" },
    dispatchable ? h("button", { class: "primary", onclick: dispatchPanel }, rec.status === "new" ? "Review & dispatch" : "Dispatch again") : null,
    rec.status === "awaiting-confirmation" ? h("button", { class: "primary", onclick: async () => { try { await api("/api/records/" + id + "/confirm", {}); toast("Marked answered"); viewRecord(id); } catch (e) { panel.prepend(errBox(e.errors)); } } }, "Confirm answered") : null,
    d.creation && d.creation.state === "partial" ? h("button", { class: "primary", onclick: async () => { try { await api("/api/records/" + id + "/resume", {}); toast("Creation resumed"); viewRecord(id); } catch (e) { panel.prepend(errBox(e.errors)); } } }, "Resume creation") : null,
    d.record.status !== "new" || kind.dispatchable ? h("button", { onclick: showResult }, "Show run result") : null,
    !retired ? h("button", { onclick: editPanel }, "Edit metadata") : null,
    !retired ? h("button", { onclick: supersedePanel }, "Replace with…") : null,
    !retired ? h("button", { class: "danger", onclick: retirePanel }, "Retire") : null);

  show(
    h("p", { class: "small" }, h("a", { href: "#/records" }, "← Records")),
    h("h1", {}, id, " ", pill(rec.status), d.creation && d.creation.state === "draft" ? h("span", { class: "pill" }, "draft") : null),
    h("p", { class: "muted small" }, rec.kind + " · rev " + (rec.rev || 0) + " · created " + when(rec.created)),
    rec.status === "awaiting-confirmation" ? h("p", { class: "note" }, "machine-flows reports this run as done. Read the result, then confirm; only you mark a question answered.") : null,
    rec.status === "dispatched" ? h("p", { class: "note small" }, "A task document was written. It stays dispatched until a machine-flows run record says otherwise (use Check runs on the Dispatch page).") : null,
    actions, panel, resultPanel,
    h("div", { class: "grid" },
      h("section", { class: "card" }, h("h2", {}, "Fields"), h("dl", { class: "kv" },
        Object.entries(rec.fields).sort().flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, Array.isArray(v) ? v.join(", ") : String(v))]))),
      h("section", { class: "card" }, h("h2", {}, "History"), h("ul", { class: "tl" },
        [...rec.history].reverse().map((e) => h("li", {}, h("b", {}, e.event), " ", h("span", { class: "muted small" }, when(e.at)), e.detail ? h("div", { class: "small" }, e.detail) : null)))),
      h("section", { class: "card" }, h("h2", {}, "Notes"), notesPanel(id)),
      d.creation ? h("section", { class: "card" }, h("h2", {}, "Creation steps"), d.creation.steps.map((s) => h("div", { class: "small" }, h("b", {}, s.id), " — ", s.status, s.detail ? h("div", { class: "muted" }, s.detail) : null))) : null));
  if (mode === "dispatch" && dispatchable) dispatchPanel();
  if (mode === "edit" && !retired) editPanel();
  if (rec.status === "awaiting-confirmation") showResult();      // read the result before confirming
}

// ---------- inbox and health
const KIND_LABEL = { mention: "Mentioned you", review: "Review", failed: "Failed", partial: "Resume", aging: "Aging", flagged: "Flagged" };
async function viewInbox() {
  const d = await api("/api/inbox?actor=" + encodeURIComponent(actorName()));
  show(h("h1", {}, "Inbox"), h("p", { class: "muted" }, "Everything that wants you, most pressing first: finished runs to confirm, failures, partial creations, dispatches with no change for days, and flagged items."),
    d.items.some((i) => i.kind === "mention") ? h("div", { class: "actions" }, h("button", { onclick: async () => { await api("/api/inbox/seen", { actor: actorName() }); viewInbox(); refreshBadge(); } }, "Mark mentions of @" + actorName() + " as read")) : h("p", { class: "small muted" }, "Mention someone in a comment with @name (no spaces). Mentions of you show here."),
    h("section", { class: "card" }, d.items.length ? d.items.map((i) => h("div", { class: "row" },
      h("div", { class: "t" }, h("span", { class: "sev " + i.kind }), h("b", {}, KIND_LABEL[i.kind]), " ", h("a", { href: i.route }, i.id), h("div", { class: "small" }, i.title), h("div", { class: "small muted" }, i.detail)),
      h("a", { class: "btn" + (i.kind === "review" ? " primary" : ""), href: i.route }, "Open"))) : h("p", { class: "muted" }, "Inbox is clear.")));
}

async function viewHealth() {
  const d = await api("/api/health");
  const out = h("div");
  const verify = async (name) => { try { const r = await api("/api/backups/" + name + "/verify", {}); toast(r.ok ? "Backup verified (" + r.checked + " files)" : "CHECKSUM MISMATCH: " + r.bad.join(", ")); } catch (e) { toast(e.message); } };
  show(h("h1", {}, "Health"),
    h("section", { class: "card" }, h("h2", {}, "Record checks"), d.errors.length || d.warnings.length ? [d.errors.map((e) => h("p", { class: "err" }, e)), d.warnings.map((w) => h("p", { class: "note small" }, w))] : h("p", { class: "muted" }, "All records pass the core's lint.")),
    h("section", { class: "card" }, h("h2", {}, "Backups"), h("p", { class: "small muted" }, "Copies records, creations, ID counters and notes into " + d.data + "/backups with a checksum manifest, then verifies the copy. Take one before moving the data root."),
      h("div", { class: "actions" }, h("button", { class: "primary", onclick: async () => { try { const r = await api("/api/backups", {}); toast("Backed up " + r.files + " files" + (r.verified ? " (verified)" : " (VERIFY FAILED)")); viewHealth(); } catch (e) { out.replaceChildren(errBox(e.errors)); } } }, "Back up now")), out,
      d.backups.length ? d.backups.map((b) => h("div", { class: "row" }, h("div", { class: "t" }, h("b", {}, b.name), h("div", { class: "small muted" }, b.files + " files")), h("button", { onclick: () => verify(b.name) }, "Verify"))) : h("p", { class: "muted small" }, "No backups yet.")),
    h("section", { class: "card" }, h("h2", {}, "Locations"), h("dl", { class: "kv" }, h("dt", {}, "Records"), h("dd", {}, d.root), h("dt", {}, "Site data"), h("dd", {}, d.data))));
}

async function refreshBadge() {
  try { const d = await api("/api/inbox?actor=" + encodeURIComponent(actorName())); const b = $("#badge"); b.textContent = d.count; b.hidden = !d.count; } catch (e) { /* offline */ }
}

// ---------- router
async function route() {
  const hash = location.hash.slice(1) || "/";
  const [path, qs] = hash.split("?");
  const params = new URLSearchParams(qs || "");
  const cur = path === "/" || path.startsWith("/stage") ? "map" : path.startsWith("/r/") ? "records" : path.slice(1);
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === cur));
  while (cleanups.length) cleanups.pop()();
  refreshBadge();
  try {
    let m;
    if (path === "/") await viewMap();
    else if (path === "/dispatch") await viewDispatch();
    else if (path === "/bundles") await viewBundles(params);
    else if (path === "/activity") await viewActivity(params);
    else if (path === "/inbox") await viewInbox();
    else if (path === "/health") await viewHealth();
    else if ((m = path.match(/^\/stage\/([a-z0-9]+)$/))) await viewStage(m[1]);
    else if (path === "/new") await viewNew(params);
    else if (path === "/records") await viewRecords(params);
    else if ((m = path.match(/^\/r\/([A-Z]+-\d{4,})(?:\/(dispatch|edit))?$/))) await viewRecord(m[1], m[2]);
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
      const body = [
        h("div", { class: "meta" }, h("b", {}, c.actor), " ", when(c.at)),
        h("div", { class: "txt" }, c.retracted ? "(retracted by author)" : c.text),
        h("div", { class: "actions" }, c.retracted ? null : replyBtn, !c.retracted && c.actor === me ? h("button", { class: "mini", onclick: () => act({ op: "retract", id: c.id }) }, "Retract") : null,
          !c.parent ? h("button", { class: "mini", onclick: () => act({ op: "resolve", id: c.id, on: !c.resolved }) }, c.resolved ? "Reopen thread" : "Resolve thread") : null),
        reply, (byParent[c.id] || []).map(node)];
      return c.resolved && !c.parent
        ? h("details", { class: "cm resolved" }, h("summary", {}, "Resolved by " + c.resolved_by + " \u00b7 " + (c.retracted ? "(retracted)" : c.text.slice(0, 60))), body)
        : h("div", { class: "cm" + (c.retracted ? " gone" : "") }, body);
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

async function viewTimeline(params) {
  const off = parseInt(params.get("offset") || "0", 10);
  const d = await api("/api/timeline?limit=50&offset=" + off);
  const to = (o) => { const p = new URLSearchParams(params); p.set("offset", String(Math.max(0, o))); location.hash = "#/activity?" + p; };
  show(h("h1", {}, "Activity"), activityTabs("timeline"),
    h("p", { class: "muted" }, "Every change to every record, newest first: created, dispatched, handed back, confirmed, edited."),
    h("section", { class: "card feed" }, d.events.map((e) => h("div", { class: "row" },
      h("div", { class: "t" }, h("a", { href: "#/r/" + e.id }, e.id), " ", h("b", {}, e.event), h("div", { class: "small muted" }, e.title.slice(0, 80) + (e.detail ? " \u2014 " + e.detail : ""))),
      h("span", { class: "small muted" }, when(e.at))))),
    h("div", { class: "actions" }, h("button", { disabled: off <= 0, onclick: () => to(off - d.limit) }, "\u2190 Newer"), h("span", { class: "small" }, (off + 1) + "\u2013" + Math.min(off + d.limit, d.total) + " of " + d.total),
      h("button", { disabled: off + d.limit >= d.total, onclick: () => to(off + d.limit) }, "Older \u2192")));
}

const activityTabs = (cur) => h("div", { class: "tabs" }, h("button", { class: cur === "notes" ? "on" : "", onclick: () => (location.hash = "#/activity") }, "Comments, stars and flags"),
  h("button", { class: cur === "timeline" ? "on" : "", onclick: () => (location.hash = "#/activity?view=timeline") }, "Record timeline"));

async function viewActivity(params) {
  if (params && params.get("view") === "timeline") return viewTimeline(params);
  const d = await api("/api/activity?limit=100");
  const verb = (e) => ({ comment: "commented", star: e.on ? "starred" : "unstarred", flag: e.on ? "flagged" : "cleared flag on" })[e.op] || e.op;
  show(h("h1", {}, "Activity"), activityTabs("notes"), h("p", { class: "muted" }, "Comments, stars and flags across records and stages. They are notes about the work and do not change any record."),
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
