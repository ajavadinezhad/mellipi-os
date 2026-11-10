//! Native session security and request-driven output capture protocols.
//! Normal clients are never rendered or input targets while a lock is held.
mod idle;
mod locked_input;
mod text_input;
pub use idle::install;
pub use text_input::{trusted_ime_stream,trusted_keyboard_stream};
mod screencopy;
mod session_lock;
use smithay::{output::Output, reexports::wayland_server::DisplayHandle};
pub struct NativeProtocols {
    pub idle: idle::IdleState,
    pub super_pending: bool,
    pub alt_switching: bool,
    pub last_window_focus:
        Option<smithay::reexports::wayland_server::protocol::wl_surface::WlSurface>,
    pub(crate) lock: session_lock::LockState,
    pub(crate) captures: Vec<screencopy::PendingCapture>,
}
impl NativeProtocols {
    pub fn new(display: &DisplayHandle) -> Self {
        // A nested window cannot certify physical output presentation. Its
        // parent owns the screen lock; expose locking only on the DRM backend.
        // Private QA can explicitly inject the presentation boundary to test
        // ownership/fail-closed protocol behavior, never secure presentation.
        if std::env::args().any(|arg| arg == "--drm") || test_lock_presentation() {
            session_lock::register(display);
        }
        screencopy::register(display);
        idle::register(display);
        text_input::register(display);
        Self {
            idle: Default::default(),
            super_pending: false,
            alt_switching: false,
            last_window_focus: None,
            lock: Default::default(),
            captures: Vec::new(),
        }
    }
    pub fn is_locked(&self) -> bool {
        self.lock.owner.is_some()
    }
    /// Call only AFTER the renderer has submitted an opaque lock/black output.
    pub fn output_presented(&mut self, output: &Output) {
        self.lock.output_presented(output);
    }
    /// Call on output addition or scale/size change before drawing it.
    pub fn output_changed(&mut self, output: &Output) {
        self.lock.output_changed(output);
    }
    pub fn output_removed(&mut self, output: &Output) {
        self.lock.output_removed(output);
        self.captures.retain(|capture| {
            if &capture.output == output {
                capture.frame.failed();
                false
            } else {
                true
            }
        });
    }
}

/// Test-only boundary injection, requiring a private nested fixture marker.
pub fn test_lock_presentation() -> bool {
    std::env::var("ORBIT_NESTED").as_deref() == Ok("1")
        && std::env::var("ORBIT_NATIVE_QA_LOCK").as_deref() == Ok("1")
}
