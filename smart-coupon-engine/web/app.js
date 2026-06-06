// 对客网站前端逻辑：上传 → 调 /api/recommend → 渲染结果 → 本地生成文件下载。
// 全程无第三方依赖、无构建步骤。

const $ = (sel) => document.querySelector(sel);

const views = {
  upload: $("#view-upload"),
  loading: $("#view-loading"),
  result: $("#view-result"),
};
let lastResult = null; // 缓存最近一次结果（含完整 csv / xlsx），供下载

function show(view) {
  views.upload.hidden = view !== "upload";
  views.loading.hidden = view !== "loading";
  views.result.hidden = view !== "result";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showError(msg) {
  const el = $("#error");
  el.textContent = msg;
  el.hidden = false;
}
function clearError() {
  $("#error").hidden = true;
}

// ---------- 上传位：点击 + 拖拽 ----------
function bindDrop(dropId, inputId) {
  const drop = $(dropId);
  const input = $(inputId);
  const fileEl = drop.querySelector(".drop__file");

  const setFile = (file) => {
    if (!file) return;
    input._file = file;
    fileEl.textContent = "✓ " + file.name;
    drop.classList.add("filled");
    clearError();
  };

  input.addEventListener("change", () => setFile(input.files[0]));
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("dragover");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) {
      input.files = e.dataTransfer.files;
      setFile(file);
    }
  });
  return input;
}

const customersInput = bindDrop("#drop-customers", "#file-customers");
const productsInput = bindDrop("#drop-products", "#file-products");
const behaviorInput = bindDrop("#drop-behavior", "#file-behavior");

// ---------- 调用后端 ----------
async function runUpload() {
  clearError();
  const cu = customersInput.files[0];
  const pr = productsInput.files[0];
  const be = behaviorInput.files[0];
  if (!cu || !pr || !be) {
    showError("请先把「客户属性」「商品属性」「行为日志」三个 CSV 都上传。");
    return;
  }
  const fd = new FormData();
  fd.append("customers", cu);
  fd.append("products", pr);
  fd.append("behavior", be);
  fd.append("budget", $("#budget").value || "0");

  show("loading");
  try {
    const resp = await fetch("/api/recommend", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "计算失败");
    lastResult = data;
    renderResult(data);
  } catch (err) {
    show("upload");
    showError("出错了：" + err.message);
  }
}

async function runDemo() {
  clearError();
  $("#loading-text").textContent = "正在生成示例数据并计算…";
  show("loading");
  try {
    const budget = $("#budget").value || "60000";
    const resp = await fetch("/api/demo?budget=" + encodeURIComponent(budget));
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "计算失败");
    lastResult = data;
    renderResult(data);
  } catch (err) {
    show("upload");
    showError("出错了：" + err.message);
  }
}

