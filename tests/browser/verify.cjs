/* Creates its own local server and disposable containers. No production data is used. */
const { chromium } = require("playwright");
const AxeBuilder = require("@axe-core/playwright").default;
const { spawn, execFileSync } = require("node:child_process");
const { promisify } = require("node:util");
const execFile = promisify(require("node:child_process").execFile);
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const assert = require("node:assert/strict");

if (process.env.RUN_DOCKER_TESTS !== "1")
  throw new Error(
    "Set RUN_DOCKER_TESTS=1 to allow disposable local Docker containers.",
  );
const root = path.resolve(__dirname, "../..");
const artifacts = path.resolve(
  process.env.ARTIFACT_DIR || path.join(root, ".taste-skill/browser"),
);
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "cfhu-browser-"));
const prefix = `cfhu-browser-${process.pid}`;
const names = [`${prefix}-media`, `${prefix}-tracker`];
const created = [];
const dockerEnv = { ...process.env };
for (const key of [
  "DOCKER_HOST",
  "DOCKER_CONTEXT",
  "DOCKER_TLS",
  "DOCKER_TLS_VERIFY",
  "DOCKER_CERT_PATH",
])
  delete dockerEnv[key];
function docker(...args) {
  return execFileSync(
    "docker",
    ["--host=unix:///var/run/docker.sock", ...args],
    {
      env: dockerEnv,
      encoding: "utf8",
      timeout: 120000,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
}
const checks = [];
let browser, server;
let serverLog = "";
fs.mkdirSync(artifacts, { recursive: true });

function record(name) {
  checks.push(name);
  process.stdout.write(`PASS ${name}\n`);
}
async function freePort() {
  const socket = net.createServer();
  await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
  const port = socket.address().port;
  await new Promise((resolve) => socket.close(resolve));
  return port;
}
async function ready(url) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${url}/healthz`)).ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Server not ready. ${serverLog}`);
}
async function navigate(page, view) {
  if (await page.locator("#open-menu").isVisible())
    await page.locator("#open-menu").click();
  await page.locator(`[data-view="${view}"]`).click();
}
async function save(page, action = "run") {
  await page.locator(`#config-form button[value="${action}"]`).click();
}
async function jobFinished(page, expected) {
  await page.waitForFunction(
    (status) => document.querySelector("#update-title").textContent === status,
    expected,
  );
}

