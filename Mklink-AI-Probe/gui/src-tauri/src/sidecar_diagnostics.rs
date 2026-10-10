//! Bounded output for a desktop-owned proxy, including frozen startup failures.
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;
use std::sync::{Arc, Mutex};

const LIMIT: u64 = 256 * 1024;

pub fn open(path: &Path) -> std::io::Result<Arc<Mutex<File>>> {
    OpenOptions::new().create(true).truncate(true).write(true).open(path)
        .map(|file| Arc::new(Mutex::new(file)))
}

fn append(file: &mut File, bytes: &[u8], limit: u64) -> std::io::Result<()> {
    if file.stream_position()? + bytes.len() as u64 > limit {
        file.set_len(0)?;
        file.seek(SeekFrom::Start(0))?;
    }
    file.write_all(bytes)?;
    file.flush()
}

pub fn drain(reader: impl Read + Send + 'static, log: Arc<Mutex<File>>) {
    std::thread::spawn(move || {
        let mut reader = reader;
        let mut buffer = [0; 4096];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(count) => {
                    if let Ok(mut file) = log.lock() {
                        // Keep draining even if storage is unavailable: logging
                        // must not block or crash the proxy when its pipe fills.
                        let _ = append(&mut file, &buffer[..count], LIMIT);
                    }
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn retains_recent_diagnostics_with_bounded_storage() {
        let path = std::env::temp_dir().join(format!("mklink-diagnostic-{}.log", rand::random::<u128>()));
        let log = open(&path).unwrap();
        {
            let mut file = log.lock().unwrap();
            for _ in 0..100 { append(&mut file, b"old\n", 32).unwrap(); }
            append(&mut file, b"startup failed: 31\n", 32).unwrap();
        }
        drop(log);
        let data = std::fs::read(&path).unwrap();
        assert!(data.len() <= 32);
        assert!(data.ends_with(b"startup failed: 31\n"));
        std::fs::remove_file(path).unwrap();
    }
}
