/// Native system-audio ducking for Jace speech.
///
/// On Windows this uses Core Audio session controls to lower every audio
/// session except Jace's own process tree. Original per-session volumes are
/// remembered and restored when speech ends.
///
/// On other platforms this is currently a harmless no-op so the desktop app
/// remains cross-platform buildable.
pub fn set_ducking(enabled: bool, factor: f32) -> Result<(), String> {
    #[cfg(windows)]
    {
        platform::set_ducking(enabled, factor)
    }

    #[cfg(not(windows))]
    {
        let _ = (enabled, factor);
        Ok(())
    }
}

#[cfg(windows)]
mod platform {
    use std::{
        collections::{HashMap, HashSet},
        ffi::c_void,
        mem::size_of,
        slice,
        sync::{Mutex, OnceLock},
    };

    use windows::{
        core::Interface,
        Win32::{
            Foundation::CloseHandle,
            Media::Audio::{
                eMultimedia, eRender, IAudioSessionControl2,
                IAudioSessionManager2, IMMDeviceEnumerator, ISimpleAudioVolume,
                MMDeviceEnumerator,
            },
            System::{
                Com::{
                    CoCreateInstance, CoInitializeEx, CoTaskMemFree,
                    CoUninitialize, CLSCTX_ALL, COINIT_MULTITHREADED,
                },
                Diagnostics::ToolHelp::{
                    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW,
                    PROCESSENTRY32W, TH32CS_SNAPPROCESS,
                },
            },
        },
    };

    #[derive(Clone, Copy, Debug)]
    struct OriginalSession {
        volume: f32,
    }

    static ORIGINAL_VOLUMES: OnceLock<Mutex<HashMap<String, OriginalSession>>> =
        OnceLock::new();

