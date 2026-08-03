use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use rand::RngCore;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
pub struct TokenResult {
    pub configured: bool,
    pub fingerprint: String,
    pub copied: bool,
}

pub struct PreparedToken {
    pub token: String,
    encrypted: Vec<u8>,
    fingerprint: String,
}

pub struct StcpCredentials {
    pub auth_token: String,
    pub secret_key: String,
}

impl PreparedToken {
    pub fn result(&self) -> TokenResult {
        TokenResult {
            configured: true,
            fingerprint: self.fingerprint.clone(),
            copied: true,
        }
    }
}

pub fn secret_path(root: &Path) -> PathBuf {
    root.join("data").join("secret.bin")
}

fn stcp_auth_path(root: &Path) -> PathBuf {
    root.join("data").join("stcp-auth.bin")
}

fn stcp_secret_path(root: &Path) -> PathBuf {
    root.join("data").join("stcp-secret.bin")
}

pub fn configured(root: &Path) -> bool {
    secret_path(root).is_file()
}

pub fn stcp_configured(root: &Path) -> bool {
    stcp_auth_path(root).is_file() && stcp_secret_path(root).is_file()
}

pub fn load(root: &Path) -> Result<String, String> {
    let encrypted = fs::read(secret_path(root)).map_err(|_| "尚未配置访问令牌".to_string())?;
    let plaintext = dpapi_unprotect(&encrypted)?;
    String::from_utf8(plaintext).map_err(|_| "访问令牌密文无效".to_string())
}

pub fn load_stcp(root: &Path) -> Result<StcpCredentials, String> {
    let auth_encrypted = fs::read(stcp_auth_path(root))
        .map_err(|_| "LAN STCP authentication token is not configured".to_string())?;
    let secret_encrypted = fs::read(stcp_secret_path(root))
        .map_err(|_| "LAN STCP secret is not configured".to_string())?;
    let auth_token = String::from_utf8(dpapi_unprotect(&auth_encrypted)?)
        .map_err(|_| "LAN STCP authentication ciphertext is invalid".to_string())?;
    let secret_key = String::from_utf8(dpapi_unprotect(&secret_encrypted)?)
        .map_err(|_| "LAN STCP secret ciphertext is invalid".to_string())?;
    Ok(StcpCredentials {
        auth_token,
        secret_key,
    })
}

pub fn store_stcp(
    root: &Path,
    auth_token: &str,
    secret_key: &str,
) -> Result<(), String> {
    if auth_token.is_empty() || secret_key.is_empty() || auth_token == secret_key {
        return Err("FRP authentication token and STCP secret must be distinct".into());
    }
    let auth_encrypted = dpapi_protect(auth_token.as_bytes())?;
    let secret_encrypted = dpapi_protect(secret_key.as_bytes())?;
    let auth_path = stcp_auth_path(root);
    let secret_path = stcp_secret_path(root);
    let previous_auth = fs::read(&auth_path).ok();
    let previous_secret = fs::read(&secret_path).ok();
    write_ciphertext_to(root, &auth_path, &auth_encrypted)?;
    if let Err(error) = write_ciphertext_to(root, &secret_path, &secret_encrypted) {
        let _ = restore_named_ciphertext(root, &auth_path, previous_auth.as_deref());
        let _ = restore_named_ciphertext(root, &secret_path, previous_secret.as_deref());
        return Err(error);
    }
    Ok(())
}

pub fn fingerprint(root: &Path) -> Option<String> {
    load(root).ok().map(|token| token_fingerprint(&token))
}

pub fn prepare() -> Result<PreparedToken, String> {
    let mut random = [0_u8; 32];
    rand::thread_rng().fill_bytes(&mut random);
    let token = URL_SAFE_NO_PAD.encode(random);
    let encrypted = dpapi_protect(token.as_bytes())?;
    let fingerprint = token_fingerprint(&token);
    Ok(PreparedToken {
        token,
        encrypted,
        fingerprint,
    })
}

