// Read-only curriculum library. Hash routes:
//   #/                       -> grade list
//   #/grade/<gradeId>        -> topics in grade
//   #/topic/<topicId>        -> lessons in topic
//   #/lesson/<lessonId>      -> lesson detail (tabbed)
const view = document.getElementById("view");
const breadcrumb = document.getElementById("breadcrumb");

const esc = (s) =>
  String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

async function api(path) {
  const res = await fetch(path);
  if (res.status === 404) throw { kind: "notfound" };
  if (!res.ok) throw { kind: "error", status: res.status };
  return res.json();
}

function setLoading() {
  view.innerHTML = `<div class="lib-loading">Đang tải…</div>`;
}
function setError(msg) {
  view.innerHTML = `<div class="lib-error">${esc(msg)}</div>`;
}
function setBreadcrumb(parts) {
  breadcrumb.innerHTML = parts
    .map((p, i) =>
      p.href
        ? `<a href="${p.href}">${esc(p.label)}</a>`
        : `<span>${esc(p.label)}</span>`
    )
    .join('<span class="sep">›</span>');
}

// ---- Views ----
async function showGrades() {
  setBreadcrumb([{ label: "Thư viện" }]);
  setLoading();
  try {
    const grades = await api("/api/curriculum/grades");
    view.innerHTML = `<div class="card-grid">${grades
      .map(
        (g) => `<a class="card grade-card" href="#/grade/${encodeURIComponent(g.id)}">
            <div class="card-title">${esc(g.label || "Lớp " + g.gradeNumber)}</div>
          </a>`
      )
      .join("")}</div>`;
  } catch (e) {
    setError("Không tải được danh sách lớp. Vui lòng thử lại.");
  }
}

async function showTopics(gradeId) {
  setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: gradeId }]);
  setLoading();
  try {
    const topics = await api(`/api/curriculum/grades/${encodeURIComponent(gradeId)}/topics`);
    if (!topics.length) return setError("Lớp này chưa có chủ đề nào.");
    setBreadcrumb([
      { label: "Thư viện", href: "#/" },
      { label: gradeId },
    ]);
    view.innerHTML = `<div class="card-grid">${topics
      .map(
        (t) => `<a class="card topic-card" href="#/topic/${encodeURIComponent(t.id)}">
            <div class="card-title">${esc(t.label || t.title)}</div>
            ${t.subtitle ? `<div class="card-sub">${esc(t.subtitle)}</div>` : ""}
            <div class="card-meta">${esc(t.lessonCount)} bài</div>
          </a>`
      )
      .join("")}</div>`;
  } catch (e) {
    setError(e.kind === "notfound" ? "Không tìm thấy lớp." : "Không tải được chủ đề.");
  }
}

async function showLessons(topicId) {
  setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: topicId }]);
  setLoading();
  try {
    const lessons = await api(`/api/curriculum/topics/${encodeURIComponent(topicId)}/lessons`);
    if (!lessons.length) return setError("Chủ đề này chưa có bài học nào.");
    view.innerHTML = `<div class="lesson-list">${lessons
      .map(
        (l) => `<a class="lesson-row" href="#/lesson/${encodeURIComponent(l.id)}">
            <span class="lesson-name">${esc(l.label || l.title)}</span>
            ${l.startPage ? `<span class="lesson-pages">tr. ${l.startPage}–${l.endPage}</span>` : ""}
          </a>`
      )
      .join("")}</div>`;
  } catch (e) {
    setError(e.kind === "notfound" ? "Không tìm thấy chủ đề." : "Không tải được bài học.");
  }
}

