mod config;
mod core_process;
mod log_store;
mod network;
mod remote_control;
mod secret;
mod state;
mod token_helper;

use config::SiteConfig;
use state::{
    log, AppState, InstanceGuard, LastError, LifecycleOperation, RuntimeState, Snapshot,
};
use std::path::PathBuf;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, State};

fn portable_root() -> Result<PathBuf, String> {
    let executable = std::env::current_exe().map_err(|_| "无法解析便携程序路径".to_string())?;
    let root = executable
        .parent()
        .ok_or_else(|| "无法解析便携程序目录".to_string())?
        .to_path_buf();
    if !root.join("portable.mode").is_file() {
        return Err("缺少 portable.mode；拒绝以未知部署模式运行".into());
    }
    Ok(root)
}

fn initialize(
    state: &AppState,
    root: PathBuf,
    instance: InstanceGuard,
) -> Result<(), String> {
    let operation = state.begin_operation()?;
    config::ensure_data_root(&root)?;
    state
        .logs
        .lock()
        .map_err(|_| "Portable log store is unavailable".to_string())?
        .initialize(&root)?;
    let config = config::load(&root)?;
    operation.ensure_current()?;
    *state.runtime.lock().map_err(|_| "运行状态不可用".to_string())? = Some(RuntimeState {
        root,
        config,
        core: None,
        core_state: "stopped".into(),
        active_endpoint: None,
        probe_connected: false,
        last_error: None,
        restart_count: 0,
        monitor_failures: 0,
        generation: 0,
        core_instance: 0,
        expected_stop: true,
        last_reported_failure_instance: None,
        instance,
    });
    log(&state.logs, "[gui] portable runtime initialized");
    Ok(())
}

enum InstanceGate {
    Primary(InstanceGuard),
    SecondarySignaled,
}

impl InstanceGate {
    fn enters_tauri(&self) -> bool {
        matches!(self, Self::Primary(_))
    }
}

#[cfg(windows)]
fn acquire_instance_gate(root: &std::path::Path) -> Result<InstanceGate, String> {
    use sha2::{Digest, Sha256};
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null;
    use windows_sys::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS, WAIT_OBJECT_0};
    use windows_sys::Win32::System::Threading::{
        CreateEventW, CreateMutexW, SetEvent, WaitForSingleObject,
    };
    let canonical = root.canonicalize().map_err(|_| "无法解析便携程序目录".to_string())?;
    let digest = Sha256::digest(canonical.to_string_lossy().to_lowercase().as_bytes());
    let suffix = digest[..12]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let name = format!(
        "Local\\MKLinkSiteAgent-{}",
        suffix
    );
    let event_name = format!("Local\\MKLinkSiteAgentFocus-{suffix}");
    let event_wide: Vec<u16> = std::ffi::OsStr::new(&event_name)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let ready_name = format!("Local\\MKLinkSiteAgentFocusReady-{suffix}");
    let ready_wide: Vec<u16> = std::ffi::OsStr::new(&ready_name)
        .encode_wide()
        .chain(Some(0))
        .collect();
    let event = unsafe { CreateEventW(null(), 0, 0, event_wide.as_ptr()) };
    if event.is_null() {
        return Err("Unable to create the Site Agent focus signal".into());
    }
    let ready_event = unsafe { CreateEventW(null(), 1, 0, ready_wide.as_ptr()) };
    if ready_event.is_null() {
        unsafe { windows_sys::Win32::Foundation::CloseHandle(event) };
        return Err("Unable to create the Site Agent focus readiness signal".into());
    }
    let wide: Vec<u16> = std::ffi::OsStr::new(&name).encode_wide().chain(Some(0)).collect();
    let handle = unsafe { CreateMutexW(null(), 0, wide.as_ptr()) };
    if handle.is_null() {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(event);
            windows_sys::Win32::Foundation::CloseHandle(ready_event);
        }
        return Err("无法创建便携版单实例锁".into());
    }
    let duplicate = unsafe { GetLastError() } == ERROR_ALREADY_EXISTS;
    let guard = InstanceGuard::new(
        handle as isize,
        event as isize,
        ready_event as isize,
    );
    if duplicate {
        let ready = unsafe { WaitForSingleObject(ready_event, 5_000) } == WAIT_OBJECT_0;
        if !ready {
            return Err("Existing MKLink Site Agent did not publish focus readiness".into());
        }
        if unsafe { SetEvent(event) } == 0 {
            return Err("Unable to signal the existing MKLink Site Agent window".into());
        }
        drop(guard);
        return Ok(InstanceGate::SecondarySignaled);
    }
    Ok(InstanceGate::Primary(guard))
}

