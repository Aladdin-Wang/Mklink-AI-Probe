use std::io::Read;
use std::path::Path;
use std::process::{Command, ExitStatus, Stdio};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const TOKEN_ENV: &str = "MKLINK_REMOTE_TOKEN";
const HARD_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_CAPTURE: usize = 64 * 1024;

pub struct HelperOutput {
    pub status: ExitStatus,
    pub stdout: Vec<u8>,
}

pub fn run(
    executable: &Path,
    arguments: &[String],
    token: &str,
) -> Result<HelperOutput, String> {
    let mut command = Command::new(executable);
    command
        .args(arguments)
        .env(TOKEN_ENV, token)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    let mut child = command
        .spawn()
        .map_err(|_| "Unable to start the bounded Site Agent helper".to_string())?;
    #[cfg(windows)]
    let mut job = match create_kill_job(&child) {
        Ok(job) => job,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };

    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            let _ = child.kill();
            #[cfg(windows)]
            close_job(job);
            let _ = child.wait();
            return Err("Unable to capture helper output".into());
        }
    };
    let stderr = match child.stderr.take() {
        Some(stderr) => stderr,
        None => {
            let _ = child.kill();
            #[cfg(windows)]
            close_job(job);
            let _ = child.wait();
            return Err("Unable to capture helper diagnostics".into());
        }
    };
    let stdout_reader = match thread::Builder::new()
        .name("mklink-helper-stdout".into())
        .spawn(move || read_bounded(stdout))
    {
        Ok(reader) => reader,
        Err(_) => {
            let _ = child.kill();
            #[cfg(windows)]
            close_job(job);
            let _ = child.wait();
            return Err("Unable to create the helper output drain".into());
        }
    };
    let stderr_reader = match thread::Builder::new()
        .name("mklink-helper-stderr".into())
        .spawn(move || read_bounded(stderr))
    {
        Ok(reader) => reader,
        Err(_) => {
            let _ = child.kill();
            #[cfg(windows)]
            close_job(job);
            let _ = child.wait();
            let _ = stdout_reader.join();
            return Err("Unable to create the helper diagnostic drain".into());
        }
    };

    let deadline = Instant::now() + HARD_TIMEOUT;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(25)),
            Ok(None) => break Err("Site Agent helper exceeded its hard timeout".to_string()),
            Err(_) => break Err("Unable to observe the Site Agent helper".to_string()),
        }
    };

    let status = match status {
        Ok(status) => status,
        Err(error) => {
            let _ = child.kill();
            #[cfg(windows)]
            {
                close_job(job);
                job = 0;
            }
            let _ = child.wait();
            let _ = stdout_reader.join();
            let _ = stderr_reader.join();
            return Err(error);
        }
    };
    #[cfg(windows)]
    {
        close_job(job);
        job = 0;
        let _ = job;
    }
    let stdout = stdout_reader
        .join()
        .map_err(|_| "Unable to collect helper output".to_string())?;
    let _stderr = stderr_reader
        .join()
        .map_err(|_| "Unable to collect helper diagnostics".to_string())?;
    Ok(HelperOutput { status, stdout })
}

fn read_bounded(mut stream: impl Read) -> Vec<u8> {
    let mut captured = Vec::new();
    let mut buffer = [0_u8; 4096];
    loop {
        match stream.read(&mut buffer) {
            Ok(0) | Err(_) => break,
            Ok(count) => {
                let remaining = MAX_CAPTURE.saturating_sub(captured.len());
                captured.extend_from_slice(&buffer[..count.min(remaining)]);
            }
        }
    }
    captured
}

#[cfg(windows)]
fn create_kill_job(child: &std::process::Child) -> Result<isize, String> {
    use std::os::windows::io::AsRawHandle;
    use std::ptr::null;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    let job = unsafe { CreateJobObjectW(null(), null()) };
    if job.is_null() {
        return Err("Unable to create the helper Job Object".into());
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
        return Err("Unable to configure the helper Job Object".into());
    }
    if unsafe { AssignProcessToJobObject(job, child.as_raw_handle() as _) } == 0 {
        unsafe { CloseHandle(job) };
        return Err("Unable to assign the helper Job Object".into());
    }
    Ok(job as isize)
}

#[cfg(windows)]
fn close_job(job: isize) {
    if job != 0 {
        unsafe { windows_sys::Win32::Foundation::CloseHandle(job as _) };
    }
}