function renderTabs(d) {
  const tabs = [
    { key: "noidung", label: "Nội dung" },
    { key: "hinhbang", label: "Hình & bảng" },
    { key: "khainiem", label: "Khái niệm" },
    { key: "baitap", label: "Bài tập" },
  ];
  const panels = {
    noidung: renderContent(d),
    hinhbang: renderFiguresTables(d),
    khainiem: renderConcepts(d),
    baitap: renderAssessments(d),
  };
  view.innerHTML = `
    <article class="lesson">
      <h2 class="lesson-heading">${esc(d.label || d.title)}</h2>
      ${
        d.objectives && d.objectives.length
          ? `<section class="objectives"><h3>Mục tiêu</h3>${d.objectives
              .map((o) => `<p>${esc(o)}</p>`)
              .join("")}</section>`
          : ""
      }
      <div class="tabbar" role="tablist">
        ${tabs
          .map(
            (t, i) =>
              `<button class="tab${i === 0 ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
          )
          .join("")}
      </div>
      ${tabs
        .map(
          (t, i) =>
            `<section class="tabpanel${i === 0 ? " active" : ""}" data-panel="${t.key}">${panels[t.key]}</section>`
        )
        .join("")}
    </article>`;

  view.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.tab;
      view.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      view.querySelectorAll(".tabpanel").forEach((p) =>
        p.classList.toggle("active", p.dataset.panel === key)
      );
    });
  });

  view.querySelectorAll(".ex-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".assessment");
      const mount = card.querySelector(".ex-mount");
      const ex = (d.assessments || []).find((a) => a.id === btn.dataset.exId);
      if (!ex) return;
      if (mount.dataset.open === "1") {
        mount.innerHTML = "";
        mount.dataset.open = "0";
        btn.textContent = "✍️ Làm bài";
        return;
      }
      window.mountExerciseRunner(mount, [{ id: ex.id, title: ex.title, text: ex.text }]);
      mount.dataset.open = "1";
      btn.textContent = "Ẩn";
    });
  });
}

function renderContent(d) {
  const empty = `<p class="empty">Không có nội dung.</p>`;
  if (!d.sections || !d.sections.length) return empty;
  return d.sections
    .map(
      (s) => `<div class="section">
        <h3 class="section-title">${esc(s.title)}</h3>
        ${(s.paragraphs || []).map((p) => `<p>${esc(p.text)}</p>`).join("")}
      </div>`
    )
    .join("");
}

function renderFiguresTables(d) {
  const figs = (d.figures || [])
    .map(
      (f) => `<figure class="fig">
        ${
          f.imageUrl
            ? `<a href="${esc(f.imageUrl)}" target="_blank" rel="noopener"><img src="${esc(f.imageUrl)}" alt="${esc(f.caption)}" loading="lazy"/></a>`
            : `<div class="fig-noimg">🖼️</div>`
        }
        <figcaption>${esc(f.caption)}</figcaption>
      </figure>`
    )
    .join("");
  const tables = (d.tables || [])
    .map(
      (t) => `<div class="tbl">
        <div class="tbl-caption">${esc(t.caption)}</div>
        <p class="tbl-text">${esc(t.text)}</p>
      </div>`
    )
    .join("");
  if (!figs && !tables) return `<p class="empty">Không có hình ảnh hoặc bảng.</p>`;
  return `${figs ? `<div class="fig-grid">${figs}</div>` : ""}${tables}`;
}

function renderConcepts(d) {
  if (!d.concepts || !d.concepts.length) return `<p class="empty">Không có khái niệm.</p>`;
  return `<div class="concept-list">${d.concepts
    .map(
      (c) => `<div class="concept-item">
        <span class="concept-name">${esc(c.label)}</span>
        ${c.definition ? `<p class="concept-def">${esc(c.definition)}</p>` : ""}
      </div>`
    )
    .join("")}</div>`;
}

function renderAssessments(d) {
  if (!d.assessments || !d.assessments.length) return `<p class="empty">Không có bài tập.</p>`;
  return d.assessments
    .map(
      (a) => `<div class="assessment" data-ex-id="${esc(a.id)}">
        <div class="assessment-type">${esc(a.title || a.type)}</div>
        <p>${esc(a.text)}</p>
        <button class="ex-toggle" data-ex-id="${esc(a.id)}">✍️ Làm bài</button>
        <div class="ex-mount" data-open="0"></div>
      </div>`
    )
    .join("");
}

async function showLesson(lessonId) {
  setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: "Bài học" }]);
  setLoading();
  try {
    const d = await api(`/api/curriculum/lessons/${encodeURIComponent(lessonId)}`);
    setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: d.label || d.title }]);
    renderTabs(d);
  } catch (e) {
    setError(e.kind === "notfound" ? "Không tìm thấy bài học." : "Không tải được bài học.");
  }
}

// ---- Router ----
function route() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const m = hash.match(/^\/(grade|topic|lesson)\/(.+)$/);
  if (!m) return showGrades();
  const id = decodeURIComponent(m[2]);
  if (m[1] === "grade") return showTopics(id);
  if (m[1] === "topic") return showLessons(id);
  if (m[1] === "lesson") return showLesson(id);
  return showGrades();
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