#[cfg(not(windows))]
fn acquire_instance_gate(_root: &std::path::Path) -> Result<InstanceGate, String> {
    Ok(InstanceGate::Primary(InstanceGuard::default()))
}

#[tauri::command]
fn config_get(state: State<'_, AppState>) -> Result<SiteConfig, String> {
    let guard = state.runtime.lock().map_err(|_| "运行状态不可用".to_string())?;
    Ok(guard.as_ref().ok_or_else(|| "便携运行时未初始化".to_string())?.config.clone())
}

#[tauri::command]
fn config_save(config: SiteConfig, state: State<'_, AppState>) -> Result<bool, String> {
    let operation = state.begin_operation()?;
    operation.ensure_current()?;
    let (restart_required, was_running, previous) = {
        let mut guard = state.runtime.lock().map_err(|_| "运行状态不可用".to_string())?;
        let runtime = guard.as_mut().ok_or_else(|| "便携运行时未初始化".to_string())?;
        let token_configured = secret::configured(&runtime.root);
        config.validate(
            token_configured,
            secret::stcp_configured(&runtime.root),
        )?;
        if !network::is_local_bind(&config.bind_host) {
            return Err("监听地址不是当前主机的活动地址".into());
        }
        let restart_required = runtime.config.bind_host != config.bind_host
            || runtime.config.port != config.port
            || runtime.config.project_root != config.project_root
            || runtime.config.allow_lan != config.allow_lan
            || runtime.config.transport != config.transport
            || runtime.config.stcp_server_addr != config.stcp_server_addr
            || runtime.config.stcp_server_port != config.stcp_server_port
            || runtime.config.stcp_user != config.stcp_user
            || runtime.config.stcp_proxy_name != config.stcp_proxy_name;
        let previous = runtime.config.clone();
        let was_running = runtime.core.is_some();
        config::save(&runtime.root, &config)?;
        runtime.config = config;
        (restart_required, was_running, previous)
    };
    if restart_required && was_running {
        stop_owned(&state, &operation)?;
        operation.ensure_current()?;
        let mut guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_mut()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        runtime.restart_count += 1;
        drop(guard);
        if let Err(start_error) = start_owned(&state, &operation) {
            operation.ensure_current()?;
            {
                let mut guard = state.runtime.lock().map_err(|_| "运行状态不可用".to_string())?;
                let runtime = guard.as_mut().ok_or_else(|| "便携运行时未初始化".to_string())?;
                if config::save(&runtime.root, &previous).is_err() {
                    runtime.core_state = "failed".into();
                    return Err(
                        "Configuration apply failed; rollback could not be persisted and the core is safely stopped"
                            .into(),
                    );
                }
                runtime.config = previous;
            }
            operation.ensure_current()?;
            if start_owned(&state, &operation).is_err() {
                return Err(
                    "Configuration apply failed; previous core could not be restored and is safely stopped"
                        .into(),
                );
            }
            return Err(format!(
                "Configuration apply failed; previous configuration and core were restored: {start_error}"
            ));
        }
    }
    log(&state.logs, "[gui] configuration saved");
    Ok(restart_required)
}

#[tauri::command]
fn list_bind_addresses() -> Vec<String> {
    network::local_bind_addresses()
}

