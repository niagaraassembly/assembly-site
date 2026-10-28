"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const captureDialog = $("capture-dialog");
  const readerDialog = $("reader-dialog");
  const form = $("question-form");
  const titleInput = $("question-title");
  const textInput = $("question-text");
  const state = { questions: [], schema: null, schemaError: false, source: "", saving: false, readerId: null, readerReturnId: "", captureReturnId: "", expanded: new Set(), drafts: new Map() };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function errorMessage(error, fallback) { return error instanceof Error && error.message ? error.message : fallback; }

  async function request(path, options = {}) {
    const headers = { Accept: "application/json", ...options.headers };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      headers["X-Assembly-CSRF"] = document.querySelector('meta[name="csrf-token"]').content;
    }
    let response;
    try { response = await fetch(path, { credentials: "same-origin", ...options, headers }); }
    catch (_) { throw new Error("Could not reach this workspace. Your changes are still here. Try again."); }
    let payload;
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) {
      const message = response.status === 413 ? "This question is larger than the workspace can accept (8 MiB). Your text is still here; shorten it before trying again." : (payload.error || "The change could not be saved. Your changes are still here. Try again.");
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function currentQuestion(id) { return state.questions.find((question) => question.id === id); }
  function questionFields(question) { return question.fields || {}; }
  function questionTitle(question) { return questionFields(question).title || "Untitled question"; }
  function canEditMetadata(question) { return question.draft === true && question.status !== "retired"; }
  function metadataText(value, field) {
    if (value === undefined || value === null) return "";
    return field.type === "list" && Array.isArray(value) ? value.join("\n") : String(value);
  }
  function metadataValue(value, field) {
    if (value === "") return "";
    if (field.type === "bool") return value === "true";
    if (field.type === "int") return Number(value);
    if (field.type === "list") return value.split("\n").filter((item) => item.trim());
    return value;
  }
  function humanize(value) { return String(value || "Not yet set").replace(/[_-]/g, " "); }
  function dateLabel(value, full = false) {
    if (!value) return "Date unavailable";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(undefined, full ? { year: "numeric", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" } : { month: "short", day: "numeric", year: "numeric" }).format(date);
  }

  function hasCaptureDraft() { return Boolean(titleInput.value || textInput.value || state.source); }
  function dirtyFields(draft) { return Object.keys(draft.values).filter((name) => draft.values[name] !== draft.base[name]); }
  function hasUnsavedChanges() { return hasCaptureDraft() || [...state.drafts.values()].some((draft) => dirtyFields(draft).length || draft.saving); }
  function updateCaptureState() {
    const plus = element("span", "", "+");
    plus.setAttribute("aria-hidden", "true");
    $("new-question").replaceChildren(plus, document.createTextNode(hasCaptureDraft() ? " Continue draft" : " Add a question"));
    $("capture-save-note").textContent = hasCaptureDraft() ? "Unsaved question" : "Ready when you are.";
    $("capture-source").hidden = !state.source;
    $("capture-source-text").textContent = state.source ? `Linked to original question ${state.source}` : "";
  }

  function showCapture() {
    if (!captureDialog.open) {
      state.captureReturnId = document.activeElement?.id || "new-question";
      captureDialog.showModal();
    }
    textInput.focus();
  }
  function closeCapture() { if (!state.saving) captureDialog.close(); }
  function openLinkedQuestion(id) {
    if (hasCaptureDraft() && state.source !== id) {
      if (!window.confirm("You have an unsaved question. Discard it and start a new question linked to this one?")) return;
      form.reset();
      $("capture-error").hidden = true;
    }
    state.source = id;
    updateCaptureState();
    readerDialog.close();
    showCapture();
  }

  function lineageLinks(question) {
    const fields = questionFields(question);
    const groups = [];
    const normalize = (value) => Array.isArray(value) ? value : value ? [value] : [];
    if (fields.source_question) groups.push(["Source submission", normalize(fields.source_question)]);
    if (fields.supersedes) groups.push(["Replaces", normalize(fields.supersedes)]);
    if (question.derived_questions?.length) groups.push(["Linked questions", normalize(question.derived_questions)]);
    if (question.superseded_by?.length) groups.push(["Replaced by", normalize(question.superseded_by)]);
    if (!groups.length) return null;
    const container = element("div", "lineage");
    for (const [label, ids] of groups) {
      const group = element("div", "lineage-group");
      group.append(element("span", "lineage-label", `${label}:`));
      for (const id of ids) {
        const button = element("button", "text-button", String(id));
        button.type = "button";
        button.addEventListener("click", () => openQuestion(String(id)));
        group.append(button);
      }
      container.append(group);
    }
    return container;
  }

  async function openQuestion(id) {
    let question = currentQuestion(id);
    if (!question) {
      try {
        const result = await request(`/api/questions/${encodeURIComponent(id)}`);
        question = result.question;
        if (!question) throw new Error("This linked question could not be found.");
      } catch (error) {
        const message = errorMessage(error, "This question could not be opened.");
        if (readerDialog.open) { $("reader-error").textContent = message; $("reader-error").hidden = false; }
        else $("workspace-status").textContent = message;
        return;
      }
    }
    state.readerId = question.id;
    $("reader-error").hidden = true;
    const fields = questionFields(question);
    $("reader-id").textContent = question.id;
    $("reader-heading").textContent = questionTitle(question);
    $("reader-text").textContent = fields.text || "";
    const meta = $("reader-meta");
    meta.replaceChildren(element("span", "status-badge", humanize(question.status)), element("span", "", dateLabel(question.created, true)));
    if (fields.lens) meta.append(element("span", "scope-lens", humanize(fields.lens)));
    if (fields.region) meta.append(element("span", "", fields.region));
    const lineage = lineageLinks(question);
    $("reader-lineage").replaceChildren();
    $("reader-lineage").hidden = !lineage;
    if (lineage) $("reader-lineage").append(lineage);
    if (!readerDialog.open) {
      state.readerReturnId = document.activeElement?.id || "new-question";
      readerDialog.showModal();
    }
    $("reader-heading").focus();
  }

  function metadataDraft(question) {
    if (state.drafts.has(question.id)) return state.drafts.get(question.id);
    const base = {};
    for (const field of state.schema?.question_fields || []) {
      base[field.name] = metadataText(questionFields(question)[field.name], field);
    }
    const draft = { base, values: { ...base }, rev: question.rev || 0, saving: false, error: "", conflict: false, message: "" };
    state.drafts.set(question.id, draft);
    return draft;
  }

  async function reloadMetadata(questionId) {
    const draft = state.drafts.get(questionId);
    if (!draft || draft.saving) return;
    const changes = Object.fromEntries(dirtyFields(draft).map((name) => [name, draft.values[name]]));
    draft.saving = true;
    renderQuestions();
    try {
      const { question } = await request(`/api/questions/${encodeURIComponent(questionId)}`);
      if (!question) throw new Error("Could not load the latest question. Your edits are still here.");
      const index = state.questions.findIndex((item) => item.id === questionId);
      if (index >= 0) state.questions[index] = question;
      state.drafts.delete(questionId);
      const nextDraft = metadataDraft(question);
      Object.assign(nextDraft.values, changes);
      nextDraft.message = "Latest metadata loaded. Your edits are kept; review them and save again.";
    } catch (error) { draft.error = errorMessage(error, "Could not load the latest metadata."); }
    finally { draft.saving = false; renderQuestions(); }
  }

  async function saveMetadata(event, questionId) {
    event.preventDefault();
    const draft = state.drafts.get(questionId);
    const question = currentQuestion(questionId);
    if (!draft || draft.saving || !question || !canEditMetadata(question)) return;
    const definitions = new Map(state.schema.question_fields.map((field) => [field.name, field]));
    const changes = Object.fromEntries(dirtyFields(draft).map((name) => [name, metadataValue(draft.values[name], definitions.get(name))]));
    if (!Object.keys(changes).length) return;
    draft.saving = true;
    draft.error = "";
    draft.message = "";
    renderQuestions();
    try {
      const { question } = await request(`/api/questions/${encodeURIComponent(questionId)}`, { method: "PATCH", body: JSON.stringify({ fields: changes, rev: draft.rev }) });
      if (!question) throw new Error("The workspace returned an incomplete response. Your edits are still here.");
      const index = state.questions.findIndex((item) => item.id === questionId);
      if (index >= 0) state.questions[index] = question;
      state.drafts.delete(questionId);
      $("workspace-status").textContent = `Metadata saved for ${questionId}.`;
      if (state.readerId === questionId && readerDialog.open) openQuestion(questionId);
    } catch (error) {
      draft.error = error.status === 409 ? "This question changed elsewhere. Your edits are still here. Load the latest metadata, review your changes, and save again." : errorMessage(error, "Metadata could not be saved. Your edits are still here.");
      draft.conflict = error.status === 409;
    } finally { draft.saving = false; renderQuestions(); }
  }

  function metadataPanel(question) {
    const panel = element("section", "metadata-panel");
    panel.setAttribute("aria-label", `Metadata for ${question.id}`);
    const heading = element("div", "metadata-heading");
    const headingText = element("div");
    const metadataTitle = element("h3", "", "Question metadata");
    metadataTitle.id = `${question.id}-metadata-heading`;
    metadataTitle.tabIndex = -1;
    headingText.append(metadataTitle, element("p", "", "Add context as it becomes clear. The original question stays unchanged."));
    heading.append(headingText);
    panel.append(heading);
    if (!state.schema) {
      panel.append(element("p", "metadata-message", state.schemaError ? "Metadata options could not be loaded." : "Loading metadata options…"));
      if (state.schemaError) {
        const retry = element("button", "button button-small button-secondary", "Try again");
        retry.type = "button";
        retry.addEventListener("click", loadSchema);
        panel.append(retry);
      }
    } else {
      const draft = metadataDraft(question);
      const editable = canEditMetadata(question);
      const metadataForm = element("form", "metadata-form");
      metadataForm.addEventListener("submit", (event) => saveMetadata(event, question.id));
      const grid = element("div", "metadata-grid");
      let save;
      for (const field of state.schema.question_fields || []) {
        const wrapper = element("div", "form-field");
        const inputId = `${question.id}-${field.name}`;
        const label = element("label", "metadata-label", humanize(field.name));
        label.htmlFor = inputId;
        const options = field.type === "bool" ? ["true", "false"] : field.values;
        const input = element(options?.length ? "select" : field.type === "list" ? "textarea" : "input");
        input.id = inputId;
        input.name = field.name;
        input.disabled = !editable || draft.saving;
        if (field.description) input.title = field.description;
        if (options?.length) {
          const blank = element("option", "", "Not yet set");
          blank.value = "";
          input.append(blank);
          for (const value of options) {
            const option = element("option", "", humanize(value));
            option.value = value;
            input.append(option);
          }
          if (draft.values[field.name] && !options.includes(draft.values[field.name])) {
            const current = element("option", "", humanize(draft.values[field.name]));
            current.value = draft.values[field.name];
            input.append(current);
          }
        } else if (field.type === "list") {
          input.rows = 3;
          input.placeholder = "One value per line";
        } else {
          input.type = field.type === "int" ? "number" : field.type === "date" ? "date" : "text";
          if (field.type === "int") input.step = "1";
          input.placeholder = "Not yet set";
        }
        input.value = draft.values[field.name];
        input.addEventListener("input", () => { draft.values[field.name] = input.value; draft.message = ""; if (save) save.disabled = !dirtyFields(draft).length || draft.saving; });
        wrapper.append(label, input);
        grid.append(wrapper);
      }
      metadataForm.append(grid);
      const actions = element("div", "metadata-actions");
      actions.append(element("span", "metadata-hint", editable ? "Blank fields stay unset. Choose Save metadata to keep changes." : "Metadata is read-only for this question."));
      if (editable) {
        save = element("button", "button button-small button-secondary", draft.saving ? "Saving…" : "Save metadata");
        save.id = `${question.id}-metadata-save`;
        save.type = "submit";
        save.disabled = !dirtyFields(draft).length || draft.saving;
        actions.append(save);
      }
      metadataForm.append(actions);
      if (draft.error || draft.message) {
        const message = element("p", `metadata-message${draft.error ? " metadata-error" : ""}`, draft.error || draft.message);
        message.setAttribute("role", draft.error ? "alert" : "status");
        metadataForm.append(message);
      }
      if (draft.conflict) {
        const reload = element("button", "button button-small button-secondary", "Load latest");
        reload.id = `${question.id}-metadata-reload`;
        reload.type = "button";
        reload.disabled = draft.saving;
        reload.addEventListener("click", () => reloadMetadata(question.id));
        metadataForm.append(reload);
      }
      panel.append(metadataForm);
    }
    const lineage = lineageLinks(question);
    if (lineage) panel.append(lineage);
    return panel;
  }

  function updatePreviewFades() {
    for (const preview of document.querySelectorAll(".question-preview")) preview.classList.toggle("is-overflowing", preview.scrollHeight > preview.clientHeight + 1);
  }

  function renderQuestions() {
    const activeId = document.activeElement?.id;
    const selection = document.activeElement?.selectionStart;
    const fallbackId = document.activeElement?.closest(".metadata-panel")?.querySelector("h3")?.id;
    const rows = $("question-rows");
    rows.replaceChildren();
    for (const question of state.questions) {
      const fields = questionFields(question);
      const row = element("tr", "question-row");
      const questionCell = element("td");
      const open = element("button", "question-open");
      open.type = "button";
      open.id = `open-${question.id}`;
      open.setAttribute("aria-label", `Read ${question.id}: ${questionTitle(question)}`);
      open.append(element("span", "question-title", questionTitle(question)), element("span", "question-preview", (fields.text || "").trim()));
      open.addEventListener("click", () => openQuestion(question.id));
      questionCell.append(open);
      const scope = element("td");
      scope.append(element("span", fields.lens ? "scope-lens" : "scope-value unset", fields.lens ? humanize(fields.lens) : "—"));
      scope.append(element("span", `scope-value${fields.region ? "" : " unset"}`, fields.region || "—"));
      const status = element("td");
      status.append(element("span", "status-badge", humanize(question.status)));
      const added = element("td");
      const date = element("time", "added-date", dateLabel(question.created));
      if (question.created) date.dateTime = question.created;
      date.title = dateLabel(question.created, true);
      added.append(date, element("span", "question-id", question.id));
      const expandCell = element("td", "expand-cell");
      const expanded = state.expanded.has(question.id);
      const expand = element("button", "expand-button", expanded ? "−" : "+");
      expand.type = "button";
      expand.id = `expand-${question.id}`;
      expand.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} metadata for ${question.id}`);
      expand.setAttribute("aria-expanded", String(expanded));
      expand.setAttribute("aria-controls", `details-${question.id}`);
      expand.addEventListener("click", () => { expanded ? state.expanded.delete(question.id) : state.expanded.add(question.id); renderQuestions(); });
      expandCell.append(expand);
      row.append(questionCell, scope, status, added, expandCell);
      rows.append(row);
      const detailRow = element("tr", "details-row");
      detailRow.id = `details-${question.id}`;
      detailRow.hidden = !expanded;
      const detailCell = element("td");
      detailCell.colSpan = 5;
      if (expanded) detailCell.append(metadataPanel(question));
      detailRow.append(detailCell);
      rows.append(detailRow);
    }
    const count = state.questions.length;
    $("question-count").textContent = String(count);
    $("table-wrapper").hidden = !count;
    $("empty-state").hidden = Boolean(count);
    $("table-summary").textContent = count ? `${count} saved ${count === 1 ? "question" : "questions"} · Open any question to read the original.` : "Questions are saved when you choose Save question.";
    if (activeId) {
      const control = $(activeId);
      const active = control && !control.disabled ? control : fallbackId ? $(fallbackId) : null;
      if (active) {
        active.focus({ preventScroll: true });
        if (typeof selection === "number" && active.type === "text") active.setSelectionRange(selection, selection);
      }
    }
    window.requestAnimationFrame(updatePreviewFades);
  }

  async function loadSchema() {
    state.schemaError = false;
    try {
      const schema = await request("/api/schema");
      if (!Array.isArray(schema.question_fields)) throw new Error("Metadata options are unavailable.");
      state.schema = schema;
    } catch (_) { state.schemaError = true; }
    if (state.questions.length) renderQuestions();
  }

  async function loadQuestions() {
    $("loading-state").hidden = false;
    $("load-error").hidden = true;
    $("empty-state").hidden = true;
    $("retry-load").disabled = true;
    try {
      const result = await request("/api/questions");
      if (!Array.isArray(result.questions)) throw new Error("The workspace returned an incomplete question list. Try again.");
      // A question saved during a slow initial load must remain visible.
      const loadedIds = new Set(result.questions.map((question) => question.id));
      state.questions = [...state.questions.filter((question) => !loadedIds.has(question.id)), ...result.questions];
      renderQuestions();
    } catch (error) {
      $("load-error-text").textContent = errorMessage(error, "Questions could not be loaded.");
      $("load-error").hidden = false;
    } finally { $("loading-state").hidden = true; $("retry-load").disabled = false; }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.saving) return;
    const error = $("capture-error");
    error.hidden = true;
    if (!textInput.value.trim()) {
      error.textContent = "Add a question or paste some text before saving.";
      error.hidden = false;
      textInput.setAttribute("aria-invalid", "true");
      textInput.focus();
      return;
    }
    const payload = { text: textInput.value };
    if (titleInput.value.trim()) payload.title = titleInput.value;
    if (state.source) payload.source_question = state.source;
    state.saving = true;
    for (const input of form.querySelectorAll("input, textarea, button")) input.disabled = true;
    $("capture-close").disabled = true;
    $("save-question").textContent = "Saving…";
    $("capture-save-note").textContent = "Saving your question…";
    try {
      const { question } = await request("/api/questions", { method: "POST", body: JSON.stringify(payload) });
      if (!question) throw new Error("The workspace returned an incomplete response. Your question is still here.");
      state.questions.unshift(question);
      if (state.source) {
        const source = currentQuestion(state.source);
        if (source) source.derived_questions = [...new Set([...(source.derived_questions || []), question.id])];
      }
      form.reset();
      state.source = "";
      renderQuestions();
      captureDialog.close();
      $("workspace-status").textContent = `Saved ${question.id}. Your original question is kept.`;
    } catch (saveError) {
      error.textContent = errorMessage(saveError, "Your question could not be saved. Your text is still here. Try again.");
      error.hidden = false;
    } finally {
      state.saving = false;
      for (const input of form.querySelectorAll("input, textarea, button")) input.disabled = false;
      $("capture-close").disabled = false;
      $("save-question").textContent = "Save question";
      updateCaptureState();
    }
  });

  for (const id of ["new-question", "empty-add"]) $(id).addEventListener("click", showCapture);
  for (const id of ["capture-close", "capture-cancel"]) $(id).addEventListener("click", closeCapture);
  $("reader-close").addEventListener("click", () => readerDialog.close());
  $("add-linked").addEventListener("click", () => openLinkedQuestion(state.readerId));
  $("remove-source").addEventListener("click", () => { state.source = ""; updateCaptureState(); });
  $("retry-load").addEventListener("click", loadQuestions);
  for (const input of [titleInput, textInput]) input.addEventListener("input", () => { textInput.removeAttribute("aria-invalid"); updateCaptureState(); });
  captureDialog.addEventListener("cancel", (event) => { if (state.saving) event.preventDefault(); });
  captureDialog.addEventListener("close", () => {
    updateCaptureState();
    if (!readerDialog.open && !captureDialog.open) {
      const target = $(state.captureReturnId);
      (target && target.getClientRects().length ? target : $("new-question")).focus({ preventScroll: true });
    }
  });
  readerDialog.addEventListener("close", () => {
    if (!captureDialog.open && !readerDialog.open) {
      const target = $(state.readerReturnId);
      (target && target.getClientRects().length ? target : $("new-question")).focus({ preventScroll: true });
    }
  });
  window.addEventListener("resize", updatePreviewFades);
  window.addEventListener("beforeunload", (event) => { if (hasUnsavedChanges()) { event.preventDefault(); event.returnValue = ""; } });
  updateCaptureState();
  loadQuestions();
  loadSchema();
})();
