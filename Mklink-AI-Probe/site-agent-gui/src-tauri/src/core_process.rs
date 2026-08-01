use crate::config::{ready_path, SiteConfig};
use crate::state::log;
use serde::Deserialize;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const TOKEN_ENV: &str = "MKLINK_REMOTE_TOKEN";
const STCP_AUTH_ENV: &str = "MKLINK_STCP_AUTH_TOKEN";
const STCP_SECRET_ENV: &str = "MKLINK_STCP_SECRET";
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const FORCE_REAP_TIMEOUT: Duration = Duration::from_secs(3);
const DRAIN_FINISH_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Deserialize)]
struct ReadyFile {
    schema: String,
    event: String,
    ready: bool,
    host: String,
    port: u16,
    pid: u32,
    probe_connected: bool,
    transport: String,
    tunnel_ready: bool,
}

#[derive(Deserialize)]
struct LifecycleHealth {
    schema: String,
    event: String,
    result: HealthResult,
}

#[derive(Deserialize)]
struct HealthResult {
    ready: bool,
    listener: bool,
    probe_connected: bool,
}

#[derive(Deserialize)]
struct LifecycleStatus {
    schema: String,
    event: String,
    result: StatusResult,
}

#[derive(Deserialize)]
struct StatusResult {
    ready: bool,
    listener: bool,
    probe_connected: bool,
    host: String,
    port: u16,
}

pub enum PollResult {
    Running { probe_connected: bool },
    Exited,
}

#[derive(Clone)]
pub struct RemoteTarget {
    pub host: String,
    pub port: u16,
    pub token: String,
}

pub struct OwnedCore {
    child: Child,
    #[cfg(windows)]
    job: isize,
    root: PathBuf,
    config: SiteConfig,
    token: String,
    drains: Vec<thread::JoinHandle<()>>,
}

impl OwnedCore {
    pub fn remote_target(&self) -> RemoteTarget {
        RemoteTarget {
            host: self.config.bind_host.clone(),
            port: self.config.port,
            token: self.token.clone(),
        }
    }

