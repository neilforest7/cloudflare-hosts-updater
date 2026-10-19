"use strict";

const $ = (selector) => document.querySelector(selector);
const csrf = $('meta[name="csrf-token"]').content;
const labels = {
  running: "运行中",
  success: "成功",
  partial: "部分成功",
  failed: "失败",
  legacy: "旧版记录",
};
let activeView = "overview";
let lastFinished = null;
let refreshTimer;
let submittedJob = null;
let statusSequence = 0;

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = content;
  if (className) node.className = className;
  return node;
}

function notice(message, error = false) {
  const box = $("#notice");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = false;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-CSRFToken": csrf, ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || `请求失败（${response.status}）`);
  return data;
}

function timeLabel(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? value
    : parsed.toLocaleString("zh-CN", { hour12: false });
}

function badge(status) {
  return element("span", labels[status] || status, `badge ${status}`);
}

function showView(view) {
  activeView = view;
  document.querySelectorAll(".view").forEach((node) => {
    node.hidden = node.id !== `view-${view}`;
  });
  document.querySelectorAll("[data-view]").forEach((node) => {
    const selected = node.dataset.view === view;
    node.classList.toggle("active", selected);
    if (selected) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  $("#page-title").textContent = $(`[data-view="${view}"]`).textContent;
  if (view === "containers") refreshContainers();
  if (view === "logs") refreshLogs();
}

document
  .querySelectorAll("[data-view]")
  .forEach((node) =>
    node.addEventListener("click", () => showView(node.dataset.view)),
  );
$("[data-open-config]").addEventListener("click", () => {
  showView("config");
  $("#CF_DOMAINS").focus();
});

function renderHistory(history) {
  const body = $("#history-body");
  const openRecords = new Set(
    [...body.querySelectorAll("details[open]")].map(
      (node) => node.dataset.recordId,
    ),
  );
  body.replaceChildren();
  for (const record of history) {
    const row = element("tr");
    row.append(element("td", timeLabel(record.timestamp)));
    row.append(
      element(
        "td",
        { manual: "手动执行", scheduled: "定时执行", startup: "启动执行" }[
          record.source
        ] || (record.is_scheduled ? "定时执行" : "手动执行"),
      ),
    );
    const state = element("td");
    state.append(badge(record.status || "legacy"));
    row.append(state);
    const detail = element("td");
    if (record.message) detail.append(element("div", record.message));
    const expanded = element("details");
    expanded.dataset.recordId = record.id || record.timestamp;
    expanded.open = openRecords.has(expanded.dataset.recordId);
    expanded.append(element("summary", "查看详情"));
    for (const [domain, ips] of Object.entries(record.ips || {}))
      expanded.append(
        element(
          "div",
          `${domain}: ${Array.isArray(ips) ? ips.join(", ") : ips}`,
        ),
      );
    for (const container of record.containers || [])
      expanded.append(
        element(
          "div",
          `${container.name}：${container.success ? "已更新" : container.error}`,
        ),
      );
    detail.append(expanded);
    row.append(detail);
    body.append(row);
  }
  if (!history.length) {
    const row = element("tr");
    const cell = element("td", "暂无执行记录", "empty");
    cell.colSpan = 4;
    row.append(cell);
    body.append(row);
  }
}

async function refreshHosts() {
  try {
    const { hosts } = await api("/api/hosts");
    $("#hosts-preview").textContent = hosts || "暂无内容";
    const mappings = new Map();
    for (const line of hosts.split("\n")) {
      const parts = line.split("#", 1)[0].trim().split(/\s+/);
      if (parts.length < 2) continue;
      const [ip, domain] = parts;
      if (!mappings.has(domain)) mappings.set(domain, []);
      mappings.get(domain).push(ip);
    }
    const body = $("#mapping-body");
    body.replaceChildren();
    for (const [domain, ips] of mappings) {
      const row = element("tr");
      row.append(element("td", domain), element("td", ips.join(", ")));
      body.append(row);
    }
    if (!mappings.size) {
      const row = element("tr");
      const cell = element("td", "尚未生成映射", "empty");
      cell.colSpan = 2;
      row.append(cell);
      body.append(row);
    }
  } catch (error) {
    notice(error.message, true);
  }
}

async function refreshStatus() {
  clearTimeout(refreshTimer);
  const sequence = ++statusSequence;
  let running = false;
  try {
    const state = await api("/api/status");
    if (sequence !== statusSequence) return;
    running = state.running;
    $("#task-state").textContent = running
      ? "任务运行中"
      : state.job
        ? labels[state.job.status]
        : "等待首次执行";
    $("#task-detail").textContent =
      state.job?.message || "配置完成后即可开始更新";
    $("#next-run").textContent = state.next_run
      ? timeLabel(state.next_run)
      : "未安排自动更新";
    $("#last-success").textContent = timeLabel(state.last_success);
    $("#setup-hint").hidden = state.configured;
    $("#running-badge").hidden = !running;
    document.querySelectorAll("[data-run]").forEach((node) => {
      node.disabled = running;
    });
    $("#job-results").replaceChildren();
    for (const item of state.job?.containers || []) {
      const line = element("div", undefined, "result-line");
      line.append(badge(item.success ? "success" : "failed"));
      line.append(
        element("span", `${item.name}${item.error ? `：${item.error}` : ""}`),
      );
      $("#job-results").append(line);
    }
    renderHistory(state.history);
    const finished = state.job?.finished_at ? state.job.id : null;
    if (finished && finished !== lastFinished) {
      lastFinished = finished;
      refreshHosts();
      if (activeView === "containers") refreshContainers();
    }
    if (finished && finished === submittedJob) {
      notice(state.job.message, state.job.status !== "success");
      submittedJob = null;
    }
    if (activeView === "logs") refreshLogs();
  } catch (error) {
    if (sequence !== statusSequence) return;
    $("#task-state").textContent = "连接中断";
    $("#task-detail").textContent = error.message;
  } finally {
    if (sequence === statusSequence)
      refreshTimer = setTimeout(
        refreshStatus,
        document.hidden ? 30000 : running ? 1500 : 10000,
      );
  }
}

document.querySelectorAll("[data-run]").forEach((button) =>
  button.addEventListener("click", async () => {
    document.querySelectorAll("[data-run]").forEach((node) => {
      node.disabled = true;
    });
    try {
      const job = await api(button.dataset.run, { method: "POST" });
      submittedJob = job.id;
      notice("任务已开始，可在运行概览中查看结果。");
    } catch (error) {
      notice(error.message, true);
    }
    refreshStatus();
  }),
);

$("#config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('[type="submit"]');
  const config = Object.fromEntries(new FormData(event.currentTarget));
  config.UPDATE_ENABLED = $("#UPDATE_ENABLED").checked;
  button.disabled = true;
  try {
    const saved = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    $("#save-state").textContent = "配置已保存";
    notice(saved.message);
    refreshStatus();
  } catch (error) {
    $("#save-state").textContent = "保存失败，修改尚未生效";
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
});

async function refreshContainers() {
  const button = $("#refresh-containers");
  button.disabled = true;
  try {
    const { containers } = await api("/api/containers");
    const list = $("#container-list");
    list.replaceChildren();
    for (const container of containers) {
      const card = element("article", undefined, "panel");
      const heading = element("div", undefined, "container-card-header");
      heading.append(
        element("h3", container.name),
        element(
          "span",
          {
            running: "运行中",
            exited: "已停止",
            paused: "已暂停",
            unavailable: "无法访问",
          }[container.state] || container.state,
          "badge",
        ),
      );
      card.append(heading);
      if (container.error)
        card.append(element("p", container.error, "result-line"));
      if (container.hosts) {
        const preview = element("pre", container.hosts);
        preview.tabIndex = 0;
        card.append(preview);
      }
      list.append(card);
    }
    if (!containers.length)
      list.append(
        element("p", "尚未配置目标容器，可前往「更新配置」添加。", "empty"),
      );
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function refreshLogs() {
  try {
    $("#log-content").textContent = (
      await api(`/api/logs?lines=${$("#log-lines").value}`)
    ).logs;
  } catch (error) {
    notice(error.message, true);
  }
}

$("#refresh-containers").addEventListener("click", refreshContainers);
$("#refresh-logs").addEventListener("click", refreshLogs);
$("#log-lines").addEventListener("change", refreshLogs);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshStatus();
});
refreshHosts();
refreshStatus();
