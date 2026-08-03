use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use rand::RngCore;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Serialize)]
pub struct SecretState {
    pub token_configured: bool,
    pub token_fingerprint: Option<String>,
    pub stcp_credentials_configured: bool,
}

#[derive(Serialize)]
pub struct TokenResult {
    pub configured: bool,
    pub fingerprint: String,
    pub copied: bool,
}

pub struct StcpCredentials {
    pub auth_token: String,
    pub secret_key: String,
}

fn token_path(root: &Path) -> PathBuf {
    root.join("token.bin")
}

fn stcp_auth_path(root: &Path) -> PathBuf {
    root.join("stcp-auth.bin")
}

fn stcp_secret_path(root: &Path) -> PathBuf {
    root.join("stcp-secret.bin")
}

pub fn configured(root: &Path) -> bool {
    token_path(root).is_file()
}

pub fn stcp_configured(root: &Path) -> bool {
    stcp_auth_path(root).is_file() && stcp_secret_path(root).is_file()
}

pub fn load(root: &Path) -> Result<String, String> {
    let encrypted = fs::read(token_path(root))
        .map_err(|_| "The Site Agent access token is not configured".to_string())?;
    String::from_utf8(dpapi_unprotect(&encrypted)?)
        .map_err(|_| "The Site Agent access token is invalid".to_string())
}

pub fn load_stcp(root: &Path) -> Result<StcpCredentials, String> {
    let auth = fs::read(stcp_auth_path(root))
        .map_err(|_| "LAN STCP authentication is not configured".to_string())?;
    let secret = fs::read(stcp_secret_path(root))
        .map_err(|_| "LAN STCP secret is not configured".to_string())?;
    Ok(StcpCredentials {
        auth_token: String::from_utf8(dpapi_unprotect(&auth)?)
            .map_err(|_| "LAN STCP authentication is invalid".to_string())?,
        secret_key: String::from_utf8(dpapi_unprotect(&secret)?)
            .map_err(|_| "LAN STCP secret is invalid".to_string())?,
    })
}

pub fn state(root: &Path) -> SecretState {
    let token = load(root).ok();
    SecretState {
        token_configured: token.is_some(),
        token_fingerprint: token.as_deref().map(fingerprint),
        stcp_credentials_configured: load_stcp(root).is_ok(),
    }
}

pub fn generate_and_copy(root: &Path) -> Result<TokenResult, String> {
    let mut random = [0_u8; 32];
    rand::thread_rng().fill_bytes(&mut random);
    let token = URL_SAFE_NO_PAD.encode(random);
    let encrypted = dpapi_protect(token.as_bytes())?;
    let destination = token_path(root);
    let previous = fs::read(&destination).ok();
    write_ciphertext(root, &destination, &encrypted)?;
    if let Err(error) = set_clipboard(&token) {
        let _ = restore_ciphertext(root, &destination, previous.as_deref());
        return Err(error);
    }
    Ok(TokenResult {
        configured: true,
        fingerprint: fingerprint(&token),
        copied: true,
    })
}

pub fn store_stcp(root: &Path, auth_token: &str, secret_key: &str) -> Result<(), String> {
    let site_token = load(root)?;
    if auth_token.is_empty()
        || secret_key.is_empty()
        || auth_token == secret_key
        || auth_token == site_token
        || secret_key == site_token
    {
        return Err("Site Agent, FRP authentication, and STCP credentials must be distinct".into());
    }
    let auth = dpapi_protect(auth_token.as_bytes())?;
    let secret = dpapi_protect(secret_key.as_bytes())?;
    let previous_auth = fs::read(stcp_auth_path(root)).ok();
    let previous_secret = fs::read(stcp_secret_path(root)).ok();
    write_ciphertext(root, &stcp_auth_path(root), &auth)?;
    if let Err(error) = write_ciphertext(root, &stcp_secret_path(root), &secret) {
        let _ = restore_ciphertext(root, &stcp_auth_path(root), previous_auth.as_deref());
        let _ = restore_ciphertext(root, &stcp_secret_path(root), previous_secret.as_deref());
        return Err(error);
    }
    Ok(())
}

