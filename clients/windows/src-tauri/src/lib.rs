use std::{
    io,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use reqwest::blocking::Client;
use serde::Deserialize;
use tauri::{
    image::Image,
    menu::MenuBuilder,
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_global_shortcut::{Builder as GlobalShortcutBuilder, Code, Modifiers, Shortcut, ShortcutState};
use url::Url;

const MAIN_WINDOW_LABEL: &str = "main";
const TRAY_ID: &str = "voice-tray";
const MENU_START: &str = "start-voice";
const MENU_TOGGLE: &str = "toggle-window";
const MENU_INTERRUPT: &str = "interrupt-now";
const MENU_QUIT: &str = "quit";
const VOICE_URL: &str = "http://127.0.0.1:8765/voice";
const STATUS_URL: &str = "http://127.0.0.1:8765/api/windows-client/status";
const STATUS_POLL_INTERVAL: Duration = Duration::from_millis(1200);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TrayState {
    Listening,
    Thinking,
    Speaking,
    Reconnecting,
    Paused,
}

impl TrayState {
    fn label(self) -> &'static str {
        match self {
            Self::Listening => "listening",
            Self::Thinking => "thinking",
            Self::Speaking => "speaking",
            Self::Reconnecting => "reconnecting",
            Self::Paused => "paused",
        }
    }

    fn accent(self) -> [u8; 4] {
        match self {
            Self::Listening => [78, 146, 255, 255],
            Self::Thinking => [245, 185, 66, 255],
            Self::Speaking => [77, 204, 113, 255],
            Self::Reconnecting => [240, 108, 91, 255],
            Self::Paused => [140, 146, 156, 255],
        }
    }

    fn from_wire(value: &str) -> Self {
        match value {
            "listening" => Self::Listening,
            "thinking" => Self::Thinking,
            "speaking" => Self::Speaking,
            "paused" => Self::Paused,
            _ => Self::Reconnecting,
        }
    }
}

#[derive(Deserialize)]
struct ShellStatusResponse {
    state: String,
    stale: bool,
}

fn generate_shell_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("windows-shell-{}-{millis}", std::process::id())
}

fn build_voice_url(shell_id: &str) -> Url {
    let mut url = Url::parse(VOICE_URL).expect("VOICE_URL must be a valid URL");
    url.query_pairs_mut().append_pair("shell_id", shell_id);
    url
}

fn should_open_externally(url: &Url) -> bool {
    matches!(url.path(), "/setup") || url.path().starts_with("/setup/")
}

fn is_voice_url(url: &Url, voice_url: &Url) -> bool {
    url.scheme() == voice_url.scheme()
        && url.host_str() == voice_url.host_str()
        && url.port_or_known_default() == voice_url.port_or_known_default()
        && matches!(url.path(), "/voice" | "/voice/")
}

fn open_in_browser(url: &Url) {
    if let Err(error) = webbrowser::open(url.as_str()) {
        eprintln!("failed to open external browser for {}: {error}", url);
    }
}

fn tray_tooltip(state: TrayState) -> String {
    format!("OpenClaw Voice: {}", state.label())
}

fn set_pixel(rgba: &mut [u8], x: i32, y: i32, color: [u8; 4]) {
    if !(0..32).contains(&x) || !(0..32).contains(&y) {
        return;
    }
    let offset = ((y as usize * 32) + x as usize) * 4;
    rgba[offset..offset + 4].copy_from_slice(&color);
}

fn draw_rect(rgba: &mut [u8], x: i32, y: i32, width: i32, height: i32, color: [u8; 4]) {
    for row in y..(y + height) {
        for column in x..(x + width) {
            set_pixel(rgba, column, row, color);
        }
    }
}

fn draw_filled_circle(rgba: &mut [u8], cx: i32, cy: i32, radius: i32, color: [u8; 4]) {
    for y in (cy - radius)..=(cy + radius) {
        for x in (cx - radius)..=(cx + radius) {
            let dx = x - cx;
            let dy = y - cy;
            if dx * dx + dy * dy <= radius * radius {
                set_pixel(rgba, x, y, color);
            }
        }
    }
}

fn draw_line(rgba: &mut [u8], mut x0: i32, mut y0: i32, x1: i32, y1: i32, color: [u8; 4]) {
    let dx = (x1 - x0).abs();
    let sx = if x0 < x1 { 1 } else { -1 };
    let dy = -(y1 - y0).abs();
    let sy = if y0 < y1 { 1 } else { -1 };
    let mut err = dx + dy;

    loop {
        set_pixel(rgba, x0, y0, color);
        if x0 == x1 && y0 == y1 {
            break;
        }
        let e2 = err * 2;
        if e2 >= dy {
            err += dy;
            x0 += sx;
        }
        if e2 <= dx {
            err += dx;
            y0 += sy;
        }
    }
}