fn poll_state(state: &AppState) {
    if state.operation_active() {
        return;
    }
    let (prepared, unexpected) = {
        let Ok(mut guard) = state.runtime.lock() else {
            return;
        };
        let Some(runtime) = guard.as_mut() else {
            return;
        };
        if state.operation_active() || runtime.expected_stop || runtime.core.is_none() {
            (None, None)
        } else if runtime
            .core
            .as_mut()
            .is_some_and(|core| core.has_exited())
        {
            let instance = runtime.core_instance;
            let should_report = runtime.last_reported_failure_instance != Some(instance);
            if should_report {
                runtime.last_reported_failure_instance = Some(instance);
            }
            runtime.generation = runtime.generation.wrapping_add(1);
            let core = runtime.core.take();
            runtime.expected_stop = true;
            runtime.core_state = "failed".into();
            runtime.active_endpoint = None;
            runtime.probe_connected = false;
            runtime.monitor_failures = 0;
            runtime.last_error = Some(LastError {
                code: "core-unexpected-exit".into(),
                message: "Site Agent core exited unexpectedly".into(),
            });
            (None, Some((core, should_report)))
        } else {
            let target = runtime
                .core
                .as_ref()
                .expect("core presence checked above")
                .remote_target();
            (
                Some((runtime.generation, runtime.core_instance, target)),
                None,
            )
        }
    };
    if let Some((core, should_report)) = unexpected {
        drop(core);
        if should_report {
            log(&state.logs, "[gui] core exited unexpectedly");
        }
        return;
    }
    let Some((generation, instance, target)) = prepared else {
        return;
    };
    if state.operation_active() {
        return;
    }
    let outcome = remote_control::status(&target.host, target.port, &target.token);
    let terminal = {
        let Ok(mut guard) = state.runtime.lock() else {
            return;
        };
        let Some(runtime) = guard.as_mut() else {
            return;
        };
        if state.operation_active()
            || runtime.expected_stop
            || runtime.generation != generation
            || runtime.core_instance != instance
            || runtime.core.is_none()
        {
            return;
        }
        match outcome {
            Ok(status)
                if status.ready
                    && status.listener
                    && status.host == target.host
                    && status.port == target.port =>
            {
                runtime.probe_connected = status.probe_connected;
                runtime.core_state = if status.probe_connected {
                    "ready-probe"
                } else {
                    "ready-no-probe"
                }
                .into();
                runtime.monitor_failures = 0;
                runtime.last_error = None;
                None
            }
            _ => {
                runtime.monitor_failures = runtime.monitor_failures.saturating_add(1);
                runtime.core_state = "degraded".into();
                runtime.last_error = Some(LastError {
                    code: "core-health-unavailable".into(),
                    message: "Site Agent authenticated health is temporarily unavailable".into(),
                });
                if runtime.monitor_failures >= 3 {
                    let should_report =
                        runtime.last_reported_failure_instance != Some(instance);
                    if should_report {
                        runtime.last_reported_failure_instance = Some(instance);
                    }
                    runtime.generation = runtime.generation.wrapping_add(1);
                    runtime.expected_stop = true;
                    runtime.core_state = "failed".into();
                    runtime.active_endpoint = None;
                    runtime.probe_connected = false;
                    runtime.last_error = Some(LastError {
                        code: "core-health-terminal".into(),
                        message: "Site Agent health failed repeatedly; the owned core was stopped"
                            .into(),
                    });
                    Some((runtime.core.take(), should_report))
                } else {
                    None
                }
            }
        }
    };
    if let Some((core, should_report)) = terminal {
        if let Some(core) = core {
            core.stop();
        }
        if should_report {
            log(
                &state.logs,
                "[gui] core health failed repeatedly; owned core stopped",
            );
        }
    }
}

fn stop_owned(state: &AppState, operation: &LifecycleOperation<'_>) -> Result<(), String> {
    operation.ensure_current()?;
    let (generation, core) = {
        let mut guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_mut()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        runtime.generation = runtime.generation.wrapping_add(1);
        runtime.expected_stop = true;
        runtime.core_state = "stopping".into();
        runtime.active_endpoint = None;
        runtime.probe_connected = false;
        (runtime.generation, runtime.core.take())
    };
    if let Some(core) = core {
        log(&state.logs, "[gui] stopping core");
        core.stop();
    }
    operation.ensure_current()?;
    let mut guard = state
        .runtime
        .lock()
        .map_err(|_| "Runtime state is unavailable".to_string())?;
    let runtime = guard
        .as_mut()
        .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
    operation.ensure_current()?;
    if runtime.generation != generation {
        return Err("Core stop was superseded by a newer runtime generation".into());
    }
    runtime.core_state = "stopped".into();
    runtime.expected_stop = true;
    runtime.monitor_failures = 0;
    runtime.last_error = None;
    drop(guard);
    log(&state.logs, "[gui] core stopped");
    Ok(())
}

