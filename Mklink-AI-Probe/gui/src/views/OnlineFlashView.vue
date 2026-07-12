<template>
  <div class="online-flash-grid">
    <aside class="workspace-zone settings-zone" data-zone="settings">
      <h2>烧录设置</h2>
      <p>选择调试器与目标芯片</p>
    </aside>
    <main class="workspace-zone firmware-zone" data-zone="firmware">
      <h2>固件</h2>
      <p>检查固件并创建在线烧录任务</p>
    </main>
    <aside class="workspace-zone flash-map-zone" data-zone="flash-map">
      <h2>Flash Map</h2>
      <p>镜像地址与扇区范围</p>
    </aside>
    <section class="workspace-zone logs-zone" data-zone="logs">
      <h2>任务日志</h2>
      <p>等待在线烧录任务</p>
    </section>
  </div>
</template>

<style scoped>
.online-flash-grid {
  --workspace-bg: #15181d;
  --workspace-surface: #1d2229;
  --workspace-border: #303741;
  --workspace-text: #e6e9ed;
  --workspace-muted: #929ba7;
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(210px, 0.8fr) minmax(360px, 1.7fr) minmax(220px, 0.9fr);
  grid-template-rows: minmax(340px, 1fr) minmax(160px, 0.45fr);
  gap: 12px;
  padding: 12px;
  border-radius: var(--radius);
  background: var(--workspace-bg);
  color: var(--workspace-text);
}

.workspace-zone {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--workspace-border);
  border-radius: var(--radius);
  background: var(--workspace-surface);
}

.workspace-zone h2 {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.workspace-zone p {
  margin: 0;
  color: var(--workspace-muted);
  font-size: 12px;
}

.logs-zone {
  grid-column: 1 / -1;
  font-family: var(--font-mono);
}

@media (max-width: 1050px) {
  .online-flash-grid {
    grid-template-columns: minmax(200px, 0.8fr) minmax(360px, 1.5fr);
  }

  .flash-map-zone {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .online-flash-grid {
    grid-template-columns: 1fr;
    grid-template-rows: none;
  }

  .flash-map-zone,
  .logs-zone {
    grid-column: auto;
  }
}
</style>