fn tray_icon_for_state(state: TrayState) -> Image<'static> {
    let mut rgba = vec![0; 32 * 32 * 4];
    let white = [255, 255, 255, 255];
    let dark = [16, 18, 22, 255];
    let accent = state.accent();

    draw_filled_circle(&mut rgba, 16, 16, 14, dark);
    draw_filled_circle(&mut rgba, 16, 16, 12, accent);

    match state {
        TrayState::Listening => {
            draw_rect(&mut rgba, 12, 8, 8, 10, white);
            draw_rect(&mut rgba, 10, 18, 12, 2, white);
            draw_rect(&mut rgba, 14, 20, 4, 4, white);
        }
        TrayState::Thinking => {
            draw_filled_circle(&mut rgba, 10, 16, 2, dark);
            draw_filled_circle(&mut rgba, 16, 16, 2, dark);
            draw_filled_circle(&mut rgba, 22, 16, 2, dark);
        }
        TrayState::Speaking => {
            draw_rect(&mut rgba, 9, 11, 3, 10, white);
            draw_rect(&mut rgba, 15, 8, 3, 16, white);
            draw_rect(&mut rgba, 21, 11, 3, 10, white);
        }
        TrayState::Reconnecting => {
            draw_line(&mut rgba, 10, 10, 22, 22, white);
            draw_line(&mut rgba, 22, 10, 10, 22, white);
            draw_rect(&mut rgba, 15, 7, 2, 2, white);
            draw_rect(&mut rgba, 15, 23, 2, 2, white);
        }
        TrayState::Paused => {
            draw_rect(&mut rgba, 11, 9, 4, 14, dark);
            draw_rect(&mut rgba, 17, 9, 4, 14, dark);
        }
    }

    Image::new_owned(rgba, 32, 32)
}

fn apply_tray_state<R: tauri::Runtime>(tray: &tauri::tray::TrayIcon<R>, state: TrayState) {
    let _ = tray.set_icon(Some(tray_icon_for_state(state)));
    let _ = tray.set_tooltip(Some(tray_tooltip(state)));
}

fn fetch_tray_state(client: &Client, shell_id: &str) -> Option<TrayState> {
    let response = client
        .get(STATUS_URL)
        .query(&[("shell_id", shell_id)])
        .send()
        .ok()?
        .error_for_status()
        .ok()?;
    let payload: ShellStatusResponse = response.json().ok()?;
    if payload.stale {
        return Some(TrayState::Reconnecting);
    }
    Some(TrayState::from_wire(&payload.state))
}

fn start_tray_status_poller<R: tauri::Runtime + 'static>(
    tray: tauri::tray::TrayIcon<R>,
    quitting: Arc<AtomicBool>,
    shell_id: String,
) {
    thread::spawn(move || {
        let client = Client::builder().timeout(Duration::from_secs(2)).build().ok();
        let mut has_seen_status = false;
        let mut last_state = Some(TrayState::Paused);

        while !quitting.load(Ordering::SeqCst) {
            let next_state = if let Some(state) = client
                .as_ref()
                .and_then(|client| fetch_tray_state(client, &shell_id))
            {
                has_seen_status = true;
                state
            } else if has_seen_status {
                TrayState::Reconnecting
            } else {
                TrayState::Paused
            };

            if last_state != Some(next_state) {
                apply_tray_state(&tray, next_state);
                last_state = Some(next_state);
            }

            thread::sleep(STATUS_POLL_INTERVAL);
        }
    });
}

fn build_main_window<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    shell_id: &str,
) -> tauri::Result<()> {
    if app.get_webview_window(MAIN_WINDOW_LABEL).is_some() {
        return Ok(());
    }

    let voice_url = build_voice_url(shell_id);

    let window = WebviewWindowBuilder::new(
        app,
        MAIN_WINDOW_LABEL,
        WebviewUrl::External(voice_url.clone()),
    )
    .title("OpenClaw Voice")
    .inner_size(460.0, 620.0)
    .min_inner_size(360.0, 520.0)
    .resizable(true)
    .center()
    .visible(false)
    .focused(false)
    .on_navigation({
        let voice_url = voice_url.clone();
        move |url| {
            if should_open_externally(url) {
                open_in_browser(url);
                return false;
            }

            is_voice_url(url, &voice_url)
        }
    })
    .on_new_window(move |url, _features| {
        if should_open_externally(&url) {
            open_in_browser(&url);
            return tauri::webview::NewWindowResponse::Deny;
        }

        tauri::webview::NewWindowResponse::Deny
    })
    .build()?;

    let _ = window;
    Ok(())
}

fn show_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window(MAIN_WINDOW_LABEL) {
            let _ = window.unminimize();
            let _ = window.show();
            let _ = window.set_focus();
        }
    });
}

fn toggle_main_window<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window(MAIN_WINDOW_LABEL) {
            let visible = window.is_visible().unwrap_or(true);
            if visible {
                let _ = window.hide();
            } else {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
    });
}