    pub fn has_exited(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(Some(_)))
    }

    pub fn start(
        root: &Path,
        config: &SiteConfig,
        token: &str,
        stcp_credentials: Option<&crate::secret::StcpCredentials>,
        logs: Arc<Mutex<crate::log_store::LogStore>>,
    ) -> Result<(Self, String, bool), String> {
        let executable = runtime_executable(root);
        if !executable.is_file() {
            return Err("现场代理运行时缺失：bin/mklink-remote-agent.exe".into());
        }
        let ready = ready_path(root);
        let _ = std::fs::remove_file(&ready);
        crate::network::ensure_port_available(&config.bind_host, config.port)?;
        let mut command = Command::new(&executable);
        command
            .arg("start")
            .arg("--host")
            .arg(&config.bind_host)
            .arg("--port")
            .arg(config.port.to_string())
            .arg("--project-root")
            .arg(&config.project_root)
            .arg("--ready-file")
            .arg(&ready)
            .env(TOKEN_ENV, token)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if config.allow_lan {
            command.arg("--allow-lan");
        }
        if config.transport == "lan-stcp" {
            let credentials = stcp_credentials
                .ok_or_else(|| "LAN STCP credentials are unavailable".to_string())?;
            command
                .arg("--transport")
                .arg("lan-stcp")
                .arg("--stcp-server-addr")
                .arg(&config.stcp_server_addr)
                .arg("--stcp-server-port")
                .arg(config.stcp_server_port.to_string())
                .arg("--stcp-user")
                .arg(&config.stcp_user)
                .arg("--stcp-proxy-name")
                .arg(&config.stcp_proxy_name)
                .env(STCP_AUTH_ENV, &credentials.auth_token)
                .env(STCP_SECRET_ENV, &credentials.secret_key);
        }
        #[cfg(windows)]
        command.creation_flags(CREATE_NO_WINDOW);
        let mut child = command.spawn().map_err(|_| "无法启动现场代理运行时".to_string())?;
        #[cfg(windows)]
        let job = match create_kill_job(&child) {
            Ok(job) => job,
            Err(error) => {
                // Dropping Child does not terminate it. Keep spawn + Job handoff
                // transactional so a failed handoff cannot leave a listener.
                let _ = child.kill();
                let _ = reap_child_bounded(&mut child, FORCE_REAP_TIMEOUT);
                let _ = std::fs::remove_file(&ready);
                return Err(error);
            }
        };

        let mut drains = Vec::with_capacity(2);
        let stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                abort_start(&mut child, job, &ready, drains);
                return Err("Unable to capture Site Agent output".into());
            }
        };
        let target = logs.clone();
        match thread::Builder::new()
            .name("mklink-core-stdout".into())
            .spawn(move || {
                for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    log(&target, format!("[core] {line}"));
                }
            })
        {
            Ok(handle) => drains.push(handle),
            Err(_) => {
                abort_start(&mut child, job, &ready, drains);
                return Err("Unable to create Site Agent output drain".into());
            }
        }
        let stderr = match child.stderr.take() {
            Some(stderr) => stderr,
            None => {
                abort_start(&mut child, job, &ready, drains);
                return Err("Unable to capture Site Agent diagnostics".into());
            }
        };
        let target = logs;
        match thread::Builder::new()
            .name("mklink-core-stderr".into())
            .spawn(move || {
                for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    log(&target, format!("[core:error] {line}"));
                }
            })
        {
            Ok(handle) => drains.push(handle),
            Err(_) => {
                abort_start(&mut child, job, &ready, drains);
                return Err("Unable to create Site Agent diagnostic drain".into());
            }
        }

        let deadline = Instant::now() + Duration::from_secs(12);
        let readiness = loop {
            if let Ok(data) = std::fs::read(&ready) {
                if let Ok(value) = serde_json::from_slice::<ReadyFile>(&data) {
                    if value.ready
                        && value.schema == "mklink.site-agent.lifecycle.v1"
                        && value.event == "ready"
                        && value.pid == child.id()
                        && value.host == config.bind_host
                        && value.port == config.port
                        && value.transport == config.transport
                        && value.tunnel_ready
                    {
                        break Ok(value);
                    }
                }
            }
            if let Ok(Some(_)) = child.try_wait() {
                break Err("现场代理在就绪前退出".to_string());
            }
            if Instant::now() >= deadline {
                break Err("等待现场代理就绪超时".to_string());
            }
            thread::sleep(Duration::from_millis(100));
        };
        let readiness = match readiness {
            Ok(value) => value,
            Err(error) => {
                abort_start(&mut child, job, &ready, drains);
                return Err(error);
            }
        };
        let health = match authenticated_health(
            &executable,
            &readiness.host,
            readiness.port,
            token,
        ) {
            Ok(health) if health.ready && health.listener => health,
            Ok(_) => {
                let error = "Site Agent authenticated health is not ready".to_string();
                abort_start(&mut child, job, &ready, drains);
                return Err(error);
            }
            Err(error) => {
                abort_start(&mut child, job, &ready, drains);
                return Err(error);
            }
        };
        let endpoint = format_endpoint(config, &readiness.host, readiness.port);
        Ok((
            Self {
                child,
                #[cfg(windows)]
                job,
                root: root.to_path_buf(),
                config: config.clone(),
                token: token.to_owned(),
                drains,
            },
            endpoint,
            health.probe_connected || readiness.probe_connected,
        ))
    }

    pub fn stop(mut self) {
        let executable = runtime_executable(&self.root);
        let arguments = vec![
            "stop".to_string(),
            "--host".to_string(),
            self.config.bind_host.clone(),
            "--port".to_string(),
            self.config.port.to_string(),
            "--timeout".to_string(),
            "2".to_string(),
        ];
        let _ = crate::token_helper::run(&executable, &arguments, &self.token);
        let deadline = Instant::now() + Duration::from_secs(10);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                #[cfg(windows)]
                {
                    close_job(self.job);
                    self.job = 0;
                }
                join_drains_bounded(&mut self.drains, DRAIN_FINISH_TIMEOUT);
                let _ = std::fs::remove_file(ready_path(&self.root));
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = self.child.kill();
        #[cfg(windows)]
        {
            close_job(self.job);
            self.job = 0;
        }
        let terminated = reap_child_bounded(&mut self.child, FORCE_REAP_TIMEOUT);
        if terminated {
            join_drains_bounded(&mut self.drains, DRAIN_FINISH_TIMEOUT);
        } else {
            self.drains.clear();
        }
        let _ = std::fs::remove_file(ready_path(&self.root));
    }

    pub fn poll(&mut self) -> Result<PollResult, String> {
        if matches!(self.child.try_wait(), Ok(Some(_))) {
            let _ = std::fs::remove_file(ready_path(&self.root));
            #[cfg(windows)]
            {
                close_job(self.job);
                self.job = 0;
            }
            join_drains_bounded(&mut self.drains, DRAIN_FINISH_TIMEOUT);
            return Ok(PollResult::Exited);
        }
        let status = crate::remote_control::status(
            &self.config.bind_host,
            self.config.port,
            &self.token,
        )?;
        if !status.ready
            || !status.listener
            || status.host != self.config.bind_host
            || status.port != self.config.port
        {
            return Err("Authenticated Site Agent status identity is invalid".into());
        }
        Ok(PollResult::Running {
            probe_connected: status.probe_connected,
        })
    }

}

impl Drop for OwnedCore {
    fn drop(&mut self) {
        let mut terminated = matches!(self.child.try_wait(), Ok(Some(_)));
        if !terminated {
            let _ = self.child.kill();
        }
        #[cfg(windows)]
        {
            close_job(self.job);
            self.job = 0;
        }
        if !terminated {
            terminated = reap_child_bounded(&mut self.child, Duration::ZERO);
        }
        if terminated {
            join_drains_bounded(&mut self.drains, Duration::ZERO);
        } else {
            self.drains.clear();
        }
        let _ = std::fs::remove_file(ready_path(&self.root));
    }
}

