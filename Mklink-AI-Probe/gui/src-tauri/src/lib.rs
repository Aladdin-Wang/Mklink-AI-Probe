use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::{Manager, State};

#[cfg(target_os = "windows")]
use windows::core::PCWSTR;
#[cfg(target_os = "windows")]
use windows::Win32::Foundation::HANDLE;
#[cfg(target_os = "windows")]
use windows::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

/// Thread-safe wrapper for Windows HANDLE — raw pointers are not Send/Sync.
#[cfg(target_os = "windows")]
struct JobHandle(HANDLE);
#[cfg(target_os = "windows")]
unsafe impl Send for JobHandle {}
#[cfg(target_os = "windows")]
unsafe impl Sync for JobHandle {}

struct Sidecar {
    child: Mutex<Option<Child>>,
    port: u16,
    project_root: String,
    #[cfg(target_os = "windows")]
    job: Mutex<Option<JobHandle>>,
}

const MAX_RESTARTS: u32 = 5;
const HEALTH_CHECK_INTERVAL_SECS: u64 = 5;
const MAX_CONSECUTIVE_FAILS: u32 = 3;

#[derive(Debug, Clone, PartialEq, Eq)]
enum SidecarLaunch {
    Bundled(std::path::PathBuf),
    Python(String),
}

fn choose_sidecar_launch(
    bundled: Option<std::path::PathBuf>,
    python: Option<String>,
) -> Result<SidecarLaunch, String> {
    if let Some(path) = bundled {
        return Ok(SidecarLaunch::Bundled(path));
    }
    if let Some(command) = python {
        return Ok(SidecarLaunch::Python(command));
    }
    Err("No bundled sidecar or Python runtime is available".into())
}

fn find_bundled_sidecar() -> Option<std::path::PathBuf> {
    let directory = std::env::current_exe().ok()?.parent()?.to_path_buf();
    let candidate = directory.join("mklink-sidecar.exe");
    candidate.is_file().then_some(candidate)
}

fn find_python() -> Option<String> {
    for name in &["python", "python3"] {
        if which_exists(name) {
            return Some(name.to_string());
        }
    }
    None
}

fn resolve_sidecar_launch() -> Result<SidecarLaunch, String> {
    choose_sidecar_launch(find_bundled_sidecar(), find_python())
}

fn default_project_root() -> String {
    ".".into()
}

#[cfg(target_os = "windows")]
fn which_exists(name: &str) -> bool {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    Command::new("where")
        .arg(name)
        .creation_flags(CREATE_NO_WINDOW)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

#[cfg(not(target_os = "windows"))]
fn which_exists(name: &str) -> bool {
    Command::new("which")
        .arg(name)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Create a Windows Job Object that kills child processes when the parent dies.
#[cfg(target_os = "windows")]
fn create_kill_on_close_job() -> Result<JobHandle, String> {
    use windows::Win32::System::JobObjects::JobObjectExtendedLimitInformation;

    unsafe {
        let job = CreateJobObjectW(None, PCWSTR::null())
            .map_err(|e| format!("CreateJobObjectW failed: {}", e))?;

        let mut info =
            windows::Win32::System::JobObjects::JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const _,
            std::mem::size_of::<
                windows::Win32::System::JobObjects::JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            >() as u32,
        )
        .map_err(|e| format!("SetInformationJobObject failed: {}", e))?;

        Ok(JobHandle(job))
    }
}

/// Assign a child process to the job object so it dies when we die.
#[cfg(target_os = "windows")]
fn assign_to_job(job: &JobHandle, child: &Child) -> Result<(), String> {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{OpenProcess, PROCESS_ALL_ACCESS};

    unsafe {
        let proc_handle = OpenProcess(PROCESS_ALL_ACCESS, false, child.id())
            .map_err(|e| format!("OpenProcess({}) failed: {}", child.id(), e))?;

        AssignProcessToJobObject(job.0, proc_handle)
            .map_err(|e| format!("AssignProcessToJobObject failed: {}", e))?;

        let _ = CloseHandle(proc_handle);
        Ok(())
    }
}

fn spawn_sidecar(launch: &SidecarLaunch, port: u16, project_root: &str) -> Result<Child, String> {
    use std::os::windows::process::CommandExt;
    use std::process::Stdio;
    // CREATE_NO_WINDOW = 0x08000000 — prevents Python console window from flashing
    const CREATE_NO_WINDOW: u32 = 0x08000000;

    let (mut command, label) = match launch {
        SidecarLaunch::Bundled(path) => (Command::new(path), path.to_string_lossy().into_owned()),
        SidecarLaunch::Python(python) => {
            let mut command = Command::new(python);
            command.args(["-m", "mklink"]);
            (command, python.clone())
        }
    };

    command
        .args([
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--project-root",
            project_root,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("Failed to start sidecar ({}): {}", label, e))
}

fn retain_child_if_registered<T, E>(
    mut child: T,
    register: impl FnOnce(&T) -> Result<(), E>,
    cleanup: impl FnOnce(&mut T),
) -> Result<T, E> {
    if let Err(error) = register(&child) {
        cleanup(&mut child);
        return Err(error);
    }
    Ok(child)
}

#[cfg(target_os = "windows")]
fn spawn_registered_sidecar(
    state: &Sidecar,
    launch: &SidecarLaunch,
    port: u16,
    project_root: &str,
) -> Result<Child, String> {
    let mut job_guard = state.job.lock().map_err(|e| e.to_string())?;
    if job_guard.is_none() {
        *job_guard = Some(create_kill_on_close_job()?);
    }
    let job = job_guard.as_ref().expect("job was initialized");
    let child = spawn_sidecar(launch, port, project_root)?;
    retain_child_if_registered(
        child,
        |child| assign_to_job(job, child),
        |child| {
            let _ = child.kill();
            let _ = child.wait();
        },
    )
}

/// Minimal HTTP health check using raw TCP — no external deps needed.
fn check_health(port: u16) -> bool {
    use std::io::{Read, Write};
    let addr = format!("127.0.0.1:{}", port);
    let mut stream = match std::net::TcpStream::connect_timeout(
        &addr.parse().unwrap(),
        std::time::Duration::from_secs(3),
    ) {
        Ok(s) => s,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(3)));
    let _ = stream.set_write_timeout(Some(std::time::Duration::from_secs(3)));

    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
        port
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 256];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let resp = String::from_utf8_lossy(&buf[..n]);
            resp.contains("200")
        }
        _ => false,
    }
}