fn start_owned(
    state: &AppState,
    operation: &LifecycleOperation<'_>,
) -> Result<(), String> {
    operation.ensure_current()?;
    let (generation, instance, root, config, token, stcp_credentials, logs) = {
        let mut guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_mut()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        if runtime.core.is_some() {
            return Ok(());
        }
        runtime.config.validate(
            secret::configured(&runtime.root),
            secret::stcp_configured(&runtime.root),
        )?;
        if !network::is_local_bind(&runtime.config.bind_host) {
            return Err("The configured bind address is not active on this host".into());
        }
        let token = secret::load(&runtime.root)?;
        let stcp_credentials = if runtime.config.transport == "lan-stcp" {
            let credentials = secret::load_stcp(&runtime.root)?;
            if credentials.auth_token == token || credentials.secret_key == token {
                return Err(
                    "Site Agent, FRP authentication, and STCP credentials must be distinct"
                        .into(),
                );
            }
            Some(credentials)
        } else {
            None
        };
        runtime.generation = runtime.generation.wrapping_add(1);
        runtime.core_instance = runtime
            .core_instance
            .checked_add(1)
            .ok_or_else(|| "Core instance generation is exhausted".to_string())?;
        runtime.expected_stop = false;
        runtime.core_state = "starting".into();
        runtime.last_error = None;
        (
            runtime.generation,
            runtime.core_instance,
            runtime.root.clone(),
            runtime.config.clone(),
            token,
            stcp_credentials,
            state.logs.clone(),
        )
    };
    log(&state.logs, "[gui] starting core");
    let started = core_process::OwnedCore::start(
        &root,
        &config,
        &token,
        stcp_credentials.as_ref(),
        logs,
    );
    let mut superseded = None;
    operation.ensure_current()?;
    let result = {
        let mut guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_mut()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        operation.ensure_current()?;
        if runtime.generation != generation
            || runtime.core_instance != instance
            || runtime.core.is_some()
        {
            if let Ok((core, _, _)) = started {
                superseded = Some(core);
            }
            Err("Core startup was superseded by a newer lifecycle operation".into())
        } else {
            match started {
                Ok((core, endpoint, probe_connected)) => {
                    runtime.core = Some(core);
                    runtime.expected_stop = false;
                    runtime.active_endpoint = Some(endpoint);
                    runtime.probe_connected = probe_connected;
                    runtime.core_state = if probe_connected {
                        "ready-probe"
                    } else {
                        "ready-no-probe"
                    }
                    .into();
                    runtime.monitor_failures = 0;
                    runtime.last_error = None;
                    Ok(())
                }
                Err(error) => {
                    runtime.expected_stop = true;
                    runtime.core_state = "failed".into();
                    runtime.active_endpoint = None;
                    runtime.probe_connected = false;
                    runtime.last_error = Some(LastError {
                        code: "core-start-failed".into(),
                        message: error.clone(),
                    });
                    Err(error)
                }
            }
        }
    };
    if let Some(core) = superseded {
        core.stop();
    }
    if result.is_ok() {
        log(&state.logs, "[gui] core ready");
    } else {
        log(&state.logs, "[gui] core start failed");
    }
    result
}