fn runtime_executable(root: &Path) -> PathBuf {
    root.join("bin").join("mklink-remote-agent.exe")
}

#[cfg(windows)]
fn abort_start(
    child: &mut Child,
    job: isize,
    ready: &Path,
    mut drains: Vec<thread::JoinHandle<()>>,
) {
    let _ = child.kill();
    close_job(job);
    let terminated = reap_child_bounded(child, FORCE_REAP_TIMEOUT);
    if terminated {
        join_drains_bounded(&mut drains, DRAIN_FINISH_TIMEOUT);
    } else {
        drains.clear();
    }
    let _ = std::fs::remove_file(ready);
}

#[cfg(windows)]
fn reap_child_bounded(child: &mut Child, timeout: Duration) -> bool {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
    use windows_sys::Win32::System::Threading::WaitForSingleObject;

    if matches!(child.try_wait(), Ok(Some(_))) {
        return true;
    }
    let timeout_ms = timeout.as_millis().min(u32::MAX as u128) as u32;
    if unsafe { WaitForSingleObject(child.as_raw_handle() as _, timeout_ms) } == WAIT_OBJECT_0 {
        let _ = child.try_wait();
        true
    } else {
        false
    }
}

#[cfg(not(windows))]
fn reap_child_bounded(child: &mut Child, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn join_drains_bounded(drains: &mut Vec<thread::JoinHandle<()>>, timeout: Duration) {
    let deadline = Instant::now() + timeout;
    while drains.iter().any(|drain| !drain.is_finished()) && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    for drain in drains.drain(..) {
        if drain.is_finished() {
            let _ = drain.join();
        }
    }
}

fn format_endpoint(config: &SiteConfig, host: &str, port: u16) -> String {
    if config.transport == "lan-stcp" {
        return format!(
            "stcp://{}@{}:{}",
            config.stcp_proxy_name,
            config.stcp_server_addr,
            config.stcp_server_port
        );
    }
    if host.contains(':') {
        format!("ws://[{host}]:{port}")
    } else {
        format!("ws://{host}:{port}")
    }
}

fn authenticated_health(
    executable: &Path,
    host: &str,
    port: u16,
    token: &str,
) -> Result<HealthResult, String> {
    let arguments = vec![
        "health".to_string(),
        "--host".to_string(),
        host.to_string(),
        "--port".to_string(),
        port.to_string(),
        "--timeout".to_string(),
        "2".to_string(),
    ];
    let output = crate::token_helper::run(executable, &arguments, token)?;
    if !output.status.success() {
        return Err("Authenticated Site Agent health check failed".into());
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let line = stdout
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .ok_or_else(|| "Authenticated Site Agent health response is empty".to_string())?;
    let response: LifecycleHealth = serde_json::from_str(line)
        .map_err(|_| "Authenticated Site Agent health response is invalid".to_string())?;
    if response.schema != "mklink.site-agent.lifecycle.v1" || response.event != "health" {
        return Err("Authenticated Site Agent health identity is invalid".into());
    }
    Ok(response.result)
}

fn authenticated_status(
    executable: &Path,
    host: &str,
    port: u16,
    token: &str,
) -> Result<StatusResult, String> {
    let arguments = vec![
        "status".to_string(),
        "--host".to_string(),
        host.to_string(),
        "--port".to_string(),
        port.to_string(),
        "--timeout".to_string(),
        "2".to_string(),
    ];
    let output = crate::token_helper::run(executable, &arguments, token)?;
    if !output.status.success() {
        return Err("Authenticated Site Agent status check failed".into());
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let line = stdout
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .ok_or_else(|| "Authenticated Site Agent status response is empty".to_string())?;
    let response: LifecycleStatus = serde_json::from_str(line)
        .map_err(|_| "Authenticated Site Agent status response is invalid".to_string())?;
    if response.schema != "mklink.site-agent.lifecycle.v1" || response.event != "status" {
        return Err("Authenticated Site Agent status identity is invalid".into());
    }
    Ok(response.result)
}

#[cfg(windows)]
fn create_kill_job(child: &Child) -> Result<isize, String> {
    use std::os::windows::io::AsRawHandle;
    use std::ptr::null;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    let job = unsafe { CreateJobObjectW(null(), null()) };
    if job.is_null() {
        return Err("无法创建现场代理 Job Object".into());
    }
    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    let configured = unsafe {
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const _,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    };
    if configured == 0 {
        unsafe { CloseHandle(job) };
        return Err("failed to configure Site Agent Job Object".into());
    }
    let assigned = unsafe { AssignProcessToJobObject(job, child.as_raw_handle() as _) };
    if assigned == 0 {
        unsafe { CloseHandle(job) };
        return Err("无法约束现场代理子进程".into());
    }
    Ok(job as isize)
}

#[cfg(windows)]
fn close_job(job: isize) {
    use windows_sys::Win32::Foundation::CloseHandle;
    if job != 0 {
        unsafe { CloseHandle(job as _) };
    }
}