(async () => {
  try {
    for (const name of names) {
      docker(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "alpine:3.22",
        "sleep",
        "600",
      );
      created.push(name);
    }
    const port = await freePort();
    const url = `http://127.0.0.1:${port}`;
    const env = {
      ...dockerEnv,
      DATA_DIR: temporary,
      WEB_HOST: "127.0.0.1",
      WEB_PORT: String(port),
      WEB_PASSWORD: "",
      DOCKER_HOST: "unix:///var/run/docker.sock",
    };
    for (const key of [
      "CF_DOMAINS",
      "TARGET_CONTAINERS",
      "PREFERRED_IP",
      "UPDATE_INTERVAL",
      "UPDATE_ENABLED",
      "IP_COUNT",
      "SPEED_TEST_ARGS",
    ])
      delete env[key];
    const python = process.env.PYTHON || path.join(root, ".venv/bin/python");
    server = spawn(python, ["-m", "app.main"], {
      cwd: root,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    for (const stream of [server.stdout, server.stderr])
      stream.on("data", (data) => {
        serverLog = (serverLog + data).slice(-30000);
      });
    await ready(url);
    browser = await chromium.launch({
      ...(process.env.CHROME_PATH
        ? { executablePath: process.env.CHROME_PATH }
        : {}),
      args: ["--no-sandbox"],
    });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      locale: "zh-CN",
      timezoneId: "Asia/Singapore",
    });
    const page = await context.newPage();
    await context.grantPermissions(["clipboard-read", "clipboard-write"], {
      origin: url,
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(url, { waitUntil: "networkidle" });
    await page.locator(`input[data-container="${names[0]}"]`).waitFor();
    assert.equal(await page.locator("#page-title").textContent(), "首次设置");
    assert.equal(
      await page.locator("#advanced-options").getAttribute("open"),
      null,
    );
    await page.screenshot({
      path: path.join(artifacts, "onboarding.png"),
      fullPage: true,
    });
    await save(page);
    await page.locator("#target-error").waitFor({ state: "visible" });
    assert.equal(
      await page.locator("#manual-targets").getAttribute("open"),
      null,
    );
    await page.locator(`input[data-container="${names[0]}"]`).check();
    await page.locator(`input[data-container="${names[1]}"]`).check();
    assert.equal(
      await page
        .locator(`input[data-container="${names[1]}"]`)
        .evaluate((node) => node === document.activeElement),
      true,
    );
    await save(page);
    await page.locator("#domain-error").waitFor({ state: "visible" });
    assert.equal(
      await page
        .locator("#CF_DOMAINS")
        .evaluate((node) => node === document.activeElement),
      true,
    );
    record("first run, container discovery, inline validation and focus");

    await page
      .locator("#CF_DOMAINS")
      .fill(
        "https://tracker.pterclub.com/announce\naudiences.me\nqingwapt.com",
      );
    await page.locator("#CF_DOMAINS").blur();
    assert.equal(
      await page.locator("#CF_DOMAINS").inputValue(),
      "tracker.pterclub.com\naudiences.me\nqingwapt.com",
    );
    await page.locator("#advanced-options > summary").click();
    await page.locator('input[name="ip-mode"][value="fixed"]').check();
    await page.locator("#PREFERRED_IP").fill("1.1.1.1");
    await save(page);
    await jobFinished(page, "更新完成");
    await page.waitForFunction(
      () =>
        document.querySelectorAll("#mapping-body .mapping-row").length === 3,
    );
    assert.match(
      docker("exec", names[0], "cat", "/etc/hosts"),
      /1\.1\.1\.1 tracker\.pterclub\.com/,
    );
    assert.match(docker("exec", names[1], "cat", "/etc/hosts"), /127\.0\.0\.1/);
    record(
      "paste URL, one-action save and run, real Docker hosts, preserved localhost",
    );

    await navigate(page, "config");
    await page.locator("#PREFERRED_IP").fill("not-an-ip");
    await save(page);
    await page.locator("#preferred-error").waitFor({ state: "visible" });
    assert.equal(
      await page
        .locator("#PREFERRED_IP")
        .evaluate((node) => node === document.activeElement),
      true,
    );
    assert.equal(
      (await (await context.request.get(`${url}/api/config`)).json())
        .PREFERRED_IP,
      "1.1.1.1",
    );
    await page.locator("#PREFERRED_IP").fill("2606:4700::1111");
    await save(page);
    await jobFinished(page, "更新完成");
    await page.waitForFunction(() =>
      document
        .querySelector("#mapping-body")
        .textContent.includes("2606:4700::1111"),
    );
    record("invalid config preserves saved settings, IPv6 update");

    await navigate(page, "containers");
    await page.locator("#container-list .container-detail").first().waitFor();
    await page.locator("#container-list details > summary").first().click();
    assert.match(
      await page.locator("#container-list pre").first().textContent(),
      /2606:4700::1111 tracker\.pterclub\.com/,
    );
    await navigate(page, "logs");
    await page.locator('[data-activity="logs"]').click();
    await page.waitForFunction(() =>
      document.querySelector("#log-content").textContent.includes("任务"),
    );
    await page.locator('[data-activity="history"]').click();
    await page.locator("#history-body .history-item > summary").first().click();
    const historyId = await page
      .locator("#history-body .history-item")
      .first()
      .getAttribute("data-id");
    await Promise.all([
      page.waitForResponse((response) =>
        response.url().endsWith("/api/status"),
      ),
      page.evaluate(() =>
        document.dispatchEvent(new Event("visibilitychange")),
      ),
    ]);
    assert.equal(
      await page
        .locator(`#history-body .history-item[data-id="${historyId}"]`)
        .getAttribute("open"),
      "",
    );
    record("actual hosts, logs, history disclosure persists during refresh");

    // All metadata views use real data; failures below are controlled browser transport fixtures.
    const accessibility = [];
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({
        width,
        height: width === 768 ? 1024 : width === 390 ? 844 : 900,
      });
      for (const view of ["overview", "config", "containers", "logs"]) {
        await navigate(page, view);
        if (view === "overview") {
          await page.locator(".inline-disclosure > summary").click();
          if (width === 1440) {
            await page.locator("#copy-hosts").click();
            assert.match(
              await page.evaluate(() => navigator.clipboard.readText()),
              /2606:4700::1111 tracker\.pterclub\.com/,
            );
          }
          assert.equal(
            await page.evaluate(
              () => document.documentElement.scrollWidth > innerWidth,
            ),
            false,
            `Hosts preview overflow at ${width}`,
          );
          await page.keyboard.press("Escape");
          assert.equal(
            await page.locator(".inline-disclosure").getAttribute("open"),
            null,
          );
          await page.locator("#update-menu > summary").click();
          await page.keyboard.press("Escape");
          assert.equal(
            await page.locator("#update-menu").getAttribute("open"),
            null,
          );
        }
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          `Overflow at ${width}/${view}`,
        );
        const result = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        accessibility.push({
          width,
          view,
          violations: result.violations.map((item) => ({
            id: item.id,
            impact: item.impact,
            nodes: item.nodes.map((node) => node.target),
          })),
        });
        if (view === "overview" || view === "config") {
          await page.evaluate(() => {
            document.activeElement?.blur();
            window.scrollTo(0, 0);
          });
          if (await page.locator("#dismiss-notice").isVisible())
            await page.locator("#dismiss-notice").click();
          await page.screenshot({
            path: path.join(artifacts, `${view}-${width}.png`),
            fullPage: true,
          });
        }
      }
    }
    fs.writeFileSync(
      path.join(artifacts, "accessibility.json"),
      JSON.stringify(accessibility, null, 2),
    );
    assert.equal(
      accessibility.reduce((sum, item) => sum + item.violations.length, 0),
      0,
      JSON.stringify(accessibility),
    );
    record("1440/768/390px, all views, no page overflow, axe WCAG A/AA");

    await page.setViewportSize({ width: 1440, height: 900 });
    await navigate(page, "config");
    await page.locator("#manual-targets > summary").click();
    await page
      .locator("#TARGET_CONTAINERS")
      .fill(`${names[0]}\n${prefix}-missing`);
    await save(page);
    await jobFinished(page, "部分容器未更新");
    assert.match(
      await page.locator("#job-results").textContent(),
      /找不到目标容器/,
    );
    await page.screenshot({
      path: path.join(artifacts, "partial.png"),
      fullPage: true,
    });
    record("partial outcome and actionable error");

    await navigate(page, "config");
    await page.locator("#export-only").check();
    await save(page);
    await jobFinished(page, "hosts 已生成");
    assert.equal(
      (await (await context.request.get(`${url}/api/status`)).json()).job
        .containers.length,
      0,
    );
    await navigate(page, "config");
    await page.locator("#export-only").uncheck();
    await page.locator("#TARGET_CONTAINERS").fill(names.join("\n"));
    await save(page);
    await jobFinished(page, "更新完成");
    record("explicit export-only mode and return to container updates");

    await page.route("**/api/containers/available", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: "暂时无法读取容器，请检查 Docker，或手动填写名称。",
        }),
      }),
    );
    await navigate(page, "config");
    await page.locator("#picker-error").waitFor({ state: "visible" });
    assert.equal(
      await page.locator("#manual-targets").getAttribute("open"),
      "",
    );
    await page.unroute("**/api/containers/available");
    await page.locator("#refresh-picker").click();
    await page.locator("#picker-error").waitFor({ state: "hidden" });
    await page.route("**/api/status", (route) => route.abort());
    await navigate(page, "overview");
    await page.evaluate(() =>
      document.dispatchEvent(new Event("visibilitychange")),
    );
    await page.locator("#overview-error").waitFor({ state: "visible" });
    assert.equal(await page.locator("#update-title").textContent(), "更新完成");
    await page.unroute("**/api/status");
    await page.locator("#overview-error button").click();
    await page.locator("#overview-error").waitFor({ state: "hidden" });
    record(
      "Docker discovery recovery, connection failure retains last good state",
    );

    await navigate(page, "config");
    let releaseSave, saveEntered;
    const gate = new Promise((resolve) => {
      releaseSave = resolve;
    });
    const entered = new Promise((resolve) => {
      saveEntered = resolve;
    });
    await page.route("**/api/config", async (route) => {
      if (route.request().method() === "POST") {
        saveEntered();
        await gate;
      }
      await route.continue();
    });
    const originalDomains = await page.locator("#CF_DOMAINS").inputValue();
    await save(page, "save");
    await entered;
    await page
      .locator("#CF_DOMAINS")
      .fill(originalDomains + "\ntracker.pterclub.com");
    const savedResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/config") &&
        response.request().method() === "POST",
    );
    releaseSave();
    await savedResponse;
    await page.waitForFunction(() =>
      document
        .querySelector("#save-state")
        .textContent.includes("当前输入仍有未保存"),
    );
    assert.equal(
      await page.locator("#CF_DOMAINS").inputValue(),
      originalDomains + "\ntracker.pterclub.com",
    );
    await page.unroute("**/api/config");
    await save(page, "save");
    await page.waitForFunction(
      () =>
        document.querySelector("#save-state").textContent ===
        "已保存，后续任务使用新规则",
    );
    assert.equal(
      await page.locator("#CF_DOMAINS").inputValue(),
      originalDomains,
    );
    record("in-flight save preserves newer edits, saved values are normalized");

    await page.reload({ waitUntil: "networkidle" });
    await navigate(page, "config");
    assert.equal(
      await page.locator("#PREFERRED_IP").inputValue(),
      "2606:4700::1111",
    );
    await navigate(page, "overview");
    await page.screenshot({
      path: path.join(artifacts, "overview-final.png"),
      fullPage: true,
    });
    assert.deepEqual(errors, []);

    if (process.env.TASTE_SKILL_DIR) {
      for (const view of ["overview", "config", "containers", "logs"]) {
        const directory = path.join(artifacts, `taste-${view}`);
        const { stdout } = await execFile(
          process.execPath,
          [
            path.join(process.env.TASTE_SKILL_DIR, "scripts/inspect.mjs"),
            "--app",
            `${url}/#${view}`,
            "--out",
            directory,
          ],
          { cwd: root, env: process.env, timeout: 180000 },
        );
        fs.writeFileSync(path.join(directory, "summary.txt"), stdout);
        record(`taste inspector ${view}`);
      }
    }
    fs.writeFileSync(
      path.join(artifacts, "results.json"),
      JSON.stringify(
        { checks, javascriptErrors: errors, fixtures: names },
        null,
        2,
      ),
    );
    process.stdout.write(
      `Browser verification complete. Artifacts: ${artifacts}\n`,
    );
  } finally {
    if (browser) await browser.close();
    if (server) {
      server.kill("SIGTERM");
      await new Promise((resolve) => {
        server.once("exit", resolve);
        setTimeout(resolve, 2000);
      });
    }
    for (const name of created) {
      try {
        docker("rm", "-f", name);
      } catch {}
    }
    fs.writeFileSync(path.join(artifacts, "server.log"), serverLog);
    fs.rmSync(temporary, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