#[tauri::command]
fn probe_refresh(
    state: State<'_, AppState>,
) -> Result<Vec<remote_control::ProbeSummary>, String> {
    let (generation, target) = {
        let guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_ref()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        let target = runtime
            .core
            .as_ref()
            .ok_or_else(|| "Start the Site Agent core before refreshing probes".to_string())?
            .remote_target();
        (runtime.generation, target)
    };
    // Refresh is deliberately read-only. Probe connection is a separate,
    // explicit operation and must never be attempted merely because the user
    // asks for current status/ports (especially on a no-hardware field host).
    let status = remote_control::status(&target.host, target.port, &target.token)?;
    if !status.ready
        || !status.listener
        || status.host != target.host
        || status.port != target.port
    {
        return Err("Site Agent authenticated status identity did not match".into());
    }
    let probes = remote_control::ports(&target.host, target.port, &target.token)?;
    let connected = status.probe_connected;
    let mut guard = state
        .runtime
        .lock()
        .map_err(|_| "Runtime state is unavailable".to_string())?;
    let runtime = guard
        .as_mut()
        .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
    if runtime.generation != generation || runtime.core.is_none() {
        return Err("Probe refresh was superseded by a core lifecycle change".into());
    }
    runtime.probe_connected = connected;
    runtime.core_state = if connected {
        "ready-probe"
    } else {
        "ready-no-probe"
    }
    .into();
    runtime.last_error = None;
    log(&state.logs, "[gui] probe discovery refreshed");
    Ok(probes)
}

#[tauri::command]
fn core_start(state: State<'_, AppState>) -> Result<(), String> {
    let operation = state.begin_operation()?;
    start_owned(&state, &operation)
}

#[tauri::command]
fn core_stop(state: State<'_, AppState>) -> Result<(), String> {
    let operation = state.begin_operation()?;
    stop_owned(&state, &operation)
}

#[tauri::command]
fn core_restart(state: State<'_, AppState>) -> Result<(), String> {
    let operation = state.begin_operation()?;
    stop_owned(&state, &operation)?;
    operation.ensure_current()?;
    {
        let mut guard = state.runtime.lock().map_err(|_| "运行状态不可用".to_string())?;
        let runtime = guard.as_mut().ok_or_else(|| "便携运行时未初始化".to_string())?;
        runtime.restart_count += 1;
    }
    start_owned(&state, &operation)
}

#[tauri::command]
fn token_generate_and_copy(state: State<'_, AppState>) -> Result<secret::TokenResult, String> {
    let operation = state.begin_operation()?;
    operation.ensure_current()?;
    let (root, was_running) = {
        let guard = state.runtime.lock().map_err(|_| "运行状态不可用".to_string())?;
        let runtime = guard.as_ref().ok_or_else(|| "便携运行时未初始化".to_string())?;
        (runtime.root.clone(), runtime.core.is_some())
    };
    let previous = secret::current_ciphertext(&root)?;
    let prepared = secret::prepare()?;
    let result = prepared.result();
    if was_running {
        stop_owned(&state, &operation)?;
        operation.ensure_current()?;
        let mut guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_mut()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        runtime.restart_count += 1;
        drop(guard);
    }
    operation.ensure_current()?;
    if let Err(error) = secret::commit(&root, &prepared) {
        if was_running {
            let _ = start_owned(&state, &operation);
        }
        return Err(error);
    }
    if was_running {
        if let Err(start_error) = start_owned(&state, &operation) {
            operation.ensure_current()?;
            let rollback = secret::restore_ciphertext(&root, previous.as_deref());
            let recovery = rollback.and_then(|()| start_owned(&state, &operation));
            if recovery.is_err() {
                operation.ensure_current()?;
                let mut guard = state
                    .runtime
                    .lock()
                    .map_err(|_| "Runtime state is unavailable".to_string())?;
                let runtime = guard
                    .as_mut()
                    .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
                runtime.core_state = "failed".into();
                runtime.active_endpoint = None;
                runtime.probe_connected = false;
                return Err(
                    "Credential rotation failed; previous credential could not be restored and the core is safely stopped"
                        .into(),
                );
            }
            return Err(format!(
                "Credential rotation failed; previous credential and running core were restored: {start_error}"
            ));
        }
    }
    if let Err(copy_error) = secret::copy_prepared(&prepared) {
        if was_running {
            stop_owned(&state, &operation)?;
        }
        operation.ensure_current()?;
        let rollback = secret::restore_ciphertext(&root, previous.as_deref());
        let recovery = if was_running {
            rollback.and_then(|()| start_owned(&state, &operation))
        } else {
            rollback
        };
        if recovery.is_err() {
            operation.ensure_current()?;
            let mut guard = state
                .runtime
                .lock()
                .map_err(|_| "Runtime state is unavailable".to_string())?;
            let runtime = guard
                .as_mut()
                .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
            runtime.core_state = "failed".into();
            runtime.active_endpoint = None;
            runtime.probe_connected = false;
            return Err(
                "Credential clipboard delivery failed; rollback failed and the core is safely stopped"
                    .into(),
            );
        }
        return Err(format!(
            "Credential clipboard delivery failed; previous credential state was restored: {copy_error}"
        ));
    }
    log(&state.logs, "[gui] credential rotated and copied");
    Ok(result)
}