fn start_voice_runtime<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    show_main_window(app);
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window(MAIN_WINDOW_LABEL) {
            let script = r#"
                (() => {
                    let attempts = 0;
                    const tryStart = () => {
                        const button = document.querySelector('#pause-btn');
                        if (!button) {
                            if (attempts < 20) {
                                attempts += 1;
                                window.setTimeout(tryStart, 150);
                            }
                            return;
                        }
                        const isPaused = document.body.dataset.state === 'paused' || button.classList.contains('active');
                        if (isPaused) button.click();
                    };
                    tryStart();
                })();
            "#;
            let _ = window.eval(script);
        }
    });
}

fn click_voice_button<R: tauri::Runtime>(app: &tauri::AppHandle<R>, selector: &'static str) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window(MAIN_WINDOW_LABEL) {
            let script = format!(
                "(() => {{ const button = document.querySelector({selector:?}); if (button && !button.disabled) button.click(); }})();"
            );
            let _ = window.eval(&script);
        }
    });
}

fn invoke_voice_action<R: tauri::Runtime>(app: &tauri::AppHandle<R>, action: &'static str) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = handle.get_webview_window(MAIN_WINDOW_LABEL) {
            let script = format!(
                r#"
                (() => {{
                    let attempts = 0;
                    const tryInvoke = () => {{
                        const action = window[{action:?}];
                        if (typeof action === 'function') {{
                            action();
                            return;
                        }}
                        if (attempts < 20) {{
                            attempts += 1;
                            window.setTimeout(tryInvoke, 150);
                        }}
                    }};
                    tryInvoke();
                }})();
                "#
            );
            let _ = window.eval(&script);
        }
    });
}

fn build_tray<R: tauri::Runtime>(
    app: &tauri::AppHandle<R>,
    quitting: Arc<AtomicBool>,
) -> tauri::Result<tauri::tray::TrayIcon<R>> {
    let menu = MenuBuilder::new(app)
        .text(MENU_START, "Start Voice")
        .separator()
        .text(MENU_INTERRUPT, "Interrupt Now")
        .separator()
        .text(MENU_TOGGLE, "Show / Hide")
        .separator()
        .text(MENU_QUIT, "Quit")
        .build()?;

    let tray = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip(tray_tooltip(TrayState::Paused))
        .icon(tray_icon_for_state(TrayState::Paused))
        .show_menu_on_left_click(false)
        .on_menu_event({
            let quitting = quitting.clone();
            move |app, event| match event.id().as_ref() {
                MENU_START => start_voice_runtime(app),
                MENU_INTERRUPT => invoke_voice_action(app, "__openclawManualInterrupt"),
                MENU_TOGGLE => toggle_main_window(app),
                MENU_QUIT => {
                    quitting.store(true, Ordering::SeqCst);
                    app.exit(0);
                }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_main_window(&tray.app_handle());
            }
        });

    tray.build(app)
}

pub fn run() {
    if let Err(error) = run_inner() {
        eprintln!("failed to launch OpenClaw Voice Windows client: {error}");
    }
}

fn run_inner() -> tauri::Result<()> {
    let quitting = Arc::new(AtomicBool::new(false));
    let shell_id = generate_shell_id();

    let show_hide_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space);
    let pause_shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyP);
    let interrupt_shortcuts = vec![Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyA)];

    let show_hide_shortcut_id = show_hide_shortcut.id();
    let pause_shortcut_id = pause_shortcut.id();
    let interrupt_shortcut_ids: Vec<_> = interrupt_shortcuts.iter().map(|shortcut| shortcut.id()).collect();

    let mut shortcuts = vec![show_hide_shortcut, pause_shortcut];
    shortcuts.extend(interrupt_shortcuts);

    let shortcut_plugin = GlobalShortcutBuilder::new()
        .with_shortcuts(shortcuts).map_err(|error| {
            io::Error::other(format!("failed to register global shortcuts: {error}"))
        })?
        .with_handler(move |app, shortcut, event| {
            if event.state != ShortcutState::Pressed {
                return;
            }

            if shortcut.id() == show_hide_shortcut_id {
                toggle_main_window(app);
            } else if shortcut.id() == pause_shortcut_id {
                click_voice_button(app, "#pause-btn");
            } else if interrupt_shortcut_ids.iter().any(|shortcut_id| *shortcut_id == shortcut.id()) {
                invoke_voice_action(app, "__openclawManualInterrupt");
            }
        })
        .build();

    tauri::Builder::default()
        .plugin(shortcut_plugin)
        .setup({
            let quitting = quitting.clone();
            let shell_id = shell_id.clone();
            move |app| {
                build_main_window(&app.handle(), &shell_id)?;
                let tray = build_tray(&app.handle(), quitting.clone())?;
                start_tray_status_poller(tray, quitting.clone(), shell_id.clone());
                Ok(())
            }
        })
        .on_window_event({
            let quitting = quitting.clone();
            move |window, event| {
                if window.label() != MAIN_WINDOW_LABEL {
                    return;
                }

                if let WindowEvent::CloseRequested { api, .. } = event {
                    if quitting.load(Ordering::SeqCst) {
                        return;
                    }
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .run(tauri::generate_context!())?;

    Ok(())
}