pub fn copy_prepared(prepared: &PreparedToken) -> Result<(), String> {
    set_clipboard(&prepared.token)
}

pub fn commit(root: &Path, prepared: &PreparedToken) -> Result<(), String> {
    write_ciphertext(root, &prepared.encrypted)
}

pub fn current_ciphertext(root: &Path) -> Result<Option<Vec<u8>>, String> {
    match fs::read(secret_path(root)) {
        Ok(value) => Ok(Some(value)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(_) => Err("Unable to back up the current access credential".into()),
    }
}

pub fn restore_ciphertext(root: &Path, previous: Option<&[u8]>) -> Result<(), String> {
    match previous {
        Some(value) => write_ciphertext(root, value),
        None => match fs::remove_file(secret_path(root)) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err("Unable to restore the previous access credential".into()),
        },
    }
}

fn write_ciphertext(root: &Path, encrypted: &[u8]) -> Result<(), String> {
    write_ciphertext_to(root, &secret_path(root), encrypted)
}

fn write_ciphertext_to(
    root: &Path,
    destination: &Path,
    encrypted: &[u8],
) -> Result<(), String> {
    fs::create_dir_all(root.join("data"))
        .map_err(|_| "Portable data directory is not writable".to_string())?;
    let temporary = destination.with_extension(format!("tmp-{}", std::process::id()));
    fs::write(&temporary, encrypted)
        .map_err(|_| "Unable to stage access credential".to_string())?;
    replace_secret(&temporary, destination)
}

fn restore_named_ciphertext(
    root: &Path,
    destination: &Path,
    previous: Option<&[u8]>,
) -> Result<(), String> {
    match previous {
        Some(value) => write_ciphertext_to(root, destination, value),
        None => match fs::remove_file(destination) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err("Unable to restore previous STCP credentials".into()),
        },
    }
}

fn token_fingerprint(token: &str) -> String {
    let digest = Sha256::digest(token.as_bytes());
    digest[..4].iter().map(|byte| format!("{byte:02x}")).collect()
}

#[cfg(all(test, windows))]
mod tests {
    use super::{load_stcp, store_stcp};
    use std::fs;

    #[test]
    fn stcp_credentials_round_trip_through_dpapi_without_plaintext_files() {
        let root = std::env::temp_dir().join(format!(
            "mklink-site-agent-stcp-secret-test-{}-{}",
            std::process::id(),
            rand::random::<u64>(),
        ));
        fs::create_dir(&root).expect("create isolated test root");
        let auth = "test-frps-auth-token";
        let secret = "test-stcp-secret-key";

        let result = (|| {
            store_stcp(&root, auth, secret)?;
            let loaded = load_stcp(&root)?;
            assert_eq!(loaded.auth_token, auth);
            assert_eq!(loaded.secret_key, secret);

            for path in [
                root.join("data").join("stcp-auth.bin"),
                root.join("data").join("stcp-secret.bin"),
            ] {
                let ciphertext = fs::read(path).expect("read DPAPI ciphertext");
                assert!(!ciphertext.windows(auth.len()).any(|part| part == auth.as_bytes()));
                assert!(
                    !ciphertext
                        .windows(secret.len())
                        .any(|part| part == secret.as_bytes())
                );
            }
            Ok::<(), String>(())
        })();
        let cleanup = fs::remove_dir_all(&root);

        result.expect("store and load STCP credentials");
        cleanup.expect("remove isolated test root");
    }

    #[test]
    fn stcp_credentials_reject_empty_or_reused_values() {
        let root = std::env::temp_dir();
        assert!(store_stcp(&root, "", "secret").is_err());
        assert!(store_stcp(&root, "same", "same").is_err());
    }
}

