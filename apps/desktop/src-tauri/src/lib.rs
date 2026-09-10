mod audio_ducking;

/// Reduce every non-Jace Windows audio session while Jace is speaking, then
/// restore the session volumes when speech finishes.
///
/// The Core Audio work is run on a blocking worker because COM is initialised
/// on the thread that performs the audio-session enumeration.
#[tauri::command]
async fn set_system_audio_ducking(
    enabled: bool,
    factor: Option<f32>,
) -> Result<(), String> {
    let factor = factor.unwrap_or(0.18).clamp(0.05, 1.0);

    tauri::async_runtime::spawn_blocking(move || {
        audio_ducking::set_ducking(enabled, factor)
    })
    .await
    .map_err(|error| format!("Audio ducking worker failed: {error}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![set_system_audio_ducking])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
