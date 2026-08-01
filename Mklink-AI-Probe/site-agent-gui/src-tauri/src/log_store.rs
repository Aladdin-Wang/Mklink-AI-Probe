use std::collections::VecDeque;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use serde::Serialize;

const MAX_LINES: usize = 500;
const MAX_RESPONSE_BYTES: usize = 256 * 1024;
const ROTATE_BYTES: u64 = 512 * 1024;

pub struct LogStore {
    lines: VecDeque<(u64, String)>,
    cursor: u64,
    path: Option<PathBuf>,
    cursor_path: Option<PathBuf>,
    cursor_backup_path: Option<PathBuf>,
}

#[derive(Serialize)]
pub struct LogBatch {
    pub cursor: usize,
    pub lines: Vec<String>,
}

impl LogStore {
    pub fn new() -> Self {
        Self {
            lines: VecDeque::with_capacity(MAX_LINES),
            cursor: 0,
            path: None,
            cursor_path: None,
            cursor_backup_path: None,
        }
    }

    pub fn initialize(&mut self, root: &Path) -> Result<(), String> {
        let path = root.join("data").join("logs").join("site-agent.log");
        let cursor_path = root.join("data").join("logs").join("cursor");
        let cursor_backup_path = root.join("data").join("logs").join("cursor.backup");
        fs::create_dir_all(path.parent().unwrap_or(root))
            .map_err(|_| "Unable to create the portable log directory".to_string())?;
        self.cursor = [&cursor_path, &cursor_backup_path]
            .iter()
            .filter_map(|path| fs::read_to_string(path).ok())
            .filter_map(|value| value.trim().parse::<u64>().ok())
            .max()
            .unwrap_or_else(|| {
                [&path.with_extension("log.1"), &path]
                    .iter()
                    .filter_map(|path| fs::read_to_string(path).ok())
                    .map(|content| content.lines().count() as u64)
                    .sum()
            });
        if let Ok(content) = fs::read_to_string(&path) {
            let selected = content
                .lines()
                .rev()
                .take(MAX_LINES)
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect::<Vec<_>>();
            let first = self.cursor.saturating_sub(selected.len() as u64);
            for (index, line) in selected.into_iter().enumerate() {
                self.lines
                    .push_back((first + index as u64 + 1, line.chars().take(1000).collect()));
            }
        }
        self.path = Some(path);
        self.cursor_path = Some(cursor_path);
        self.cursor_backup_path = Some(cursor_backup_path);
        Ok(())
    }

    pub fn append(&mut self, message: impl Into<String>) {
        let sanitized = redact(&message.into());
        self.cursor = self.cursor.saturating_add(1);
        if self.lines.len() >= MAX_LINES {
            self.lines.pop_front();
        }
        self.lines.push_back((self.cursor, sanitized.clone()));
        if let Some(cursor_path) = self.cursor_path.as_ref() {
            let _ = atomic_write(cursor_path, self.cursor.to_string().as_bytes());
        }
        if let Some(cursor_backup_path) = self.cursor_backup_path.as_ref() {
            let _ = atomic_write(cursor_backup_path, self.cursor.to_string().as_bytes());
        }
        let Some(path) = self.path.as_ref() else {
            return;
        };
        if path.metadata().map(|value| value.len()).unwrap_or_default() >= ROTATE_BYTES {
            let rotated = path.with_extension("log.1");
            let _ = fs::remove_file(&rotated);
            let _ = fs::rename(path, rotated);
        }
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(file, "{sanitized}");
            let _ = file.flush();
        }
    }

    pub fn cursor(&self) -> usize {
        usize::try_from(self.cursor).unwrap_or(usize::MAX)
    }

    pub fn tail(&self, after: Option<usize>) -> LogBatch {
        let after = after
            .and_then(|value| u64::try_from(value).ok())
            .unwrap_or_default();
        let mut bytes: usize = 0;
        let mut result = Vec::new();
        for (cursor, line) in self.lines.iter().rev() {
            if *cursor <= after {
                continue;
            }
            let size = line.len().saturating_add(1);
            if bytes.saturating_add(size) > MAX_RESPONSE_BYTES {
                break;
            }
            bytes += size;
            result.push(line.clone());
        }
        result.reverse();
        LogBatch {
            cursor: self.cursor(),
            lines: result,
        }
    }
}

fn atomic_write(path: &Path, value: &[u8]) -> Result<(), String> {
    let temporary = path.with_extension(format!("tmp-{}", std::process::id()));
    {
        let mut file = fs::File::create(&temporary)
            .map_err(|_| "Unable to stage the log cursor".to_string())?;
        file.write_all(value)
            .map_err(|_| "Unable to write the log cursor".to_string())?;
        file.flush()
            .map_err(|_| "Unable to flush the log cursor".to_string())?;
        file.sync_all()
            .map_err(|_| "Unable to sync the log cursor".to_string())?;
    }
    replace_file(&temporary, path)
}

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination.as_os_str().encode_wide().chain(Some(0)).collect();
    if unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        let _ = fs::remove_file(source);
        return Err("Unable to atomically replace the log cursor".into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace_file(source: &Path, destination: &Path) -> Result<(), String> {
    fs::rename(source, destination)
        .map_err(|_| "Unable to atomically replace the log cursor".to_string())
}

fn redact(message: &str) -> String {
    let lowered = message.to_ascii_lowercase();
    if lowered.contains("token")
        || lowered.contains("authorization")
        || lowered.contains("password")
        || lowered.contains("secret")
        || lowered.contains("bearer ")
    {
        "[redacted sensitive lifecycle message]".into()
    } else {
        message.chars().take(1000).collect()
    }
}
