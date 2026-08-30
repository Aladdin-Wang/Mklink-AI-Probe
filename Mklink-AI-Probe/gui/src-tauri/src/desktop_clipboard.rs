#[cfg(target_os = "windows")]
struct ClipboardGuard;

#[cfg(target_os = "windows")]
impl ClipboardGuard {
    fn open() -> Result<Self, String> {
        use windows_sys::Win32::System::DataExchange::OpenClipboard;

        for attempt in 0..10 {
            if unsafe { OpenClipboard(std::ptr::null_mut()) } != 0 {
                return Ok(Self);
            }
            if attempt < 9 {
                std::thread::sleep(std::time::Duration::from_millis(5));
            }
        }
        Err("Unable to open the Windows clipboard".into())
    }
}

#[cfg(target_os = "windows")]
impl Drop for ClipboardGuard {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::System::DataExchange::CloseClipboard();
        }
    }
}

#[cfg(target_os = "windows")]
struct GlobalUnlockGuard(*mut std::ffi::c_void);

#[cfg(target_os = "windows")]
impl Drop for GlobalUnlockGuard {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::System::Memory::GlobalUnlock(self.0);
        }
    }
}

#[cfg(target_os = "windows")]
struct GlobalMemory(*mut std::ffi::c_void);

#[cfg(target_os = "windows")]
impl Drop for GlobalMemory {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::GlobalFree(self.0);
        }
    }
}

#[cfg(target_os = "windows")]
pub fn read_text() -> Result<String, String> {
    use std::slice;
    use windows_sys::Win32::System::DataExchange::{GetClipboardData, IsClipboardFormatAvailable};
    use windows_sys::Win32::System::Memory::{GlobalLock, GlobalSize};

    const CF_UNICODETEXT: u32 = 13;
    let _clipboard = ClipboardGuard::open()?;
    unsafe {
        if IsClipboardFormatAvailable(CF_UNICODETEXT) == 0 {
            return Ok(String::new());
        }
        let handle = GetClipboardData(CF_UNICODETEXT);
        if handle.is_null() {
            return Err("Unable to read text from the Windows clipboard".into());
        }
        let size = GlobalSize(handle);
        if size < std::mem::size_of::<u16>() {
            return Err("The Windows clipboard contains invalid text".into());
        }
        let source = GlobalLock(handle) as *const u16;
        if source.is_null() {
            return Err("Unable to lock the Windows clipboard".into());
        }
        let _locked = GlobalUnlockGuard(handle);
        let units = slice::from_raw_parts(source, size / std::mem::size_of::<u16>());
        let length = units
            .iter()
            .position(|unit| *unit == 0)
            .unwrap_or(units.len());
        String::from_utf16(&units[..length])
            .map_err(|_| "The Windows clipboard contains invalid text".to_string())
    }
}

#[cfg(target_os = "windows")]
pub fn write_text(text: &str) -> Result<(), String> {
    use std::ptr::copy_nonoverlapping;
    use windows_sys::Win32::System::DataExchange::{EmptyClipboard, SetClipboardData};
    use windows_sys::Win32::System::Memory::{GlobalAlloc, GlobalLock, GMEM_MOVEABLE};

    const CF_UNICODETEXT: u32 = 13;
    let mut wide: Vec<u16> = text.encode_utf16().collect();
    wide.push(0);
    unsafe {
        let memory = GlobalMemory(GlobalAlloc(
            GMEM_MOVEABLE,
            wide.len() * std::mem::size_of::<u16>(),
        ));
        if memory.0.is_null() {
            return Err("Unable to allocate clipboard memory".into());
        }
        let target = GlobalLock(memory.0) as *mut u16;
        if target.is_null() {
            return Err("Unable to lock clipboard memory".into());
        }
        {
            let _locked = GlobalUnlockGuard(memory.0);
            copy_nonoverlapping(wide.as_ptr(), target, wide.len());
        }

        let _clipboard = ClipboardGuard::open()?;
        if EmptyClipboard() == 0 {
            return Err("Unable to clear the Windows clipboard".into());
        }
        if SetClipboardData(CF_UNICODETEXT, memory.0).is_null() {
            return Err("Unable to write the Windows clipboard".into());
        }
        // SetClipboardData transfers ownership to the system on success.
        std::mem::forget(memory);
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
pub fn read_text() -> Result<String, String> {
    Err("Desktop clipboard access is available only on Windows".into())
}

#[cfg(not(target_os = "windows"))]
pub fn write_text(_text: &str) -> Result<(), String> {
    Err("Desktop clipboard access is available only on Windows".into())
}
