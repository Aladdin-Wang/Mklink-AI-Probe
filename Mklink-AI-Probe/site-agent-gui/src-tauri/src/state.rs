use crate::config::SiteConfig;
use serde::Serialize;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

#[derive(Clone, Debug, Serialize)]
pub struct LastError {
    pub code: String,
    pub message: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub mode: String,
    pub service_state: String,
    pub core_state: String,
    pub configured_endpoint: String,
    pub active_endpoint: Option<String>,
    pub protocol_version: String,
    pub mklink_version: String,
    pub token_configured: bool,
    pub token_fingerprint: Option<String>,
    pub stcp_credentials_configured: bool,
    pub transport: String,
    pub probe_connected: bool,
    pub last_error: Option<LastError>,
    pub restart_count: u32,
    pub monitor_failures: u8,
    pub log_cursor: usize,
}

#[derive(Default)]
pub struct InstanceGuard {
    #[cfg(windows)]
    mutex: isize,
    #[cfg(windows)]
    focus_event: isize,
    #[cfg(windows)]
    focus_ready_event: isize,
}

impl InstanceGuard {
    #[cfg(windows)]
    pub fn new(mutex: isize, focus_event: isize, focus_ready_event: isize) -> Self {
        Self {
            mutex,
            focus_event,
            focus_ready_event,
        }
    }

    #[cfg(windows)]
    pub fn focus_event(&self) -> isize {
        self.focus_event
    }

    #[cfg(windows)]
    pub fn focus_ready_event(&self) -> isize {
        self.focus_ready_event
    }
}

impl Drop for InstanceGuard {
    fn drop(&mut self) {
        #[cfg(windows)]
        unsafe {
            if self.focus_ready_event != 0 {
                windows_sys::Win32::Foundation::CloseHandle(self.focus_ready_event as _);
                self.focus_ready_event = 0;
            }
            if self.focus_event != 0 {
                windows_sys::Win32::Foundation::CloseHandle(self.focus_event as _);
                self.focus_event = 0;
            }
            if self.mutex != 0 {
                windows_sys::Win32::Foundation::CloseHandle(self.mutex as _);
                self.mutex = 0;
            }
        }
    }
}

pub struct RuntimeState {
    pub root: PathBuf,
    pub config: SiteConfig,
    pub core: Option<crate::core_process::OwnedCore>,
    pub core_state: String,
    pub active_endpoint: Option<String>,
    pub probe_connected: bool,
    pub last_error: Option<LastError>,
    pub restart_count: u32,
    pub monitor_failures: u8,
    pub generation: u64,
    pub core_instance: u64,
    pub expected_stop: bool,
    pub last_reported_failure_instance: Option<u64>,
    pub instance: InstanceGuard,
}

pub struct AppState {
    pub runtime: Mutex<Option<RuntimeState>>,
    pub logs: Arc<Mutex<crate::log_store::LogStore>>,
    pub operation: Mutex<()>,
    pub operation_generation: AtomicU64,
    operation_active: AtomicBool,
}

pub struct LifecycleOperation<'a> {
    _guard: MutexGuard<'a, ()>,
    generation: &'a AtomicU64,
    active: &'a AtomicBool,
    epoch: u64,
}

impl LifecycleOperation<'_> {
    pub fn ensure_current(&self) -> Result<(), String> {
        if self.generation.load(Ordering::SeqCst) == self.epoch {
            Ok(())
        } else {
            Err("Lifecycle operation was superseded by a newer operation".into())
        }
    }
}

impl Drop for LifecycleOperation<'_> {
    fn drop(&mut self) {
        self.active.store(false, Ordering::SeqCst);
    }
}

impl AppState {
    pub fn new() -> Self {
        Self {
            runtime: Mutex::new(None),
            logs: Arc::new(Mutex::new(crate::log_store::LogStore::new())),
            operation: Mutex::new(()),
            operation_generation: AtomicU64::new(0),
            operation_active: AtomicBool::new(false),
        }
    }

    pub fn begin_operation(&self) -> Result<LifecycleOperation<'_>, String> {
        let guard = self.operation.lock().map_err(|_| {
            "Lifecycle operation coordination is unavailable because a previous operation panicked"
                .to_string()
        })?;
        let previous = self
            .operation_generation
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
                current.checked_add(1)
            })
            .map_err(|_| "Lifecycle operation generation is exhausted".to_string())?;
        self.operation_active.store(true, Ordering::SeqCst);
        Ok(LifecycleOperation {
            _guard: guard,
            generation: &self.operation_generation,
            active: &self.operation_active,
            epoch: previous + 1,
        })
    }

    pub fn operation_active(&self) -> bool {
        self.operation_active.load(Ordering::SeqCst)
    }
}

pub fn log(logs: &Arc<Mutex<crate::log_store::LogStore>>, message: impl Into<String>) {
    if let Ok(mut store) = logs.lock() {
        store.append(message);
    }
}