#[tauri::command]
fn sidecar_status(state: State<Sidecar>) -> Result<bool, String> {
    let mut guard = state.child.lock().map_err(|e| e.to_string())?;
    match guard.as_mut() {
        Some(child) => match child.try_wait() {
            Ok(Some(_)) => {
                *guard = None;
                Ok(false)
            }
            Ok(None) => Ok(true),
            Err(e) => Err(e.to_string()),
        },
        None => Ok(false),
    }
}

#[tauri::command]
fn start_sidecar(
    state: State<Sidecar>,
    project_root: Option<String>,
    port: Option<u16>,
) -> Result<u16, String> {
    let mut guard = state.child.lock().map_err(|e| e.to_string())?;
    if guard.is_some()
        && guard
            .as_mut()
            .unwrap()
            .try_wait()
            .map(|s| s.is_none())
            .unwrap_or(false)
    {
        return Ok(port.unwrap_or(state.port));
    }

    let port = port.unwrap_or(state.port);
    let project_root = project_root.unwrap_or_else(|| state.project_root.clone());

    let launch = resolve_sidecar_launch()?;
    let child = spawn_registered_sidecar(state.inner(), &launch, port, &project_root)?;

    *guard = Some(child);
    Ok(port)
}

#[tauri::command]
fn stop_sidecar(state: State<Sidecar>) -> Result<(), String> {
    let mut guard = state.child.lock().map_err(|e| e.to_string())?;
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(())
}

