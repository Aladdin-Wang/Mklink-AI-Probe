const invoke = window.__TAURI__.core.invoke;
const $ = (id) => document.getElementById(id);
let pending = false;
let probeSummaries = [];
let logCursor = 0;
let logLines = [];

function notify(message, error = false) {
  const node = $("notice");
  node.textContent = message;
  node.className = error ? "show error" : "show";
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { node.className = ""; }, 4200);
}

function setPending(value) {
  pending = value;
  document.querySelectorAll("button, input, select").forEach((node) => {
    node.disabled = value;
  });
}

function syncTransportUI() {
  const isStcp = $("transport").value === "lan-stcp";
  document.querySelectorAll(".stcp-only").forEach((node) => {
    node.classList.toggle("hidden", !isStcp);
  });
  if (isStcp) {
    $("bind-host").value = "127.0.0.1";
    $("allow-lan").checked = false;
  }
  if (!pending) {
    $("bind-host").disabled = isStcp;
    $("allow-lan").disabled = isStcp;
  }
}

function configFromForm() {
  return {
    schema: "mklink.site-agent.config.v1",
    mode: "portable",
    transport: $("transport").value,
    bind_host: $("bind-host").value,
    port: Number($("port").value),
    allow_lan: $("allow-lan").checked,
    project_root: $("project-root").value.trim(),
    start_core_on_launch: true,
    stcp_server_addr: $("stcp-server-addr").value.trim(),
    stcp_server_port: Number($("stcp-server-port").value),
    stcp_user: $("stcp-user").value.trim(),
    stcp_proxy_name: $("stcp-proxy-name").value.trim(),
  };
}

async function refresh() {
  const state = await invoke("snapshot");
  $("core-state").textContent = state.core_state;
  $("active-endpoint").textContent = state.active_endpoint || "未启动";
  $("token-state").textContent = state.token_configured ? "已配置" : "未配置";
  $("stcp-credential-state").textContent = state.stcp_credentials_configured ? "已配置" : "未配置";
  $("transport-state").textContent = state.transport === "lan-stcp" ? "LAN STCP（进程内）" : "直接连接";
  $("fingerprint").textContent = `指纹：${state.token_fingerprint || "—"}`;
  $("probe-state").textContent = `${state.probe_connected ? "已连接" : "未连接"} / ${probeSummaries.length} 个端口`;
  $("probe-list").replaceChildren(...(
    probeSummaries.length
      ? probeSummaries.map((probe) => {
          const item = document.createElement("li");
          const details = [probe.description, probe.manufacturer].filter(Boolean).join(" · ");
          item.textContent = `${probe.device}${details ? ` — ${details}` : ""}`;
          return item;
        })
      : [Object.assign(document.createElement("li"), { textContent: "未发现可用串口" })]
  ));
  const badge = $("core-badge");
  badge.textContent = state.core_state;
  badge.className = `badge ${state.core_state.startsWith("ready") ? "ready" : state.core_state === "failed" ? "failed" : "neutral"}`;
  const running = ["starting", "ready-no-probe", "ready-probe", "degraded"].includes(state.core_state);
  $("start").disabled = pending || running;
  $("stop").disabled = pending || !running;
  $("restart").disabled = pending || !running;
  const batch = await invoke("logs_tail", { cursor: logCursor });
  logCursor = batch.cursor;
  logLines = logLines.concat(batch.lines).slice(-500);
  $("logs").textContent = logLines.length ? logLines.join("\n") : "暂无日志";
}

async function initialize() {
  try {
    const [addresses, config] = await Promise.all([
      invoke("list_bind_addresses"),
      invoke("config_get"),
    ]);
    $("bind-host").replaceChildren(...addresses.map((address) => {
      const option = document.createElement("option");
      option.value = address;
      option.textContent = address === "127.0.0.1" ? "127.0.0.1（仅本机）" : address;
      return option;
    }));
    if (!addresses.includes(config.bind_host)) {
      const option = document.createElement("option");
      option.value = config.bind_host;
      option.textContent = config.bind_host;
      $("bind-host").append(option);
    }
    $("transport").value = config.transport;
    $("bind-host").value = config.bind_host;
    $("port").value = config.port;
    $("project-root").value = config.project_root;
    $("allow-lan").checked = config.allow_lan;
    $("stcp-server-addr").value = config.stcp_server_addr;
    $("stcp-server-port").value = config.stcp_server_port;
    $("stcp-user").value = config.stcp_user;
    $("stcp-proxy-name").value = config.stcp_proxy_name;
    syncTransportUI();
    await refresh();
  } catch (error) {
    notify(String(error), true);
  }
}

async function action(name, fn) {
  if (pending) return;
  setPending(true);
  try {
    await fn();
    notify(`${name}完成`);
  } catch (error) {
    notify(String(error), true);
  } finally {
    setPending(false);
    syncTransportUI();
    await refresh().catch(() => {});
  }
}

$("save").addEventListener("click", () => action("保存", async () => {
  await invoke("config_save", { config: configFromForm() });
}));
$("save-restart").addEventListener("click", () => action("保存并重启", async () => {
  await invoke("config_save", { config: configFromForm() });
  await invoke("core_restart");
}));
$("start").addEventListener("click", () => action("启动", () => invoke("core_start")));
$("stop").addEventListener("click", () => action("停止", () => invoke("core_stop")));
$("restart").addEventListener("click", () => action("重启", () => invoke("core_restart")));
$("token").addEventListener("click", () => action("令牌已生成并复制", async () => {
  const result = await invoke("token_generate_and_copy");
  if (!result.copied) throw new Error("令牌已保存，但未能复制到剪贴板");
}));
$("stcp-credentials").addEventListener("click", () => action("STCP 凭据已保存", async () => {
  const authToken = $("stcp-auth-token").value;
  const secretKey = $("stcp-secret").value;
  try {
    await invoke("stcp_credentials_configure", { authToken, secretKey });
  } finally {
    $("stcp-auth-token").value = "";
    $("stcp-secret").value = "";
  }
}));
$("refresh").addEventListener("click", () => action("刷新探针", async () => {
  probeSummaries = await invoke("probe_refresh");
}));
$("transport").addEventListener("change", syncTransportUI);

initialize();
setInterval(() => { if (!pending) refresh().catch(() => {}); }, 2500);