#[tauri::command]
fn stcp_credentials_configure(
    auth_token: String,
    secret_key: String,
    state: State<'_, AppState>,
) -> Result<bool, String> {
    let operation = state.begin_operation()?;
    operation.ensure_current()?;
    let root = {
        let guard = state
            .runtime
            .lock()
            .map_err(|_| "Runtime state is unavailable".to_string())?;
        let runtime = guard
            .as_ref()
            .ok_or_else(|| "Portable runtime is not initialized".to_string())?;
        if runtime.core.is_some() {
            return Err("Stop the Site Agent before changing STCP credentials".into());
        }
        runtime.root.clone()
    };
    let site_token = secret::load(&root)?;
    if auth_token == site_token || secret_key == site_token {
        return Err(
            "Site Agent, FRP authentication, and STCP credentials must be distinct"
                .into(),
        );
    }
    secret::store_stcp(&root, &auth_token, &secret_key)?;
    log(&state.logs, "[gui] LAN STCP credentials updated");
    Ok(true)
}

#[tauri::command]
fn snapshot(state: State<'_, AppState>) -> Result<Snapshot, String> {
    let guard = state.runtime.lock().map_err(|_| "运行状态不可用".to_string())?;
    let runtime = guard.as_ref().ok_or_else(|| "便携运行时未初始化".to_string())?;
    let fingerprint = secret::fingerprint(&runtime.root);
    let cursor = state.logs.lock().map(|logs| logs.cursor()).unwrap_or_default();
    Ok(Snapshot {
        mode: "portable".into(),
        service_state: "not-installed".into(),
        core_state: runtime.core_state.clone(),
        configured_endpoint: configured_endpoint(&runtime.config),
        active_endpoint: runtime.active_endpoint.clone(),
        protocol_version: "1.0".into(),
        mklink_version: "0.1.4".into(),
        token_configured: fingerprint.is_some(),
        token_fingerprint: fingerprint,
        stcp_credentials_configured: secret::stcp_configured(&runtime.root),
        transport: runtime.config.transport.clone(),
        probe_connected: runtime.probe_connected,
        last_error: runtime.last_error.clone(),
        restart_count: runtime.restart_count,
        monitor_failures: runtime.monitor_failures,
        log_cursor: cursor,
    })
}

#[tauri::command]
fn logs_tail(
    cursor: Option<usize>,
    state: State<'_, AppState>,
) -> log_store::LogBatch {
    state
        .logs
        .lock()
        .map(|logs| logs.tail(cursor))
        .unwrap_or(log_store::LogBatch {
            cursor: cursor.unwrap_or_default(),
            lines: Vec::new(),
        })
}

fn endpoint(host: &str, port: u16) -> String {
    if host.contains(':') {
        format!("ws://[{host}]:{port}")
    } else {
        format!("ws://{host}:{port}")
    }
}

fn configured_endpoint(config: &SiteConfig) -> String {
    if config.transport == "lan-stcp" {
        format!(
            "stcp://{}@{}:{}",
            config.stcp_proxy_name,
            config.stcp_server_addr,
            config.stcp_server_port
        )
    } else {
        endpoint(&config.bind_host, config.port)
    }
}