// ---------- 渲染结果 ----------
function renderResult(data) {
  const s = data.summary;
  const cards = [
    { label: "覆盖客户数", value: fmt(s["客户总数"]) },
    { label: "建议发券人数", value: fmt(s["建议发券人数"]) + " 人", accent: true },
    { label: "预期券成本 / 预算", value: "¥" + fmt(s["预期券成本"]) + " / ¥" + fmt(s["总预算"]) },
    { label: "预算使用率", value: s["预算使用率"] + "%" },
  ];
  $("#summary-cards").innerHTML = cards
    .map(
      (c) => `<div class="stat">
        <div class="stat__value ${c.accent ? "accent" : ""}">${c.value}</div>
        <div class="stat__label">${c.label}</div>
      </div>`
    )
    .join("");

  // 模型评估
  renderEvaluation(data.evaluation);

  // 预览表
  const cols = data.columns;
  const thead = `<thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>`;
  const rows = data.preview
    .map((row) => {
      const tds = cols
        .map((col) => {
          let v = row[col];
          if (col === "是否发放") {
            const cls = v === "是" ? "pill--yes" : "pill--no";
            return `<td><span class="pill ${cls}">${v}</span></td>`;
          }
          if (col === "推荐券面额" || col === "最优面额") v = "¥" + v;
          if (col === "预期增量购买概率") v = (v * 100).toFixed(2) + "%";
          if (col === "预期成本") v = "¥" + v;
          return `<td>${v}</td>`;
        })
        .join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  $("#result-table").innerHTML = thead + `<tbody>${rows}</tbody>`;
  $("#preview-count").textContent = `（共 ${fmt(data.n_rows)} 行，展示前 ${data.preview.length} 行）`;

  // 面额分布
  const dist = s["面额分布"] || [];
  const max = Math.max(1, ...dist.map((d) => d["人数"]));
  $("#dist-card").hidden = dist.length === 0;
  $("#dist").innerHTML = dist
    .map(
      (d) => `<div class="dist__row">
        <div class="dist__label">¥${d["面额"]}</div>
        <div class="dist__bar"><div class="dist__fill" style="width:${(100 * d["人数"]) / max}%"></div></div>
        <div class="dist__count">${fmt(d["人数"])} 人</div>
      </div>`
    )
    .join("");

  show("result");
}

function fmt(n) {
  return Number(n).toLocaleString("zh-CN");
}

// ---------- 模型评估渲染 ----------
function renderEvaluation(ev) {
  const card = $("#eval-card");
  if (!ev) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  if (!ev["可用"]) {
    $("#eval-note").textContent = "ℹ️ " + (ev["说明"] || "本次数据无法评估。");
    $("#eval-metrics").innerHTML = "";
    $("#eval-deciles").innerHTML = "";
    return;
  }

  const s = ev["样本"] || {};
  $("#eval-note").textContent =
    `测试集 ${fmt(s["测试集"])} 人（处理组 ${fmt(s["处理组"])} / 对照组 ${fmt(s["对照组"])}）。下列指标越高代表模型越能把券发给“被券打动的人”。`;

  const lift = ev["提升倍数"];
  const cards = [
    { label: "Top 档提升倍数", value: lift != null ? lift + "×" : "—", accent: true,
      hint: "最高分 10% 客户的真实 uplift ÷ 整体平均" },
    { label: "Qini 系数", value: ev["Qini系数"], hint: ">0 即优于随机发券" },
    { label: "AUUC", value: ev["AUUC"], hint: "增益曲线下面积，越大越好" },
    { label: "对照/处理模型 AUC", value: (ev["对照模型AUC"] ?? "—") + " / " + (ev["处理模型AUC"] ?? "—"),
      hint: "两个子模型的判别力（0.5=随机，1=完美）" },
  ];
  $("#eval-metrics").innerHTML = cards
    .map(
      (c) => `<div class="stat" title="${c.hint}">
        <div class="stat__value ${c.accent ? "accent" : ""}">${c.value}</div>
        <div class="stat__label">${c.label}</div>
      </div>`
    )
    .join("");

  // 分位 uplift 柱（正向蓝、负向红，0 在中线）
  const rows = ev["分位表"] || [];
  const maxAbs = Math.max(0.0001, ...rows.map((r) => Math.abs(r["实际uplift"] ?? 0)));
  $("#eval-deciles").innerHTML = rows
    .map((r, i) => {
      const v = r["实际uplift"];
      if (v == null) {
        return `<div class="decile"><div class="decile__label">第${i + 1}档</div>
          <div class="decile__track"></div><div class="decile__val">—</div></div>`;
      }
      const w = (Math.abs(v) / maxAbs) * 50; // 半轴最多 50%
      const bar = v >= 0
        ? `<div class="decile__bar pos" style="width:${w}%"></div>`
        : `<div class="decile__bar neg" style="width:${w}%"></div>`;
      return `<div class="decile">
        <div class="decile__label">第${i + 1}档</div>
        <div class="decile__track">${bar}</div>
        <div class="decile__val">${(v * 100).toFixed(1)}%</div>
      </div>`;
    })
    .join("");
}

// ---------- 下载（本地生成 Blob，无需服务端存储）----------
function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadCsv() {
  if (!lastResult) return;
  // 加 BOM，Excel 打开 UTF-8 中文不乱码
  const blob = new Blob(["﻿" + lastResult.result_csv], { type: "text/csv;charset=utf-8" });
  download(blob, "推荐券面额.csv");
}

function downloadXlsx() {
  if (!lastResult) return;
  const bytes = Uint8Array.from(atob(lastResult.result_xlsx_b64), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  download(blob, "推荐券面额.xlsx");
}

function reset() {
  lastResult = null;
  show("upload");
}

// ---------- 绑定 ----------
$("#btn-run").addEventListener("click", runUpload);
$("#btn-demo").addEventListener("click", runDemo);
$("#btn-csv").addEventListener("click", downloadCsv);
$("#btn-xlsx").addEventListener("click", downloadXlsx);
$("#btn-reset").addEventListener("click", reset);
