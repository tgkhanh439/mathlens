/* MathLens frontend.
   The frontend never reasons about maths. Every verdict comes from /api.
   The API returns each text field in both languages, so switching language
   re-renders from the payload already in memory. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  lang: "vi",
  problems: [],
  taxonomy: [],
  result: null,      // last /api/analyze payload
  attemptId: null,
  diagnosticStatus: null,
};

const MARK = { ok: "✓", error: "✗", parse_error: "?", after_error: "·" };

/* Plot colours assigned per error group and kept identical on every screen,
   so a student learns a group by its colour the way they learn a graph by its. */
const PALETTE = [
  "var(--c-blue)", "var(--c-green)", "var(--c-amber)",
  "var(--c-violet)", "var(--c-teal)", "var(--c-red)",
];

/* --------------------------------------------------------------- language */

function t(key) {
  const table = STRINGS[state.lang] || STRINGS.vi;
  return table[key] !== undefined ? table[key] : key;
}

/* Fields from the API arrive as {vi, en}; plain strings pass straight through. */
function pick(field) {
  if (field === null || field === undefined) return "";
  if (typeof field === "string") return field;
  return field[state.lang] || field.vi || "";
}

function applyStaticStrings() {
  document.documentElement.lang = state.lang;
  $$("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  $$("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  $$("[data-i18n-attr]").forEach((el) => {
    const [attr, key] = el.dataset.i18nAttr.split(":");
    el.setAttribute(attr, t(key));
  });
}

function setLanguage(lang) {
  state.lang = lang;
  try {
    localStorage.setItem("mathlens_lang", lang);
  } catch (err) {
    /* private browsing: fall back to session-only language */
  }
  $$(".lang-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.lang === lang));

  applyStaticStrings();
  renderProblemOptions();
  renderTaxonomy($("#taxonomy-filter").value || "");
  if (state.result) renderResult(state.result);
  else renderEmptySheet();
  if ($("#view-profile").classList.contains("is-active")) loadProfile();
}

/* ------------------------------------------------------------------ utils */

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function renderMath(el, latex, fallback) {
  if (latex && window.katex) {
    try {
      window.katex.render(latex, el, { throwOnError: false, displayMode: false });
      return;
    } catch (err) {
      /* fall through to plain text */
    }
  }
  el.classList.add("step-raw");
  el.textContent = fallback;
}

function groupColor(group) {
  const name = typeof group === "string" ? group : (group && group.vi) || "";
  if (!name) return PALETTE[0];
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.codePointAt(0)) % 100000;
  return PALETTE[hash % PALETTE.length];
}

function setView(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.view === name));
  $$(".view").forEach((view) => view.classList.toggle("is-active", view.id === `view-${name}`));
  if (name === "profile") loadProfile();
}

/* --------------------------------------------------------------- problems */

async function loadProblems() {
  state.problems = await api("/api/problems");
  renderProblemOptions();
  $("#problem").addEventListener("change", showQuestion);
}

function renderProblemOptions() {
  const select = $("#problem");
  if (!select) return;
  const current = select.value;
  select.innerHTML =
    `<option value="">${t("problem.custom")}</option>` +
    state.problems
      .map((p) => `<option value="${p.problem_id}">${p.problem_id} · ${p.question}</option>`)
      .join("");
  select.value = current;
}

function showQuestion() {
  const problem = state.problems.find((p) => p.problem_id === $("#problem").value);
  const box = $("#question-text");
  if (!problem) {
    box.hidden = true;
    return;
  }
  box.textContent = problem.question;
  box.hidden = false;
}

/* ---------------------------------------------------------------- grading */

function renderEmptySheet() {
  $("#marking-sheet").innerHTML = `<p class="empty">${t("sheet.empty")}</p>`;
}