fn stop_before_exit(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    let operation = state.begin_operation()?;
    stop_owned(&state, &operation)
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg(windows)]
fn spawn_focus_listener(app: tauri::AppHandle) -> Result<(), String> {
    use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
    use windows_sys::Win32::System::Threading::{WaitForSingleObject, INFINITE};
    let (event, ready_event) = {
        let state = app.state::<AppState>();
        state
            .runtime
            .lock()
            .ok()
            .and_then(|runtime| {
                runtime
                    .as_ref()
                    .map(|runtime| {
                        (
                            runtime.instance.focus_event(),
                            runtime.instance.focus_ready_event(),
                        )
                    })
            })
            .unwrap_or_default()
    };
    if event == 0 || ready_event == 0 {
        return Err("Site Agent focus events are unavailable".into());
    }
    std::thread::Builder::new()
        .name("mklink-focus-listener".into())
        .spawn(move || {
            unsafe { windows_sys::Win32::System::Threading::SetEvent(ready_event as _) };
            loop {
                if unsafe { WaitForSingleObject(event as _, INFINITE) } != WAIT_OBJECT_0 {
                    break;
                }
                show_main(&app);
            }
        })
        .map_err(|_| "Unable to create the Site Agent focus listener".to_string())?;
    Ok(())
}

#[cfg(not(windows))]
fn spawn_focus_listener(_app: tauri::AppHandle) -> Result<(), String> {
    Ok(())
}

fn run_primary(root: PathBuf, instance: InstanceGuard) {
    let app_state = AppState::new();
    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            config_get,
            config_save,
            list_bind_addresses,
            core_start,
            core_stop,
            core_restart,
            token_generate_and_copy,
            stcp_credentials_configure,
            probe_refresh,
            snapshot,
            logs_tail,
        ])
        .setup(move |app| {
            initialize(&app.state::<AppState>(), root, instance)
                .map_err(std::io::Error::other)?;
            spawn_focus_listener(app.handle().clone()).map_err(std::io::Error::other)?;
            let supervisor = app.handle().clone();
            std::thread::Builder::new()
                .name("mklink-core-supervisor".into())
                .spawn(move || loop {
                    std::thread::sleep(std::time::Duration::from_secs(2));
                    let state = supervisor.state::<AppState>();
                    poll_state(&state);
                })
                .map_err(std::io::Error::other)?;

            let open = MenuItem::with_id(app, "open", "打开", true, None::<&str>)?;
            let start = MenuItem::with_id(app, "start", "启动", true, None::<&str>)?;
            let stop = MenuItem::with_id(app, "stop", "停止", true, None::<&str>)?;
            let exit = MenuItem::with_id(app, "exit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &start, &stop, &exit])?;
            TrayIconBuilder::new()
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_main(app),
                    "start" => {
                        let state = app.state::<AppState>();
                        let result = state
                            .begin_operation()
                            .and_then(|operation| start_owned(&state, &operation));
                        if let Err(error) = result {
                            log(&state.logs, format!("[gui:error] tray start failed: {error}"));
                        }
                    }
                    "stop" => {
                        let state = app.state::<AppState>();
                        let result = state
                            .begin_operation()
                            .and_then(|operation| stop_owned(&state, &operation));
                        if let Err(error) = result {
                            log(&state.logs, format!("[gui:error] tray stop failed: {error}"));
                        }
                    }
                    "exit" => {
                        if let Err(error) = stop_before_exit(app) {
                            let state = app.state::<AppState>();
                            log(
                                &state.logs,
                                format!("[gui:error] explicit exit cleanup failed: {error}"),
                            );
                        }
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("MKLink Site Agent runtime failed");
}

pub fn run() {
    let root = portable_root().expect("MKLink Site Agent portable root is invalid");
    let gate = acquire_instance_gate(&root)
        .expect("MKLink Site Agent single-instance gate failed");
    if !gate.enters_tauri() {
        return;
    }
    let InstanceGate::Primary(instance) = gate else {
        unreachable!("only the primary instance may enter Tauri");
    };
    run_primary(root, instance);
}

#[cfg(test)]
mod tests {
    use super::{InstanceGate, InstanceGuard};

    #[test]
    fn secondary_gate_skips_tauri() {
        assert!(!InstanceGate::SecondarySignaled.enters_tauri());
    }

    #[test]
    fn primary_gate_enters_tauri() {
        assert!(InstanceGate::Primary(InstanceGuard::default()).enters_tauri());
    }
}