#[tauri::command]
fn restart_sidecar(state: State<Sidecar>) -> Result<u16, String> {
    // Stop
    {
        let mut guard = state.child.lock().map_err(|e| e.to_string())?;
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    std::thread::sleep(std::time::Duration::from_secs(1));
    start_sidecar(state, None, None)
}

#[tauri::command]
fn backend_alive(state: State<Sidecar>) -> Result<bool, String> {
    let running = {
        let mut guard = state.child.lock().map_err(|e| e.to_string())?;
        match guard.as_mut() {
            Some(child) => child.try_wait().map(|s| s.is_none()).unwrap_or(false),
            None => false,
        }
    };
    if !running {
        return Ok(false);
    }
    Ok(check_health(state.port))
}

fn run_monitor(handle: tauri::AppHandle, shutdown: std::sync::Arc<AtomicBool>) {
    let mut consecutive_fails: u32 = 0;
    let mut restart_count: u32 = 0;

    loop {
        std::thread::sleep(std::time::Duration::from_secs(HEALTH_CHECK_INTERVAL_SECS));

        if shutdown.load(Ordering::Relaxed) {
            break;
        }

        let state: State<Sidecar> = handle.state();

        let process_alive = {
            let mut guard = state.child.lock().unwrap();
            match guard.as_mut() {
                Some(child) => child.try_wait().map(|s| s.is_none()).unwrap_or(false),
                None => false,
            }
        };

        if !process_alive {
            if restart_count >= MAX_RESTARTS {
                eprintln!(
                    "[tauri] max restarts ({}) reached, stopping monitor",
                    MAX_RESTARTS
                );
                break;
            }
            restart_count += 1;
            eprintln!(
                "[tauri] sidecar exited, restarting ({}/{})...",
                restart_count, MAX_RESTARTS
            );
            // Longer backoff: 3s base + 2s per restart attempt
            let backoff = 3 + 2 * (restart_count - 1);
            std::thread::sleep(std::time::Duration::from_secs(backoff as u64));

            // Check if port is already in use — no point restarting if so
            if check_health(state.port) {
                eprintln!(
                    "[tauri] port {} already in use, skipping restart",
                    state.port
                );
                restart_count = restart_count.saturating_sub(1); // don't count this
                continue;
            }

            let launch = match resolve_sidecar_launch() {
                Ok(launch) => launch,
                Err(error) => {
                    eprintln!("[tauri] cannot resolve sidecar: {}", error);
                    continue;
                }
            };

            match spawn_registered_sidecar(
                state.inner(),
                &launch,
                state.port,
                &state.project_root,
            ) {
                Ok(child) => {
                    let mut guard = state.child.lock().unwrap();
                    *guard = Some(child);
                    eprintln!("[tauri] sidecar restarted");
                    consecutive_fails = 0;
                }
                Err(e) => eprintln!("[tauri] restart failed: {}", e),
            }
            continue;
        }

        // Process alive — check HTTP health
        if check_health(state.port) {
            consecutive_fails = 0;
        } else {
            consecutive_fails += 1;
            eprintln!(
                "[tauri] health check failed ({}/{})",
                consecutive_fails, MAX_CONSECUTIVE_FAILS
            );
            if consecutive_fails >= MAX_CONSECUTIVE_FAILS {
                eprintln!("[tauri] backend unresponsive, killing...");
                {
                    let mut guard = state.child.lock().unwrap();
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
                consecutive_fails = 0;
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let shutdown = std::sync::Arc::new(AtomicBool::new(false));

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .manage(Sidecar {
            child: Mutex::new(None),
            port: 8765,
            project_root: default_project_root(),
            #[cfg(target_os = "windows")]
            job: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            sidecar_status,
            start_sidecar,
            stop_sidecar,
            restart_sidecar,
            backend_alive,
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let shutdown_clone = shutdown.clone();

            // Kill sidecar when main window closes
            let cleanup_handle = app.handle().clone();
            let cleanup_shutdown = shutdown.clone();
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { .. } = event {
                        eprintln!("[tauri] window closing, cleaning up sidecar...");
                        cleanup_shutdown.store(true, Ordering::Relaxed);
                        let state: State<Sidecar> = cleanup_handle.state();
                        let mut guard = state.child.lock().unwrap();
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                            eprintln!("[tauri] sidecar killed");
                        }
                    }
                });
            }

            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(1));
                let state: State<Sidecar> = handle.state();
                match start_sidecar(state, None, Some(8765)) {
                    Ok(port) => {
                        eprintln!("[tauri] sidecar started on port {}", port);
                        // Wait for Python to fully initialize before monitoring
                        for _ in 0..20 {
                            if check_health(port) {
                                eprintln!("[tauri] backend healthy");
                                break;
                            }
                            std::thread::sleep(std::time::Duration::from_millis(500));
                        }
                    }
                    Err(e) => eprintln!(
                        "[tauri] sidecar failed: {} (start Python backend manually)",
                        e
                    ),
                }
                run_monitor(handle, shutdown_clone);
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_sidecar_wins_over_python() {
        let bundled = std::path::PathBuf::from(r"C:\Program Files\Mklink\mklink-sidecar.exe");
        assert_eq!(
            choose_sidecar_launch(Some(bundled.clone()), Some("python".into()),).unwrap(),
            SidecarLaunch::Bundled(bundled),
        );
    }

    #[test]
    fn python_is_only_the_development_fallback() {
        assert_eq!(
            choose_sidecar_launch(None, Some("python".into())).unwrap(),
            SidecarLaunch::Python("python".into()),
        );
    }

    #[test]
    fn missing_sidecar_and_python_is_an_error() {
        assert!(choose_sidecar_launch(None, None)
            .unwrap_err()
            .contains("No bundled sidecar or Python runtime"));
    }

    #[test]
    fn installed_runtime_lets_backend_restore_the_last_project() {
        assert_eq!(default_project_root(), ".");
    }

    #[test]
    fn failed_child_registration_runs_cleanup() {
        let mut cleaned = false;
        let result = retain_child_if_registered(
            "child",
            |_| Err("job assignment failed"),
            |_| cleaned = true,
        );

        assert_eq!(result.unwrap_err(), "job assignment failed");
        assert!(cleaned);
    }

    #[test]
    fn successful_child_registration_retains_child_without_cleanup() {
        let mut cleaned = false;
        let result = retain_child_if_registered("child", |_| Ok::<_, &str>(()), |_| cleaned = true);

        assert_eq!(result.unwrap(), "child");
        assert!(!cleaned);
    }
}