    fn volume_store() -> &'static Mutex<HashMap<String, OriginalSession>> {
        ORIGINAL_VOLUMES.get_or_init(|| Mutex::new(HashMap::new()))
    }

    struct ComGuard;

    impl ComGuard {
        fn initialise() -> Result<Self, String> {
            let result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
            if result.is_err() {
                return Err(format!(
                    "Could not initialise Windows Core Audio COM: 0x{:08X}",
                    result.0 as u32
                ));
            }
            Ok(Self)
        }
    }

    impl Drop for ComGuard {
        fn drop(&mut self) {
            unsafe { CoUninitialize() };
        }
    }

    pub fn set_ducking(enabled: bool, factor: f32) -> Result<(), String> {
        let _com = ComGuard::initialise()?;
        let factor = factor.clamp(0.05, 1.0);

        if enabled {
            duck_sessions(factor)
        } else {
            restore_sessions()
        }
    }

    fn session_manager() -> Result<IAudioSessionManager2, String> {
        unsafe {
            let device_enumerator: IMMDeviceEnumerator = CoCreateInstance(
                &MMDeviceEnumerator,
                None,
                CLSCTX_ALL,
            )
            .map_err(|error| format!("Could not create audio device enumerator: {error}"))?;

            let device = device_enumerator
                .GetDefaultAudioEndpoint(eRender, eMultimedia)
                .map_err(|error| format!("Could not access the default audio output: {error}"))?;

            device
                .Activate::<IAudioSessionManager2>(CLSCTX_ALL, None)
                .map_err(|error| format!("Could not open the Windows audio session manager: {error}"))
        }
    }

    fn jace_process_tree() -> HashSet<u32> {
        let root_pid = std::process::id();
        let mut excluded = HashSet::from([root_pid]);
        let mut processes: Vec<(u32, u32)> = Vec::new();

        let snapshot = match unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) } {
            Ok(handle) => handle,
            Err(_) => return excluded,
        };

        let mut entry = PROCESSENTRY32W::default();
        entry.dwSize = size_of::<PROCESSENTRY32W>() as u32;

        if unsafe { Process32FirstW(snapshot, &mut entry) }.is_ok() {
            loop {
                processes.push((entry.th32ProcessID, entry.th32ParentProcessID));

                if unsafe { Process32NextW(snapshot, &mut entry) }.is_err() {
                    break;
                }
            }
        }

        let _ = unsafe { CloseHandle(snapshot) };

        // WebView2 creates several child/utility processes, including the
        // process that can own Jace's audio stream. Excluding the complete
        // descendant tree keeps Jace's own TTS at full volume.
        loop {
            let mut changed = false;

            for (pid, parent_pid) in &processes {
                if !excluded.contains(pid) && excluded.contains(parent_pid) {
                    excluded.insert(*pid);
                    changed = true;
                }
            }

            if !changed {
                break;
            }
        }

        excluded
    }

    unsafe fn take_com_string(value: windows::core::PWSTR) -> String {
        if value.0.is_null() {
            return String::new();
        }

        let mut length = 0usize;
        while *value.0.add(length) != 0 {
            length += 1;
        }

        let text = String::from_utf16_lossy(slice::from_raw_parts(value.0, length));
        CoTaskMemFree(Some(value.0.cast::<c_void>() as *const c_void));
        text
    }

    fn session_key(control: &IAudioSessionControl2, index: i32, pid: u32) -> String {
        unsafe {
            if let Ok(identifier) = control.GetSessionInstanceIdentifier() {
                let identifier = take_com_string(identifier);
                if !identifier.is_empty() {
                    return identifier;
                }
            }
        }

        // The instance identifier should normally be available. This fallback
        // still gives a stable-enough key for the duration of a short spoken
        // response if a third-party audio session does not expose one.
        format!("pid:{pid}:index:{index}")
    }

    fn duck_sessions(factor: f32) -> Result<(), String> {
        unsafe {
            let manager = session_manager()?;
            let enumerator = manager
                .GetSessionEnumerator()
                .map_err(|error| format!("Could not enumerate audio sessions: {error}"))?;
            let count = enumerator
                .GetCount()
                .map_err(|error| format!("Could not count audio sessions: {error}"))?;

            let excluded_pids = jace_process_tree();
            let mut originals = volume_store()
                .lock()
                .map_err(|_| "Jace audio ducking state is unavailable.".to_string())?;

            for index in 0..count {
                let session = match enumerator.GetSession(index) {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                let control: IAudioSessionControl2 = match session.cast() {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                let pid = match control.GetProcessId() {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                if excluded_pids.contains(&pid) {
                    continue;
                }

                let volume: ISimpleAudioVolume = match session.cast() {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                let key = session_key(&control, index, pid);

                let original = if let Some(existing) = originals.get(&key) {
                    existing.volume
                } else {
                    let current = match volume.GetMasterVolume() {
                        Ok(value) => value.clamp(0.0, 1.0),
                        Err(_) => continue,
                    };

                    originals.insert(key.clone(), OriginalSession { volume: current });
                    current
                };

                let target = (original * factor).clamp(0.0, 1.0);
                let _ = volume.SetMasterVolume(target, std::ptr::null());
            }
        }

        Ok(())
    }

    fn restore_sessions() -> Result<(), String> {
        unsafe {
            let manager = session_manager()?;
            let enumerator = manager
                .GetSessionEnumerator()
                .map_err(|error| format!("Could not enumerate audio sessions: {error}"))?;
            let count = enumerator
                .GetCount()
                .map_err(|error| format!("Could not count audio sessions: {error}"))?;

            let mut originals = volume_store()
                .lock()
                .map_err(|_| "Jace audio ducking state is unavailable.".to_string())?;

            if originals.is_empty() {
                return Ok(());
            }

            for index in 0..count {
                let session = match enumerator.GetSession(index) {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                let control: IAudioSessionControl2 = match session.cast() {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                let pid = match control.GetProcessId() {
                    Ok(value) => value,
                    Err(_) => 0,
                };

                let key = session_key(&control, index, pid);
                let Some(original) = originals.get(&key).copied() else {
                    continue;
                };

                let volume: ISimpleAudioVolume = match session.cast() {
                    Ok(value) => value,
                    Err(_) => continue,
                };

                if volume
                    .SetMasterVolume(original.volume.clamp(0.0, 1.0), std::ptr::null())
                    .is_ok()
                {
                    originals.remove(&key);
                }
            }

            // Any entries left here refer to sessions that disappeared while
            // Jace was speaking. There is nothing left to restore for them.
            originals.clear();
        }

        Ok(())
    }
}