fn restore_ciphertext(
    root: &Path,
    destination: &Path,
    previous: Option<&[u8]>,
) -> Result<(), String> {
    match previous {
        Some(value) => write_ciphertext(root, destination, value),
        None => match fs::remove_file(destination) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err("Unable to restore the previous Site Agent credential".into()),
        },
    }
}

fn fingerprint(token: &str) -> String {
    let digest = Sha256::digest(token.as_bytes());
    digest[..4]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn write_ciphertext(root: &Path, destination: &Path, value: &[u8]) -> Result<(), String> {
    fs::create_dir_all(root)
        .map_err(|_| "Unable to create the Site Agent credential directory".to_string())?;
    let temporary = destination.with_extension(format!("tmp-{}", std::process::id()));
    fs::write(&temporary, value)
        .map_err(|_| "Unable to stage the Site Agent credential".to_string())?;
    replace_secret(&temporary, destination)
}

#[cfg(windows)]
fn dpapi_protect(plaintext: &[u8]) -> Result<Vec<u8>, String> {
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let mut input = CRYPT_INTEGER_BLOB {
        cbData: plaintext.len() as u32,
        pbData: plaintext.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: null_mut(),
    };
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
        return Err("Windows could not protect the Site Agent credential".into());
    }
    let result =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { LocalFree(output.pbData.cast()) };
    Ok(result)
}

#[cfg(windows)]
fn dpapi_unprotect(encrypted: &[u8]) -> Result<Vec<u8>, String> {
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let mut input = CRYPT_INTEGER_BLOB {
        cbData: encrypted.len() as u32,
        pbData: encrypted.as_ptr() as *mut u8,
    };
    let mut output = CRYPT_INTEGER_BLOB {
        cbData: 0,
        pbData: null_mut(),
    };
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
        return Err("The Site Agent credential cannot be decrypted by this Windows user".into());
    }
    let result =
        unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { LocalFree(output.pbData.cast()) };
    Ok(result)
}

#[cfg(not(windows))]
fn dpapi_protect(_plaintext: &[u8]) -> Result<Vec<u8>, String> {
    Err("DPAPI credential storage is available only on Windows".into())
}

#[cfg(not(windows))]
fn dpapi_unprotect(_encrypted: &[u8]) -> Result<Vec<u8>, String> {
    Err("DPAPI credential storage is available only on Windows".into())
}

#[cfg(windows)]
fn replace_secret(source: &Path, destination: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    if unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        let _ = fs::remove_file(source);
        return Err("Unable to save the Site Agent credential".into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace_secret(source: &Path, destination: &Path) -> Result<(), String> {
    if destination.exists() {
        fs::remove_file(destination)
            .map_err(|_| "Unable to replace the Site Agent credential".to_string())?;
    }
    fs::rename(source, destination)
        .map_err(|_| "Unable to save the Site Agent credential".to_string())
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
            return Err("Unable to open the Windows clipboard".into());
        }
        if EmptyClipboard() == 0 {
            CloseClipboard();
            return Err("Unable to clear the Windows clipboard".into());
        }
        let handle = GlobalAlloc(GMEM_MOVEABLE, wide.len() * 2);
        if handle.is_null() {
            CloseClipboard();
            return Err("Unable to allocate clipboard memory".into());
        }
        let target = GlobalLock(handle) as *mut u16;
        if target.is_null() {
            GlobalFree(handle);
            CloseClipboard();
            return Err("Unable to lock clipboard memory".into());
        }
        copy_nonoverlapping(wide.as_ptr(), target, wide.len());
        GlobalUnlock(handle);
        if SetClipboardData(CF_UNICODETEXT, handle).is_null() {
            GlobalFree(handle);
            CloseClipboard();
            return Err("Unable to write the Windows clipboard".into());
        }
        CloseClipboard();
    }
    Ok(())
}

#[cfg(not(windows))]
fn set_clipboard(_text: &str) -> Result<(), String> {
    Err("Clipboard token provisioning is available only on Windows".into())
}