#[cfg(windows)]
fn dpapi_protect(plaintext: &[u8]) -> Result<Vec<u8>, String> {
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN,
    };
    let mut input = CRYPT_INTEGER_BLOB {
        cbData: plaintext.len() as u32,
        pbData: plaintext.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB { cbData: 0, pbData: null_mut() };
    let ok = unsafe {
        CryptProtectData(
            &mut input,
            null(),
            null(),
            null_mut(),
            null_mut(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err("Windows 无法保护访问令牌".into());
    }
    let result = unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { LocalFree(output.pbData.cast()) };
    Ok(result)
}

#[cfg(windows)]
fn dpapi_unprotect(encrypted: &[u8]) -> Result<Vec<u8>, String> {
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptUnprotectData, CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN,
    };
    let mut input = CRYPT_INTEGER_BLOB {
        cbData: encrypted.len() as u32,
        pbData: encrypted.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB { cbData: 0, pbData: null_mut() };
    let ok = unsafe {
        CryptUnprotectData(
            &mut input,
            null_mut(),
            null(),
            null_mut(),
            null_mut(),
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut output,
        )
    };
    if ok == 0 {
        return Err("访问令牌不属于当前 Windows 用户或密文已损坏".into());
    }
    let result = unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { LocalFree(output.pbData.cast()) };
    Ok(result)
}

#[cfg(not(windows))]
fn dpapi_protect(_plaintext: &[u8]) -> Result<Vec<u8>, String> {
    Err("DPAPI 仅支持 Windows".into())
}

#[cfg(not(windows))]
fn dpapi_unprotect(_encrypted: &[u8]) -> Result<Vec<u8>, String> {
    Err("DPAPI 仅支持 Windows".into())
}

#[cfg(windows)]
fn replace_secret(source: &Path, destination: &Path) -> Result<(), String> {
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
        return Err("无法原子保存访问令牌".into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace_secret(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        fs::remove_file(destination).map_err(|_| "无法保存访问令牌".to_string())?;
    }
    fs::rename(source, destination).map_err(|_| "无法保存访问令牌".to_string())
}

#[cfg(windows)]
fn set_clipboard(text: &str) -> Result<(), String> {
    use std::ptr::copy_nonoverlapping;
    use windows_sys::Win32::Foundation::GlobalFree;
    use windows_sys::Win32::System::DataExchange::{
        CloseClipboard, EmptyClipboard, OpenClipboard, SetClipboardData,
    };
    use windows_sys::Win32::System::Memory::{
        GlobalAlloc, GlobalLock, GlobalUnlock, GMEM_MOVEABLE,
    };
    let mut wide: Vec<u16> = text.encode_utf16().collect();
    wide.push(0);
    const CF_UNICODETEXT: u32 = 13;
    unsafe {
        if OpenClipboard(std::ptr::null_mut()) == 0 {
            return Err("无法打开 Windows 剪贴板".into());
        }
        if EmptyClipboard() == 0 {
            CloseClipboard();
            return Err("无法清空 Windows 剪贴板".into());
        }
        let handle = GlobalAlloc(GMEM_MOVEABLE, wide.len() * 2);
        if handle.is_null() {
            CloseClipboard();
            return Err("无法分配剪贴板内存".into());
        }
        let target = GlobalLock(handle) as *mut u16;
        if target.is_null() {
            GlobalFree(handle);
            CloseClipboard();
            return Err("无法锁定剪贴板内存".into());
        }
        copy_nonoverlapping(wide.as_ptr(), target, wide.len());
        GlobalUnlock(handle);
        if SetClipboardData(CF_UNICODETEXT, handle).is_null() {
            GlobalFree(handle);
            CloseClipboard();
            return Err("无法写入 Windows 剪贴板".into());
        }
        CloseClipboard();
    }
    Ok(())
}

#[cfg(not(windows))]
fn set_clipboard(_text: &str) -> Result<(), String> {
    Err("剪贴板操作仅支持 Windows".into())
}
