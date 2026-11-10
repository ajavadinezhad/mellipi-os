#![allow(irrefutable_let_patterns)]

mod handlers;

mod decoration;
mod cursor_theme;
mod clipboard;
mod dmabuf;
#[cfg(feature = "drm")]
mod drm;
mod grabs;
mod input;
mod ipc;
mod motion;
mod window_motion;
mod native_system;
mod protocols;
mod state;
mod winit;
mod workspaces;
mod xwayland;

use smithay::reexports::{
    calloop::EventLoop,
    wayland_server::{Display, DisplayHandle},
};
pub use state::OrbitCompositor;

pub struct CalloopData {
    state: OrbitCompositor,
    display_handle: DisplayHandle,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments.iter().any(|arg|arg=="--dmabuf-import-check") {
        #[cfg(feature="drm")] println!("{}",crate::dmabuf::hardware_probe());
        #[cfg(not(feature="drm"))] println!("{}",serde_json::json!({"ok":false,"error":"DRM support was not built","physical_session_changed":false}));
        return Ok(());
    }
    if arguments.iter().any(|arg| arg == "--drm-preflight") {
        #[cfg(feature = "drm")]
        println!("{}", crate::drm::preflight());
        #[cfg(not(feature = "drm"))]
        println!(
            "{}",
            serde_json::json!({"ok":false,"error":"DRM backend was not compiled"})
        );
        return Ok(());
    }
    if let Ok(env_filter) = tracing_subscriber::EnvFilter::try_from_default_env() {
        tracing_subscriber::fmt().with_env_filter(env_filter).init();
    } else {
        tracing_subscriber::fmt().init();
    }

    let mut event_loop: EventLoop<CalloopData> = EventLoop::try_new()?;

    let display: Display<OrbitCompositor> = Display::new()?;
    let display_handle = display.handle();
    let state = OrbitCompositor::new(&mut event_loop, display);

    let mut data = CalloopData {
        state,
        display_handle,
    };

    if arguments.iter().any(|arg| arg == "--drm") {
        #[cfg(feature = "drm")]
        crate::drm::init_drm(&mut event_loop, &mut data)?;
        #[cfg(not(feature = "drm"))]
        return Err("DRM backend was not compiled".into());
    } else {
        crate::winit::init_winit(&mut event_loop, &mut data)?;
    }
    if let Err(error) = crate::xwayland::start(&mut event_loop, &mut data) {
        data.state.xwayland.error = Some(error.to_string());
    }

    crate::ipc::install(&mut event_loop, &mut data)?;
    crate::protocols::install(event_loop.handle(), &mut data);
    println!(
        "{}",
        serde_json::json!({"ready":true,"wayland_display":data.state.socket_name.to_string_lossy(),"control":data.state.control_path,"experimental":true})
    );
    let mut args = std::env::args().skip(1);
    let flag = args.next();
    let arg = args.next();

    if let (Some("-c") | Some("--command"), Some(command)) = (flag.as_deref(), arg) {
        std::process::Command::new(command).spawn()?;
    }

    event_loop.run(None, &mut data, move |_| {
        // OrbitCompositor is running
    })?;

    let _ = std::fs::remove_file(&data.state.control_path);
    Ok(())
}
