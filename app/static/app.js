"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const csrf = $('meta[name="csrf-token"]').content;
let config = JSON.parse($("#initial-config").textContent);
let selected = new Set(entries(config.TARGET_CONTAINERS));
let inventory = [];
let inventoryConnected = null;
let inventoryPromise;
let lastInventoryRead = 0;
let activeView = null;
let activityView = "history";
let lastState;
let statusSequence = 0;
let pollTimer;
let toastTimer;
let dirty = false;
let formRevision = 0;
let saving = false;
let submitting = false;
let submittedJob = null;
let lastFinished = null;
let lastHistory = "";
let lastContainerContent = "";
let hostsContent = "";
const scrollPositions = {};
const viewNames = {
  overview: "总览",
  config: "更新规则",
  containers: "容器",
  logs: "活动记录",
};
const stateNames = {
  running: "运行中",
  exited: "已停止",
  created: "未启动",
  paused: "已暂停",
  restarting: "重启中",
  dead: "已停止",
  unavailable: "无法访问",
  unknown: "未找到",
};
const jobNames = {
  running: "运行中",
  success: "成功",
  partial: "部分成功",
  failed: "失败",
  legacy: "旧版记录",
};

function entries(value) {
  return [
    ...new Set(
      String(value || "")
        .split(/[\s,，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}

function make(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function icon(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.classList.add("icon");
  node.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  node.append(use);
  return node;
}

function text(selector, value) {
  const node = $(selector);
  const next = String(value ?? "—");
  if (node.textContent !== next) node.textContent = next;
}

function notice(message, error = false) {
  clearTimeout(toastTimer);
  text("#notice-message", message);
  $("#notice").classList.toggle("error", error);
  $("#notice").hidden = false;
  if (!error)
    toastTimer = setTimeout(() => {
      $("#notice").hidden = true;
    }, 5000);
}

function inlineError(selector, message) {
  const node = $(selector);
  if (message) node.textContent = message;
  node.hidden = !message;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 35000);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: { "X-CSRFToken": csrf, ...options.headers },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(
        data.error ||
          (response.status === 401
            ? "需要登录，请刷新页面后重试。"
            : "服务暂时无法响应，请稍后重试。"),
      );
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error("请求超时，请检查连接后重试。");
    if (error instanceof TypeError)
      throw new Error("无法连接更新器，请检查服务是否正在运行。");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function formatTime(value, full = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return String(value);
  return date.toLocaleString("zh-CN", {
    ...(full ? { year: "numeric" } : {}),
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(full ? { second: "2-digit" } : {}),
    hour12: false,
  });
}

function setTime(selector, value) {
  text(selector, formatTime(value));
  $(selector).title = value ? formatTime(value, true) : "尚无记录";
  if (value) $(selector).setAttribute("datetime", value);
  else $(selector).removeAttribute("datetime");
}

function intervalLabel(value) {
  const match = String(value).match(/^(\d+)([smhd]?)$/i);
  if (!match) return value;
  return `每 ${Number(match[1])} ${{ s: "秒", m: "分钟", h: "小时", d: "天", "": "小时" }[match[2].toLowerCase()]}`;
}

function friendlyError(value) {
  const message = String(value || "更新未完成，请查看日志后重试。");
  if (
    /no such container|container .*not found|container does not exist/i.test(
      message,
    )
  )
    return "找不到目标容器，请检查名称或重新选择。";
  if (/container .*not running|is not running/i.test(message))
    return "容器已停止，请启动后再更新。";
  if (/permission denied|read-only file system/i.test(message))
    return "无法写入 hosts，请检查目标容器的文件权限。";
  if (/timed out|TimeoutExpired/i.test(message))
    return "操作超时，原有配置仍保留。请检查网络或容器后重试。";
  if (/cannot connect to the docker daemon|docker.sock/i.test(message))
    return "无法连接 Docker，请检查服务与 Socket 挂载。";
  return message;
}

function jobLabel(status, label) {
  return make(
    "span",
    label || jobNames[status] || status,
    `status-label ${status}`,
  );
}

function closeMenu(restoreFocus = false) {
  document.body.classList.remove("menu-open");
  $("#nav-scrim").hidden = true;
  $("#open-menu").setAttribute("aria-expanded", "false");
  $("#main").inert = false;
  $(".topbar").inert = false;
  if (restoreFocus) $("#open-menu").focus();
}

function updatePageHeading() {
  const firstRun = !entries(config.CF_DOMAINS).length;
  text(
    "#page-title",
    activeView === "config" && firstRun ? "首次设置" : viewNames[activeView],
  );
  text("#breadcrumb", viewNames[activeView]);
  const descriptions = {
    overview: firstRun
      ? "添加目标容器和域名，开始自动更新。"
      : `${entries(config.CF_DOMAINS).length} 个域名${entries(config.TARGET_CONTAINERS).length ? `，更新到 ${entries(config.TARGET_CONTAINERS).length} 个容器` : "，仅生成 hosts 文件"}。`,
    config: firstRun
      ? "选择目标容器，添加域名，其余交给自动更新。"
      : "管理需要更新的容器、域名与更新方式。",
    containers: "检查所选容器的运行状态与实际 hosts 内容。",
    logs: "查看每次更新的结果，需要排查时再打开日志。",
  };
  text("#page-description", descriptions[activeView]);
  $("#overview-actions").hidden = activeView !== "overview";
  $("#update-menu").hidden = firstRun;
}

function showView(view, { focus = false, restore = true } = {}) {
  if (!viewNames[view]) view = "overview";
  if (activeView) scrollPositions[activeView] = window.scrollY;
  activeView = view;
  $$(".view").forEach((node) => {
    node.hidden = node.id !== `view-${view}`;
  });
  $$("[data-view]").forEach((node) => {
    const active = node.dataset.view === view;
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  closeMenu();
  $("#update-menu").open = false;
  updatePageHeading();
  if (view === "config") loadInventory();
  if (view === "containers") refreshContainers();
  if (view === "logs" && activityView === "logs") refreshLogs();
  if (restore)
    window.scrollTo({ top: scrollPositions[view] || 0, behavior: "instant" });
  if (focus) {
    $("#page-title").tabIndex = -1;
    $("#page-title").focus({ preventScroll: true });
  }
}

function navigate(view) {
  if (!viewNames[view]) return;
  if (location.hash !== `#${view}`) history.pushState({ view }, "", `#${view}`);
  showView(view, { focus: true });
}

$$("[data-view]").forEach((node) =>
  node.addEventListener("click", () => navigate(node.dataset.view)),
);
$$("[data-navigate]").forEach((node) =>
  node.addEventListener("click", () => navigate(node.dataset.navigate)),
);
window.addEventListener("popstate", () =>
  showView(location.hash.slice(1) || document.body.dataset.initialView),
);
window.addEventListener("hashchange", () => {
  const view = location.hash.slice(1);
  if (viewNames[view] && view !== activeView) showView(view);
});
$("#open-menu").addEventListener("click", () => {
  document.body.classList.add("menu-open");
  $("#nav-scrim").hidden = false;
  $("#open-menu").setAttribute("aria-expanded", "true");
  $("#main").inert = true;
  $(".topbar").inert = true;
  $("#close-menu").focus();
});
$("#close-menu").addEventListener("click", () => closeMenu(true));
$("#nav-scrim").addEventListener("click", () => closeMenu(true));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (document.body.classList.contains("menu-open")) closeMenu(true);
    $$("details.action-menu[open], details.inline-disclosure[open]").forEach(
      (node) => {
        node.open = false;
        node.querySelector("summary").focus();
      },
    );
  }
  if (event.key === "Tab" && document.body.classList.contains("menu-open")) {
    const targets = $$("a,button", $("#navigation")).filter(
      (node) => node.getClientRects().length,
    );
    const first = targets[0],
      last = targets[targets.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      last.focus();
      event.preventDefault();
    } else if (!event.shiftKey && document.activeElement === last) {
      first.focus();
      event.preventDefault();
    }
  }
});
document.addEventListener("click", (event) => {
  $$("details.action-menu[open], details.inline-disclosure[open]").forEach(
    (node) => {
      if (!node.contains(event.target)) node.open = false;
    },
  );
});
window.matchMedia("(min-width: 1101px)").addEventListener("change", (event) => {
  if (event.matches) closeMenu();
});
$("#dismiss-notice").addEventListener("click", () => {
  $("#notice").hidden = true;
});

function updateSelectionSummary() {
  const exportOnly = $("#export-only").checked;
  const domainCount = entries($("#CF_DOMAINS").value).length;
  const targetCount = exportOnly ? 0 : selected.size;
  text("#selected-count", exportOnly ? "仅生成文件" : `已选 ${targetCount} 个`);
  text(
    "#domain-feedback",
    domainCount ? `已添加 ${domainCount} 个域名` : "支持换行或逗号分隔",
  );
  text(
    "#scope-preview",
    domainCount
      ? `${domainCount} 个域名 → ${targetCount ? `${targetCount} 个容器` : exportOnly ? "hosts 文件" : "请选择容器"}`
      : "选择容器并填写域名",
  );
}

function renderPicker() {
  const focused = $("input[data-container]:focus");
  const focusedName = focused?.dataset.container;
  const list = $("#container-picker");
  const query = $("#container-search").value.trim().toLowerCase();
  const exportOnly = $("#export-only").checked;
  const items = [...inventory];
  for (const name of selected) {
    if (!items.some((item) => item.name === name))
      items.push({
        name,
        image: "手动添加的容器",
        state: inventoryConnected ? "unknown" : "manual",
      });
  }
  list.replaceChildren();
  const visible = items.filter((item) =>
    item.name.toLowerCase().includes(query),
  );
  for (const item of visible) {
    const choice = make(
      "label",
      undefined,
      `container-choice${selected.has(item.name) ? " selected" : ""}`,
    );
    const checkbox = make("input");
    checkbox.type = "checkbox";
    checkbox.dataset.container = item.name;
    checkbox.checked = selected.has(item.name);
    checkbox.disabled =
      exportOnly ||
      (item.state !== "running" &&
        item.state !== "manual" &&
        !checkbox.checked);
    const description = make("span", undefined, "choice-description");
    description.append(
      make("span", item.name, "container-name"),
      make("span", item.image || "镜像信息不可用", "container-image"),
    );
    const state =
      item.state === "manual"
        ? "手动添加"
        : stateNames[item.state] || item.state;
    choice.append(
      checkbox,
      description,
      make("span", state, `badge${item.state === "running" ? "" : " neutral"}`),
    );
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selected.add(item.name);
      else selected.delete(item.name);
      choice.classList.toggle("selected", checkbox.checked);
      $("#TARGET_CONTAINERS").value = [...selected].join("\n");
      inlineError("#target-error", "");
      updateSelectionSummary();
    });
    list.append(choice);
  }
  if (!visible.length)
    list.append(
      make(
        "p",
        query
          ? "没有匹配的容器，试试其他名称。"
          : inventoryConnected === false
            ? "可以重试读取，或在下方手动填写名称。"
            : "还没有 Docker 容器，启动目标容器后刷新即可。",
        "empty-row",
      ),
    );
  if (focusedName)
    $$("input[data-container]", list)
      .find((node) => node.dataset.container === focusedName)
      ?.focus({ preventScroll: true });
  $("#TARGET_CONTAINERS").disabled = exportOnly;
  updateSelectionSummary();
}

async function loadInventory() {
  if (inventoryPromise) return inventoryPromise;
  $("#refresh-picker").disabled = true;
  inventoryPromise = (async () => {
    try {
      const data = await api("/api/containers/available");
      inventory = data.containers;
      inventoryConnected = true;
      inlineError("#picker-error", "");
      $("#docker-connection").classList.add("connected");
      $("#docker-connection span:last-child").textContent = "Docker 已连接";
    } catch (error) {
      inventoryConnected = false;
      inlineError("#picker-error", error.message);
      const retry = make("button", "重新读取", "text-button");
      retry.type = "button";
      retry.addEventListener("click", () => loadInventory());
      $("#picker-error").append(retry);
      $("#manual-targets").open = true;
      $("#docker-connection").classList.remove("connected");
      $("#docker-connection span:last-child").textContent = "Docker 连接待检查";
    } finally {
      lastInventoryRead = Date.now();
      renderPicker();
      renderTargets();
      $("#refresh-picker").disabled = false;
      inventoryPromise = null;
    }
  })();
  return inventoryPromise;
}

$("#refresh-picker").addEventListener("click", loadInventory);
$("#container-search").addEventListener("input", renderPicker);
$("#TARGET_CONTAINERS").addEventListener("input", () => {
  selected = new Set(entries($("#TARGET_CONTAINERS").value));
  renderPicker();
});
$("#export-only").addEventListener("change", renderPicker);

function updateMode() {
  const fixed = $('input[name="ip-mode"]:checked').value === "fixed";
  $("#preferred-field").hidden = !fixed;
  $("#PREFERRED_IP").required = fixed;
  for (const id of ["IP_COUNT", "SPEED_TEST_TIMEOUT", "SPEED_TEST_ARGS"])
    $("#" + id).closest(".field").hidden = fixed;
}

function updateSchedule() {
  const enabled = $("#UPDATE_ENABLED").checked;
  $("#interval-preset").disabled = !enabled;
  text(
    "#schedule-help",
    enabled
      ? "启动后及每个间隔自动执行，随时也能手动更新。"
      : "自动更新已暂停；仍可随时手动更新。",
  );
  const preset = $("#interval-preset").value;
  $("#custom-interval").hidden = preset !== "custom";
  if (preset !== "custom") $("#UPDATE_INTERVAL").value = preset;
}

$$("input[name=ip-mode]").forEach((node) =>
  node.addEventListener("change", updateMode),
);
$("#UPDATE_ENABLED").addEventListener("change", updateSchedule);
$("#interval-preset").addEventListener("change", updateSchedule);
$("#CF_DOMAINS").addEventListener("input", () => {
  inlineError("#domain-error", "");
  updateSelectionSummary();
});
$("#CF_DOMAINS").addEventListener("blur", () => {
  let converted = false;
  const domains = entries($("#CF_DOMAINS").value).map((value) => {
    if (/^https?:\/\//i.test(value)) {
      try {
        converted = true;
        return new URL(value).hostname;
      } catch {
        return value;
      }
    }
    return value;
  });
  if (converted) {
    $("#CF_DOMAINS").value = [...new Set(domains)].join("\n");
    text("#domain-feedback", `已从链接提取 ${domains.length} 个域名`);
    updateSelectionSummary();
  }
});

function markDirty(event) {
  if (event?.target.id === "container-search") return;
  dirty = true;
  formRevision += 1;
  text("#save-state", "有未保存的修改");
}
$("#config-form").addEventListener("input", markDirty);
$("#config-form").addEventListener("change", markDirty);
window.addEventListener("beforeunload", (event) => {
  if (dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

function fieldError(selector, message) {
  const field = $(selector);
  if (field) field.setAttribute("aria-invalid", "true");
  const errorIds = {
    "#TARGET_CONTAINERS": "#target-error",
    "#CF_DOMAINS": "#domain-error",
    "#UPDATE_INTERVAL": "#interval-error",
    "#PREFERRED_IP": "#preferred-error",
    "#IP_COUNT": "#count-error",
    "#SPEED_TEST_TIMEOUT": "#timeout-error",
    "#SPEED_TEST_ARGS": "#args-error",
  };
  inlineError(errorIds[selector] || "#config-error", message);
  if (selector === "#TARGET_CONTAINERS" && message.startsWith("请至少")) {
    const choice = $("input[data-container]:not(:disabled)");
    if (choice) {
      choice.focus();
      return;
    }
  }
  if (field) {
    for (
      let parent = field.parentElement;
      parent;
      parent = parent.parentElement
    )
      if (parent.tagName === "DETAILS") parent.open = true;
    field.focus();
  }
}

function clearFieldErrors() {
  $$(".field-error").forEach((node) => {
    node.hidden = true;
  });
  $$("[aria-invalid]").forEach((node) => node.removeAttribute("aria-invalid"));
}

function formValues() {
  const fixed = $('input[name="ip-mode"]:checked').value === "fixed";
  return {
    TARGET_CONTAINERS: $("#export-only").checked ? "" : [...selected].join(","),
    CF_DOMAINS: entries($("#CF_DOMAINS").value).join(","),
    PREFERRED_IP:
      $('input[name="ip-mode"]:checked').value === "fixed"
        ? $("#PREFERRED_IP").value.trim()
        : "",
    UPDATE_INTERVAL: $("#UPDATE_INTERVAL").value.trim(),
    UPDATE_ENABLED: $("#UPDATE_ENABLED").checked,
    IP_COUNT: fixed ? String(config.IP_COUNT) : $("#IP_COUNT").value,
    SPEED_TEST_TIMEOUT: fixed
      ? String(config.SPEED_TEST_TIMEOUT)
      : $("#SPEED_TEST_TIMEOUT").value,
    SPEED_TEST_ARGS: fixed
      ? config.SPEED_TEST_ARGS
      : $("#SPEED_TEST_ARGS").value.trim(),
  };
}

function validate(values) {
  if (!values.TARGET_CONTAINERS && !$("#export-only").checked) {
    fieldError(
      "#TARGET_CONTAINERS",
      "请至少选择一个目标容器；仅需导出时可勾选「只生成 hosts 文件」。",
    );
    return false;
  }
  if (!values.CF_DOMAINS) {
    fieldError("#CF_DOMAINS", "请填写至少一个域名。");
    return false;
  }
  if (
    $('input[name="ip-mode"]:checked').value === "fixed" &&
    !values.PREFERRED_IP
  ) {
    fieldError("#PREFERRED_IP", "请输入固定 IP，或切换为自动优选。");
    return false;
  }
  for (const [key, limit, label] of [
    ["IP_COUNT", 20, "IP 数量"],
    ["SPEED_TEST_TIMEOUT", 86400, "测速超时秒数"],
  ]) {
    if (
      !/^\d+$/.test(values[key]) ||
      Number(values[key]) < 1 ||
      Number(values[key]) > limit
    ) {
      fieldError(`#${key}`, `${label}应为 1–${limit} 的整数。`);
      return false;
    }
  }
  return true;
}

function handleConfigError(error) {
  const message = error.message;
  const field = /容器/.test(message)
    ? "#TARGET_CONTAINERS"
    : /域名/.test(message)
      ? "#CF_DOMAINS"
      : /预设 IP|固定 IP/.test(message)
        ? "#PREFERRED_IP"
        : /更新间隔/.test(message)
          ? "#UPDATE_INTERVAL"
          : /IP 数量/.test(message)
            ? "#IP_COUNT"
            : /超时秒数/.test(message)
              ? "#SPEED_TEST_TIMEOUT"
              : /测速参数|引号| -o/.test(message)
                ? "#SPEED_TEST_ARGS"
                : null;
  if (field) fieldError(field, message);
  else inlineError("#config-error", message);
}

function syncControls() {
  const running = Boolean(lastState?.running);
  const configured = entries(config.CF_DOMAINS).length > 0;
  $$("[data-run]").forEach((node) => {
    node.disabled = running || submitting;
    node.title = running ? "已有任务运行，完成后可以再次更新" : "";
  });
  text(
    "#run-speedtest span",
    !configured
      ? "开始设置"
      : running
        ? "更新中…"
        : lastState?.job?.status === "failed"
          ? "重试更新"
          : "立即更新",
  );
  $$("#config-form button[type=submit]").forEach((node) => {
    node.disabled = saving || (node.value === "run" && (running || submitting));
  });
  $("#save-and-run").title = running ? "已有任务运行，可先仅保存配置" : "";
}

async function startJob(path = "/run_speedtest") {
  if (!entries(config.CF_DOMAINS).length) {
    navigate("config");
    return;
  }
  submitting = true;
  syncControls();
  try {
    const job = await api(path, { method: "POST" });
    submittedJob = job.id;
    $("#update-menu").open = false;
    navigate("overview");
    window.scrollTo({ top: 0, behavior: "instant" });
    notice(
      config.PREFERRED_IP
        ? "正在使用固定 IP 更新容器。"
        : path === "/update_hosts"
          ? "正在沿用已有 IP 更新。"
          : "已开始优选 IP，完成后自动更新容器。",
    );
  } catch (error) {
    notice(
      error.status === 409 ? "已有任务运行，完成后再更新即可。" : error.message,
      error.status !== 409,
    );
  } finally {
    submitting = false;
    await refreshStatus();
  }
}

$$("[data-run]").forEach((node) =>
  node.addEventListener("click", () => startJob(node.dataset.run)),
);
$("#config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFieldErrors();
  const values = formValues();
  if (!validate(values)) return;
  const run = event.submitter?.value === "run";
  const submittedRevision = formRevision;
  saving = true;
  syncControls();
  try {
    const saved = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    config = saved.config;
    dirty = formRevision !== submittedRevision;
    if (!dirty) {
      $("#CF_DOMAINS").value = entries(config.CF_DOMAINS).join("\n");
      for (const key of [
        "UPDATE_INTERVAL",
        "PREFERRED_IP",
        "IP_COUNT",
        "SPEED_TEST_TIMEOUT",
        "SPEED_TEST_ARGS",
      ])
        $("#" + key).value = String(config[key]);
      updateSelectionSummary();
    }
    text(
      "#save-state",
      dirty
        ? "已保存提交时的规则，当前输入仍有未保存的修改"
        : "已保存，后续任务使用新规则",
    );
    updatePageHeading();
    renderScope();
    renderTargets();
    if (run) await startJob();
    else {
      notice("更新规则已保存。");
      await refreshStatus();
    }
  } catch (error) {
    handleConfigError(error);
    text("#save-state", "保存未完成，修改仍保留在页面中");
  } finally {
    saving = false;
    syncControls();
  }
});

function renderScope() {
  const domains = entries(config.CF_DOMAINS),
    targets = entries(config.TARGET_CONTAINERS);
  text("#route-domains", `${domains.length} 个`);
  text("#route-domain-detail", domains.join("、") || "尚未配置");
  $("#route-domain-detail").title = domains.join("、");
  text("#route-ip", config.PREFERRED_IP || "自动优选");
  $("#route-ip").classList.toggle("address", Boolean(config.PREFERRED_IP));
  text(
    "#route-ip-detail",
    config.PREFERRED_IP ? "固定 IP，跳过测速" : "按测速结果选择",
  );
  text("#route-containers", targets.length ? `${targets.length} 个` : "仅导出");
  text("#route-container-detail", targets.join("、") || "生成 hosts 文件");
  $("#route-container-detail").title = targets.join("、");
  text(
    "#schedule-caption",
    config.UPDATE_ENABLED
      ? `${intervalLabel(config.UPDATE_INTERVAL)}自动更新`
      : "自动更新已暂停",
  );
}

function renderTargets() {
  const targets = entries(config.TARGET_CONTAINERS);
  const results = new Map(
    (lastState?.job?.containers || []).map((item) => [item.name, item]),
  );
  text("#target-count", `${targets.length} 个已选`);
  const list = $("#target-summary");
  list.replaceChildren();
  for (const name of targets.slice(0, 4)) {
    const item = inventory.find((item) => item.name === name);
    const row = make("div", undefined, "target-row");
    const identity = make("div");
    identity.append(make("strong", name));
    identity.append(
      make(
        "span",
        item
          ? stateNames[item.state] || item.state
          : inventoryConnected
            ? "未找到容器"
            : "等待连接",
        "target-state",
      ),
    );
    const result = results.get(name);
    row.append(
      identity,
      jobLabel(
        result ? (result.success ? "success" : "failed") : "legacy",
        result ? (result.success ? "已更新" : "未更新") : "尚未更新",
      ),
    );
    list.append(row);
  }
  if (!targets.length)
    list.append(make("p", "当前仅生成 hosts 文件，不写入容器。", "empty-row"));
  text(
    "#target-footnote",
    targets.length > 4
      ? `另有 ${targets.length - 4} 个容器，可在「容器」中查看。`
      : "结果来自最近一次任务；容器内容可单独查看。",
  );
}

function renderJob(state) {
  const job = state.job;
  let title = "可以开始更新了",
    description = "规则已保存，点击「立即更新」执行第一次任务。";
  if (!state.configured) {
    title = "等待完成设置";
    description = "选择容器并添加域名，即可开始自动更新。";
  } else if (state.running) {
    title = "正在更新";
    description = `${job.message}，任务会在后台继续。`;
  } else if (job) {
    const outcomes = job.containers || [];
    const successful = outcomes.filter((item) => item.success).length;
    if (job.status === "success") {
      title = outcomes.length ? "更新完成" : "hosts 已生成";
      description = outcomes.length
        ? `${successful} 个容器已更新，${Object.keys(job.ips || {}).length} 个域名已写入。`
        : "已生成域名映射，本次未写入容器。";
    } else if (job.status === "partial") {
      title = "部分容器未更新";
      description = `${successful} 个成功，${outcomes.length - successful} 个未完成。检查下方原因后重试。`;
    } else {
      title = "本次更新未完成";
      description = friendlyError(job.message);
    }
  }
  text("#update-title", title);
  text("#task-detail", description);
  const status = state.running ? "running" : job?.status || "idle";
  $("#task-symbol").className = `task-symbol ${status}`;
  $("#task-symbol use").setAttribute(
    "href",
    `#i-${status === "running" ? "refresh" : status === "success" ? "check" : "info"}`,
  );
  setTime("#last-success", state.last_success);
  setTime("#next-run", state.next_run);
  const failures = (job?.containers || []).filter((item) => !item.success);
  const results = $("#job-results");
  const fingerprint = JSON.stringify(failures);
  if (results.dataset.content !== fingerprint) {
    results.dataset.content = fingerprint;
    results.replaceChildren();
    for (const item of failures) {
      const row = make("div", undefined, "job-result");
      row.append(
        make("span", item.name, "result-name"),
        make("span", friendlyError(item.error)),
      );
      results.append(row);
    }
  }
  results.hidden = !failures.length;
  syncControls();
}

function historyList(root, records) {
  const focusedId = root.contains(document.activeElement)
    ? document.activeElement.closest(".history-item")?.dataset.id
    : null;
  const open = new Set(
    $$("details[open]", root).map((node) => node.dataset.id),
  );
  root.replaceChildren();
  for (const [index, record] of records.entries()) {
    const detail = make("details", undefined, "history-item");
    detail.dataset.id = record.id || `${record.timestamp}-${index}`;
    detail.open = open.has(detail.dataset.id);
    const summary = make("summary");
    const title = make("div");
    const source =
      { manual: "手动更新", scheduled: "定时更新", startup: "启动更新" }[
        record.source
      ] || (record.is_scheduled ? "定时更新" : "手动更新");
    title.append(make("span", source, "event-title"));
    title.append(
      make(
        "span",
        record.message ? friendlyError(record.message) : "旧版执行记录",
        "event-caption",
      ),
    );
    const when = make("time", formatTime(record.timestamp));
    if (record.timestamp) {
      when.dateTime = record.timestamp;
      when.title = formatTime(record.timestamp, true);
    }
    summary.append(
      title,
      jobLabel(record.status || "legacy"),
      when,
      icon("chevron"),
    );
    const content = make("div", undefined, "history-detail");
    if (record.duration !== undefined)
      content.append(make("p", `耗时 ${record.duration} 秒`));
    for (const [domain, ips] of Object.entries(record.ips || {}))
      content.append(
        make(
          "p",
          `${domain} → ${Array.isArray(ips) ? ips.join("、") : ips}`,
          "mono",
        ),
      );
    for (const item of record.containers || []) {
      content.append(
        make(
          "p",
          `${item.name}：${item.success ? "已更新" : friendlyError(item.error)}`,
        ),
      );
      if (item.error) {
        const raw = make("details");
        raw.append(make("summary", "原始错误"), make("pre", item.error));
        content.append(raw);
      }
    }
    detail.append(summary, content);
    root.append(detail);
  }
  if (!records.length)
    root.append(
      make("p", "还没有执行记录。完成首次更新后会显示在这里。", "empty-row"),
    );
  if (focusedId)
    $$(".history-item", root)
      .find((node) => node.dataset.id === focusedId)
      ?.querySelector("summary")
      ?.focus({ preventScroll: true });
}

function renderHistory(history) {
  const fingerprint = JSON.stringify(history);
  if (fingerprint === lastHistory) return;
  lastHistory = fingerprint;
  historyList($("#recent-history"), history.slice(0, 3));
  historyList($("#history-body"), history);
  text(
    "#recent-count",
    history.length ? `最近 ${Math.min(history.length, 3)} 次` : "",
  );
  text("#history-count", history.length);
}

async function refreshHosts() {
  try {
    const { hosts } = await api("/api/hosts");
    hostsContent = hosts;
    text("#hosts-preview", hosts || "尚未生成 hosts");
    const mappings = new Map();
    for (const line of hosts.split("\n")) {
      const parts = line.split("#", 1)[0].trim().split(/\s+/);
      if (parts.length < 2) continue;
      if (!mappings.has(parts[1])) mappings.set(parts[1], []);
      mappings.get(parts[1]).push(parts[0]);
    }
    const list = $("#mapping-body");
    list.replaceChildren();
    for (const [domain, ips] of mappings) {
      const row = make("div", undefined, "mapping-row");
      const values = make("div", undefined, "ip-values");
      for (const ip of ips) values.append(make("span", ip));
      row.append(make("span", domain, "domain"), values);
      list.append(row);
    }
    if (!mappings.size)
      list.append(
        make("p", "首次更新完成后，域名与 IP 会显示在这里。", "empty-row"),
      );
    text("#mapping-count", `${mappings.size} 个域名`);
  } catch (error) {
    $("#mapping-body").replaceChildren(make("p", error.message, "empty-row"));
  }
}

$("#copy-hosts").addEventListener("click", async () => {
  try {
    if (!hostsContent) {
      notice("尚未生成 hosts，请先执行一次更新。");
      return;
    }
    if (!navigator.clipboard) throw new Error("请选中 hosts 内容后手动复制。");
    await navigator.clipboard.writeText(hostsContent);
    notice("hosts 已复制。");
  } catch {
    notice("浏览器未允许复制，请选中内容后手动复制。", true);
  }
});

async function refreshStatus() {
  clearTimeout(pollTimer);
  const sequence = ++statusSequence;
  let running = false;
  try {
    const state = await api("/api/status");
    if (sequence !== statusSequence) return;
    lastState = state;
    running = state.running;
    inlineError("#overview-error", "");
    renderJob(state);
    renderHistory(state.history);
    renderTargets();
    if (!document.hidden && Date.now() - lastInventoryRead > 30000)
      loadInventory();
    const finished = state.job?.finished_at ? state.job.id : null;
    if (finished && finished !== lastFinished) {
      lastFinished = finished;
      refreshHosts();
      if (activeView === "containers") refreshContainers();
    }
    if (finished && finished === submittedJob) {
      notice(
        state.job.status === "success"
          ? state.job.message
          : "本次更新有未完成项，请查看总览中的原因。",
        state.job.status !== "success",
      );
      submittedJob = null;
    }
    if (activeView === "logs" && activityView === "logs") refreshLogs();
  } catch (error) {
    if (sequence !== statusSequence) return;
    inlineError("#overview-error", `${error.message} 页面保留上次读取的结果。`);
    const retry = make("button", "重试", "text-button");
    retry.addEventListener("click", refreshStatus);
    $("#overview-error").append(retry);
  } finally {
    if (sequence === statusSequence)
      pollTimer = setTimeout(
        refreshStatus,
        document.hidden ? 30000 : running ? 1500 : 10000,
      );
  }
}

async function refreshContainers() {
  const button = $("#refresh-containers");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const { containers } = await api("/api/containers");
    inlineError("#container-error", "");
    text(
      "#container-view-summary",
      `${containers.length} 个目标容器 · 只读查看，不会修改 hosts`,
    );
    const signature = JSON.stringify(containers);
    if (signature === lastContainerContent) return;
    lastContainerContent = signature;
    const list = $("#container-list");
    const open = new Set(
      $$("details[open]", list).map((node) => node.dataset.name),
    );
    list.replaceChildren();
    for (const item of containers) {
      const card = make("article", undefined, "container-detail");
      const header = make("div", undefined, "container-detail-header");
      header.append(
        make("h2", item.name),
        make("span", stateNames[item.state] || item.state, "badge"),
      );
      card.append(header);
      if (item.error)
        card.append(make("p", friendlyError(item.error), "error-description"));
      if (item.hosts) {
        const detail = make("details");
        detail.dataset.name = item.name;
        detail.open = open.has(item.name);
        const preview = make("pre", item.hosts);
        preview.tabIndex = 0;
        detail.append(make("summary", "查看实际 hosts"), preview);
        card.append(detail);
      } else if (!item.error)
        card.append(
          make("p", "容器启动后才能读取实际 hosts。", "state-caption"),
        );
      list.append(card);
    }
    if (!containers.length) {
      const empty = make("div", undefined, "empty-row");
      empty.append(make("p", "当前未选择目标容器。"));
      const action = make("button", "前往选择容器", "text-button");
      action.addEventListener("click", () => navigate("config"));
      empty.append(action);
      list.append(empty);
    }
  } catch (error) {
    inlineError("#container-error", error.message);
  } finally {
    button.disabled = false;
  }
}

async function refreshLogs() {
  const button = $("#refresh-logs");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const { logs } = await api(`/api/logs?lines=${$("#log-lines").value}`);
    inlineError("#log-error", "");
    const output = $("#log-content");
    const atBottom =
      output.scrollHeight - output.scrollTop - output.clientHeight < 30;
    if (output.textContent !== logs) {
      output.textContent = logs;
      if (atBottom) output.scrollTop = output.scrollHeight;
    }
  } catch (error) {
    inlineError("#log-error", error.message);
  } finally {
    button.disabled = false;
  }
}

$$("[data-activity]").forEach((button) =>
  button.addEventListener("click", () => {
    activityView = button.dataset.activity;
    $$("[data-activity]").forEach((node) => {
      const active = node === button;
      node.classList.toggle("active", active);
      node.setAttribute("aria-pressed", String(active));
    });
    $("#activity-history").hidden = activityView !== "history";
    $("#activity-logs").hidden = activityView !== "logs";
    if (activityView === "logs") refreshLogs();
  }),
);
$("#refresh-containers").addEventListener("click", refreshContainers);
$("#refresh-logs").addEventListener("click", refreshLogs);
$("#log-lines").addEventListener("change", refreshLogs);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshStatus();
});

const presetExists = $$("#interval-preset option").some(
  (option) => option.value === config.UPDATE_INTERVAL,
);
$("#interval-preset").value = presetExists ? config.UPDATE_INTERVAL : "custom";
$("#export-only").checked =
  entries(config.CF_DOMAINS).length > 0 && selected.size === 0;
if ($("#export-only").checked) $("#manual-targets").open = true;
if (config.PREFERRED_IP) $("#advanced-options").open = true;
updateMode();
updateSchedule();
updateSelectionSummary();
renderScope();
showView(
  viewNames[location.hash.slice(1)]
    ? location.hash.slice(1)
    : document.body.dataset.initialView,
  { restore: false },
);
loadInventory();
refreshHosts();
refreshStatus();