async function grade() {
  const solution = $("#solution").value.trim();
  if (!solution) {
    $("#solution").focus();
    return;
  }
  const btn = $("#btn-grade");
  btn.disabled = true;
  btn.textContent = t("btn.grading");

  const problem = state.problems.find((p) => p.problem_id === $("#problem").value);

  try {
    const data = await api("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        solution,
        problem_id: problem ? problem.problem_id : "",
        topic: problem ? problem.topic : "",
      }),
    });
    state.result = data;
    state.attemptId = data.attempt_id;
    state.diagnosticStatus = null;
    renderResult(data);
  } catch (err) {
    $("#marking-sheet").innerHTML = `<p class="empty">${t("sheet.offline")}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = t("btn.grade");
  }
}

function renderResult(data) {
  renderSteps(data);
  renderVerdict(data);
  renderDiagnostic(data);
  renderEvidence(data);
}

function renderSteps(data) {
  const sheet = $("#marking-sheet");
  sheet.innerHTML = "";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  data.steps.forEach((step, i) => {
    const row = document.createElement("div");
    row.className = "step";
    if (step.status === "ok") row.classList.add("is-ok");
    if (step.status === "error") row.classList.add("is-wrong");
    if (step.is_first_error) row.classList.add("is-error");
    if (step.status === "parse_error") row.classList.add("is-parse-error");
    if (step.status === "after_error") row.classList.add("is-after");

    const no = document.createElement("span");
    no.className = "step-no";
    no.textContent = step.index;

    const body = document.createElement("div");
    body.className = "step-body";
    renderMath(body, step.latex, step.raw);

    if (step.status === "parse_error") {
      const note = document.createElement("span");
      note.className = "step-note";
      note.textContent = t(`parse.${step.error_code || "unparsable"}`);
      body.appendChild(note);
    }

    const mark = document.createElement("span");
    mark.className = "step-mark";
    mark.textContent = MARK[step.status] || "";

    row.append(no, body, mark);
    if (!reduceMotion) {
      row.classList.add("reveal");
      row.style.animationDelay = `${i * 80}ms`;
    }
    sheet.appendChild(row);

    if (step.is_first_error) {
      const margin = document.createElement("p");
      margin.className = "margin-note";
      margin.textContent = t("margin.firsterror");
      if (!reduceMotion) {
        margin.classList.add("reveal");
        margin.style.animationDelay = `${(i + 1) * 80}ms`;
      }
      sheet.appendChild(margin);
    }
  });
}

function renderVerdict(data) {
  const box = $("#verdict");
  const isError = data.first_error_step !== null;
  const mis = data.misconception;

  box.className = `verdict ${isError ? "is-error" : data.has_parse_error ? "" : "is-ok"}`;
  box.hidden = false;
  if (mis) box.style.setProperty("--tone", groupColor(mis.group));
  else box.style.removeProperty("--tone");

  const errorStep = isError ? data.steps.find((s) => s.is_first_error) : null;
  const relationNote = errorStep && errorStep.relation ? t(`relation.${errorStep.relation}`) : "";

  box.innerHTML = `
    <h3>${pick(data.headline)}</h3>
    ${mis ? `<p class="mis-id">${pick(mis.group)} · ${mis.id}</p>
             <p><strong>${pick(mis.name)}</strong></p>` : ""}
    ${relationNote && relationNote.indexOf("relation.") !== 0 ? `<p>${relationNote}</p>` : ""}
    <p>${pick(data.detail)}</p>
    ${
      mis && mis.wrong_example
        ? `<div class="verdict-examples">
             <span>${t("verdict.wrong")}: <code>${mis.wrong_example}</code></span>
             <span>${t("verdict.right")}: <code>${mis.correct_example}</code></span>
           </div>`
        : ""
    }
    ${data.has_parse_error ? `<p class="footnote">${t("verdict.parsenote")}</p>` : ""}
  `;
}

function renderDiagnostic(data) {
  const box = $("#diagnostic");
  const question = pick(data.diagnostic_question);
  if (!question) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  $("#diagnostic-question").textContent = question;

  const out = $("#diagnostic-result");
  if (state.diagnosticStatus) {
    out.textContent = t(`diagnostic.${state.diagnosticStatus}`);
    out.className = `diagnostic-result is-${state.diagnosticStatus}`;
    out.hidden = false;
  } else {
    $("#diagnostic-answer").value = "";
    out.hidden = true;
  }
}

function renderEvidence(data) {
  const box = $("#evidence");
  if (!data.evidence.length) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  $("#evidence-list").innerHTML = data.evidence
    .map(
      (e) => `<li>${e.id} <span class="conf">· ${t("evidence.confidence")} ${e.confidence.toFixed(
        2
      )} · ${e.note}</span></li>`
    )
    .join("");
}

async function checkDiagnostic() {
  const answer = $("#diagnostic-answer").value.trim();
  if (!answer || !state.attemptId) return;
  const out = $("#diagnostic-result");
  try {
    const data = await api("/api/diagnostic", {
      method: "POST",
      body: JSON.stringify({ attempt_id: state.attemptId, answer }),
    });
    state.diagnosticStatus = data.status;
    out.textContent = t(`diagnostic.${data.status}`);
    out.className = `diagnostic-result is-${data.status}`;
    out.hidden = false;
  } catch (err) {
    state.diagnosticStatus = null;
    out.textContent = t("diagnostic.offline");
    out.className = "diagnostic-result";
    out.hidden = false;
  }
}

/* --------------------------------------------------------------- taxonomy */

async function loadTaxonomy() {
  state.taxonomy = await api("/api/taxonomy");
  renderTaxonomy("");
  $("#taxonomy-filter").addEventListener("input", (e) => renderTaxonomy(e.target.value));
}

function renderTaxonomy(filter) {
  const q = (filter || "").trim().toLowerCase();
  const items = state.taxonomy.filter((m) => {
    if (!q) return true;
    const haystack = [
      m.id, pick(m.name), pick(m.group), m.name.vi, m.name.en, m.group.vi, m.group.en,
    ].join(" ").toLowerCase();
    return haystack.includes(q);
  });

  $("#taxonomy-grid").innerHTML = items
    .map(
      (m) => `
      <article class="tax-card" style="--tone: ${groupColor(m.group)}">
        <p class="mis-id">${m.id} · ${pick(m.group)}</p>
        <h3>${pick(m.name)}</h3>
        <p>${pick(m.definition)}</p>
        <div class="tax-examples">
          <span class="bad">${m.wrong_example || ""}</span>
          <span class="good">${m.correct_example || ""}</span>
        </div>
      </article>`
    )
    .join("");
}

/* ---------------------------------------------------------------- profile */

async function loadProfile() {
  const data = await api("/api/profile");
  const wrong = data.total_attempts - data.clean_attempts;

  $("#profile-stats").innerHTML = `
    <div class="stat"><b>${data.total_attempts}</b><span>${t("profile.attempts")}</span></div>
    <div class="stat"><b>${data.clean_attempts}</b><span>${t("profile.clean")}</span></div>
    <div class="stat"><b>${wrong}</b><span>${t("profile.wrong")}</span></div>
  `;

  if (!data.by_misconception.length) {
    $("#profile-table").innerHTML = `<p class="empty">${t("profile.empty")}</p>`;
    return;
  }

  $("#profile-table").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>${t("col.code")}</th><th>${t("col.name")}</th><th>${t("col.count")}</th>
          <th>${t("col.answered")}</th><th>${t("col.fixed")}</th>
        </tr>
      </thead>
      <tbody>
        ${data.by_misconception
          .map(
            (m) => `<tr>
              <td class="num" style="color: ${groupColor(m.group)}">${m.id}</td>
              <td class="tone">${pick(m.name)}</td>
              <td class="num">${m.count}</td>
              <td class="num">${m.answered}</td>
              <td class="num">${m.fixed}</td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
}

