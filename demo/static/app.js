"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const config = {
  A: {title:"Fixed-size", description:"500 ký tự · overlap 50 · không lọc"},
  B: {title:"Paragraph", description:"Tối đa 700 ký tự · không lọc"},
  C: {title:"Paragraph + metadata", description:"Cùng chunk với B · lọc section khi được cung cấp"}
};
const state = {data:null, questionId:null, split:"all", mode:"saved", history:[], selectedHistory:null, busy:false};

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Không đọc được dữ liệu.");
  return data;
}
function notice(message = "", error = false) {
  $("notice").hidden = !message;
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
function pdf(page, label) {
  return `<a href="/document.pdf#page=${Number(page)}" target="_blank" rel="noopener">${esc(label || `Trang ${page}`)} ↗</a>`;
}
function renderList() {
  if (!state.data) return;
  const search = $("question-search").value.trim().toLowerCase();
  const questions = state.data.questions.filter(q => (state.split === "all" || q.split === state.split) && `${q.id} ${q.question}`.toLowerCase().includes(search));
  $("question-count").textContent = questions.length;
  $("question-list").innerHTML = questions.map(q => `<button class="question-item ${q.id === state.questionId ? "active" : ""}" data-id="${esc(q.id)}" ${q.id === state.questionId ? 'aria-current="true"' : ""}><div class="question-meta"><strong>${esc(q.id.toUpperCase())}</strong><span>${esc(q.split.toUpperCase())}${q.filter ? " · FILTER" : ""}</span></div><p>${esc(q.question)}</p></button>`).join("") || '<p class="side-copy">Không tìm thấy câu hỏi.</p>';
}
function renderResults(traces, saved) {
  $("result-area").hidden = false;
  $("live-empty").hidden = true;
  $("results").classList.toggle("single", traces.length === 1);
  $("results").innerHTML = traces.map(trace => {
    const c = config[trace.strategy];
    const filter = trace.filter ? `section = ${trace.filter.section}` : "Không áp dụng filter";
    const metrics = saved ? `<div class="metric-row"><span class="metric ${trace.hit_at_1 ? "yes" : ""}">Hit@1 ${trace.hit_at_1 ? "✓" : "✕"}</span><span class="metric ${trace.evidence_hit_at_3 ? "yes" : ""}">Evidence Hit@3 ${trace.evidence_hit_at_3 ? "✓" : "✕"}</span></div>` : "";
    const cards = trace.hits.map((hit, index) => {
      const score = Number(hit.score);
      const width = Math.max(0, Math.min(100, score * 100));
      return `<article class="chunk ${saved && hit.evidence_match ? "hit" : ""}"><div class="chunk-top"><span class="rank">RANK 0${index + 1}</span><span class="score">${score.toFixed(4)}</span></div><div class="score-bar"><span style="width:${width}%"></span></div>${saved && hit.evidence_match ? '<span class="evidence-tag">Khớp gold evidence</span>' : ""}<p class="chunk-text">${esc(hit.text)}</p><div class="chunk-source"><span>${esc(hit.source)}</span>${pdf(hit.page)}</div><div class="chunk-section">SECTION / ${esc(hit.metadata?.section || "Không có nhãn")}</div><div class="chunk-id">${esc(hit.chunk_id)}</div><details><summary>Metadata</summary><p>${esc(JSON.stringify(hit.metadata, null, 2))}</p></details></article>`;
    }).join("");
    return `<section class="strategy-column strategy-${trace.strategy.toLowerCase()}" aria-label="Cấu hình ${esc(trace.strategy)}"><div class="strategy-header"><div class="strategy-title"><span class="strategy-letter">${esc(trace.strategy)}</span><h3>${esc(c.title)}</h3></div><p class="strategy-description">${esc(c.description)}<br>${esc(filter)}</p>${metrics}</div>${cards || '<div class="chunk"><p class="chunk-text">Không có chunk phù hợp với điều kiện.</p></div>'}${trace.hits.length < 3 ? `<p class="form-hint">Trả về ${trace.hits.length}/3 chunk; không thêm kết quả ngoài filter.</p>` : ""}</section>`;
  }).join("");
}
function selectQuestion(id) {
  if (!state.data) return;
  const q = state.data.questions.find(q => q.id === id);
  if (!q) return;
  state.questionId = id;
  renderList();
  $("question-detail").hidden = false;
  $("question-detail").innerHTML = `<div class="detail-meta"><span class="tag">${esc(q.id.toUpperCase())}</span><span class="tag neutral">${esc(q.split.toUpperCase())}</span>${q.filter ? '<span class="tag">CÓ FILTER</span>' : ""}</div><h2>${esc(q.question)}</h2><p><strong>Đáp án kỳ vọng:</strong> ${esc(q.expected_answer)}</p><p><strong>Gold:</strong> ${esc(q.gold_source_id)} · ${pdf(q.gold_page)}${q.filter ? ` · <strong>Filter:</strong> ${esc(JSON.stringify(q.filter))}` : ""}</p><details><summary>Xem gold evidence</summary><p>${esc(q.evidence_quote)}</p></details><button class="secondary" id="try-question" style="margin-top:16px">Thử lại câu hỏi này ↗</button>`;
  renderResults(state.data.traces.filter(t => t.question_id === id).sort((a,b) => a.strategy.localeCompare(b.strategy)), true);
  $("try-question").onclick = () => {
    setMode("live");
    $("query-input").value = q.question;
    ensureSection(q.filter?.section || "");
    $("strategy").value = "all";
    syncFilter();
    $("query-input").focus();
  };
}
function ensureSection(section) {
  if (section && !Array.from($("section").options).some(o => o.value === section)) {
    const option = new Option(section, section);
    $("section").add(option);
  }
  $("section").value = section;
}
function setMode(mode) {
  state.mode = mode;
  const live = mode === "live";
  $("saved-mode").classList.toggle("active", !live);
  $("live-mode").classList.toggle("active", live);
  $("saved-controls").hidden = live;
  $("live-sidebar").hidden = !live;
  $("live-panel").hidden = !live;
  $("page-title").textContent = live ? "Thử query mới" : "Kết quả đã lưu";
  $("page-description").textContent = live ? "Truy xuất trực tiếp từ database với cùng embedding model của benchmark." : "So sánh top-3 chunk của A, B và C trên cùng một câu hỏi.";
  notice();
  if (live) {
    $("question-detail").hidden = true;
    $("result-area").hidden = true;
    $("live-empty").hidden = true;
    if (state.selectedHistory !== null) showHistory(state.selectedHistory);
    else $("live-empty").hidden = false;
    if (state.busy) notice("Đang tải model và truy xuất. Lần đầu có thể mất nhiều thời gian hơn…");
  } else {
    $("live-empty").hidden = true;
    if (state.data) selectQuestion(state.questionId || state.data.questions[0]?.id);
  }
}
function renderHistory() {
  $("history").innerHTML = state.history.map((item, i) => `<button class="question-item ${state.selectedHistory === i ? "active" : ""}" data-history="${i}"><div class="question-meta"><strong>QUERY ${String(i+1).padStart(2,"0")}</strong><span>${item.results.map(t => t.strategy).join(" / ")}</span></div><p>${esc(item.question)}</p></button>`).reverse().join("") || '<p class="side-copy">Chưa có truy vấn mới.</p>';
}
function showHistory(index) {
  state.selectedHistory = index;
  const item = state.history[index];
  $("question-detail").hidden = false;
  $("question-detail").innerHTML = `<div class="detail-meta"><span class="tag">QUERY MỚI</span><span class="tag neutral">${item.seconds.toFixed(3)} giây</span></div><h2>${esc(item.question)}</h2><p>Chưa có gold evidence cho query mới nên không tính Hit@1, Hit@3 hoặc điểm grounding.</p>`;
  renderResults(item.results, false);
  renderHistory();
}
function syncFilter() {
  const active = ["all", "C"].includes($("strategy").value);
  $("section").disabled = !active;
  $("load-sections").disabled = !active || state.busy;
}
$("saved-mode").onclick = () => setMode("saved");
$("live-mode").onclick = () => setMode("live");
$("question-search").oninput = renderList;
$("question-list").onclick = event => {const button = event.target.closest("[data-id]"); if (button) selectQuestion(button.dataset.id);};
$("history").onclick = event => {const button = event.target.closest("[data-history]"); if (button) showHistory(Number(button.dataset.history));};
document.querySelectorAll("[data-split]").forEach(button => button.onclick = () => {
  state.split = button.dataset.split;
  document.querySelectorAll("[data-split]").forEach(b => b.classList.toggle("active", b === button));
  renderList();
});
$("strategy").onchange = syncFilter;
$("load-sections").onclick = async () => {
  const button = $("load-sections");
  button.disabled = true; button.textContent = "Đang đọc…";
  try {
    const data = await api("/api/sections");
    const selected = $("section").value;
    $("section").replaceChildren(new Option("Không lọc", ""), ...data.sections.map(section => new Option(section, section)));
    if (data.sections.includes(selected)) $("section").value = selected;
    notice(`Đã tải ${data.sections.length} section từ cấu hình C trong database.`);
  } catch(error) { notice(error.message, true); }
  finally {button.textContent = "Tải section từ DB";syncFilter();}
};
$("query-form").onsubmit = async event => {
  event.preventDefault();
  if (state.busy) return;
  state.busy = true;
  $("run-query").disabled = true; $("run-query").textContent = "Đang truy xuất…";syncFilter();
  notice("Đang tải model và truy xuất. Lần đầu có thể mất nhiều thời gian hơn…");
  try {
    const result = await api("/api/query", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({question:$("query-input").value, strategy:$("strategy").value, section:$("section").value})});
    state.history.push(result);
    state.selectedHistory = state.history.length - 1;
    renderHistory();
    if (state.mode === "live") {showHistory(state.selectedHistory);notice();}
  } catch(error) {if (state.mode === "live") notice(error.message, true);}
  finally {state.busy=false;$("run-query").disabled=false;$("run-query").textContent="Truy xuất";syncFilter();}
};
(async () => {
  try {
    state.data = await api("/api/saved");
    $("stat-questions").textContent = state.data.questions.length;
    state.questionId = state.data.questions[0]?.id;
    renderList();renderHistory();
    if (state.mode === "saved") selectQuestion(state.questionId);
    // Saved section values are useful even when the database is offline.
    [...new Set(state.data.traces.flatMap(t => t.hits.map(h => h.metadata?.section)).filter(Boolean))].sort().forEach(section => $("section").add(new Option(section, section)));
  } catch(error) {notice(error.message, true);}
})();
