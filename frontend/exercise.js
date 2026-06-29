// Shared interactive exercise runner. Used by the Library Bài tập tab and the
// QA chatbot. mountExerciseRunner(container, [{id, title, text}]).
(function () {
  function escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const VERDICT = {
    correct: ["Chính xác", "verdict-correct"],
    partial: ["Gần đúng", "verdict-partial"],
    incorrect: ["Chưa chính xác", "verdict-incorrect"],
  };

  async function gradeOne(id, answer) {
    const res = await fetch("/api/exercises/grade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exerciseId: id, userAnswer: answer }),
    });
    if (!res.ok) {
      let detail = "HTTP " + res.status;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return res.json();
  }

  function mountExerciseRunner(container, exercises) {
    container.innerHTML = exercises
      .map(
        (ex) => `<div class="ex-runner" data-id="${escHtml(ex.id)}">
          <div class="ex-q">${ex.title ? `<strong>${escHtml(ex.title)}</strong><br>` : ""}${escHtml(ex.text)}</div>
          <textarea class="ex-input" rows="3" placeholder="Nhập câu trả lời của em..."></textarea>
          <div class="ex-actions"><button class="ex-submit">Nộp bài</button></div>
          <div class="ex-result"></div>
        </div>`
      )
      .join("");

    container.querySelectorAll(".ex-runner").forEach((el) => {
      const id = el.dataset.id;
      const input = el.querySelector(".ex-input");
      const submit = el.querySelector(".ex-submit");
      const result = el.querySelector(".ex-result");

      submit.addEventListener("click", async () => {
        const ans = input.value.trim();
        if (!ans) {
          result.innerHTML = `<div class="ex-hint">Hãy nhập câu trả lời trước khi nộp.</div>`;
          return;
        }
        submit.disabled = true;
        result.innerHTML = `<div class="ex-loading">Đang chấm…</div>`;
        try {
          const d = await gradeOne(id, ans);
          const [label, cls] = VERDICT[d.verdict] || ["Đã chấm", "verdict-partial"];
          result.innerHTML =
            `<div class="ex-verdict ${cls}">${label}</div>` +
            (d.feedback ? `<div class="ex-feedback">${escHtml(d.feedback)}</div>` : "") +
            (d.modelAnswer
              ? `<div class="ex-model"><div class="ex-model-h">Đáp án mẫu</div><div>${escHtml(d.modelAnswer)}</div></div>`
              : "") +
            `<div class="ex-actions"><button class="ex-retry">Làm lại</button></div>`;
          result.querySelector(".ex-retry").addEventListener("click", () => {
            result.innerHTML = "";
            submit.disabled = false;
            input.focus();
          });
        } catch (err) {
          result.innerHTML =
            `<div class="ex-error">Lỗi chấm bài: ${escHtml(err.message)} ` +
            `<button class="ex-retry">Thử lại</button></div>`;
          result.querySelector(".ex-retry").addEventListener("click", () => {
            result.innerHTML = "";
          });
          submit.disabled = false;
        }
      });
    });
  }

  window.mountExerciseRunner = mountExerciseRunner;
})();