/* ------------------------------------------------------------------- init */

function init() {
  let saved = null;
  try {
    saved = localStorage.getItem("mathlens_lang");
  } catch (err) {
    /* storage unavailable, keep the default */
  }
  const browserPrefersEnglish = (navigator.language || "").toLowerCase().startsWith("en");
  state.lang = saved || (browserPrefersEnglish ? "en" : "vi");

  $$(".lang-btn").forEach((btn) =>
    btn.addEventListener("click", () => setLanguage(btn.dataset.lang))
  );
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));

  $("#btn-grade").addEventListener("click", grade);
  $("#btn-clear").addEventListener("click", () => {
    $("#solution").value = "";
    state.result = null;
    state.attemptId = null;
    state.diagnosticStatus = null;
    renderEmptySheet();
    $("#verdict").hidden = true;
    $("#diagnostic").hidden = true;
    $("#evidence").hidden = true;
  });
  $("#btn-diagnostic").addEventListener("click", checkDiagnostic);
  $("#diagnostic-answer").addEventListener("keydown", (e) => {
    if (e.key === "Enter") checkDiagnostic();
  });
  $$(".chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      $("#solution").value = chip.dataset.sample;
      grade();
    })
  );
  $("#solution").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) grade();
  });

  setLanguage(state.lang);
  loadProblems().catch(() => {});
  loadTaxonomy().catch(() => {});
}

document.addEventListener("DOMContentLoaded", init);
