//! Standard text-input-v3 plus a narrowly trusted input-method-v2 endpoint.
//! The compositor does not install/start an IME. Only a root-owned installed
//! IBus/Fcitx executable may bind the privileged input-method manager.
use crate::OrbitCompositor;
use smithay::{
    delegate_input_method_manager, delegate_text_input_manager, delegate_virtual_keyboard_manager,
    desktop::{PopupKind, PopupManager},
    reexports::wayland_server::{protocol::wl_surface::WlSurface, DisplayHandle},
    utils::{Logical, Rectangle},
    wayland::{
        input_method::{InputMethodHandler, InputMethodManagerState, PopupSurface},
        seat::WaylandFocus,
        text_input::TextInputManagerState,
    },
};
use std::os::unix::fs::MetadataExt;
/// Evaluate peer credentials before inserting the client into Wayland's backend.
/// Global visibility filters must not re-enter DisplayHandle while it is locked.
pub fn trusted_ime_stream(stream: &std::os::unix::net::UnixStream) -> bool {trusted_stream(stream,false)}
pub fn trusted_keyboard_stream(stream:&std::os::unix::net::UnixStream)->bool{trusted_stream(stream,true)}
fn trusted_stream(stream: &std::os::unix::net::UnixStream,keyboard:bool) -> bool {
    use std::os::fd::AsRawFd;
    #[repr(C)]
    struct Credentials {
        pid: i32,
        uid: u32,
        gid: u32,
    }
    unsafe extern "C" {
        fn getsockopt(
            fd: i32,
            level: i32,
            name: i32,
            value: *mut std::ffi::c_void,
            len: *mut u32,
        ) -> i32;
    }
    let mut credentials = Credentials {
        pid: 0,
        uid: u32::MAX,
        gid: u32::MAX,
    };
    let mut len = std::mem::size_of::<Credentials>() as u32;
    // Linux SO_PEERCRED on an already accepted connected AF_UNIX stream.
    let result = unsafe {
        getsockopt(
            stream.as_raw_fd(),
            1,
            17,
            (&mut credentials as *mut Credentials).cast(),
            &mut len,
        )
    };
    result == 0
        && len as usize == std::mem::size_of::<Credentials>()
        && trusted_pid(credentials.pid, credentials.uid,keyboard)
}
fn trusted_pid(pid: i32, uid: u32,keyboard:bool) -> bool {
    // /proc/self/status uses real credentials without adding a libc dependency.
    let self_uid = std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|s| {
            s.lines().find_map(|line| {
                line.strip_prefix("Uid:")
                    .and_then(|v| v.split_whitespace().next())
                    .and_then(|n| n.parse::<u32>().ok())
            })
        });
    if self_uid != Some(uid) || pid <= 0 {
        return false;
    }
    let Ok(exe) = std::fs::read_link(format!("/proc/{pid}/exe")) else {
        return false;
    };
    // Input-method-v2 engines must reinject unhandled keys through the
    // virtual-keyboard protocol. Giving only the IME manager makes Fcitx
    // refuse to create its input method. Both globals use identical peer
    // credentials and installed-executable ownership checks.
    let known:&[&str]=if keyboard {&["/usr/bin/wvkbd-mobintl","/usr/bin/wvkbd-desktop","/usr/bin/squeekboard","/usr/bin/fcitx5","/usr/bin/ibus-daemon"]}else{&["/usr/bin/ibus-daemon", "/usr/bin/fcitx5","/usr/bin/squeekboard"]};
    known.iter().copied()
        .any(|known| {
            let Ok(path) = std::fs::canonicalize(known) else {
                return false;
            };
            let Ok(metadata) = std::fs::metadata(&path) else {
                return false;
            };
            path == exe && metadata.is_file() && metadata.uid() == 0 && metadata.mode() & 0o022 == 0
        })
}
pub fn register(display: &DisplayHandle) {
    smithay::wayland::virtual_keyboard::VirtualKeyboardManagerState::new::<OrbitCompositor,_>(display,|client|client.get_data::<crate::state::ClientState>().is_some_and(|state|state.trusted_virtual_keyboard));
    TextInputManagerState::new::<OrbitCompositor>(display);
    InputMethodManagerState::new::<OrbitCompositor, _>(display, |client| {
        client
            .get_data::<crate::state::ClientState>()
            .is_some_and(|state| state.trusted_input_method)
    });
}
impl InputMethodHandler for OrbitCompositor {
    fn new_popup(&mut self, surface: PopupSurface) {
        if self.protocols.is_locked() {
            return;
        }
        let _ = self.popups.track_popup(PopupKind::from(surface));
        self.request_redraw();
    }
    fn popup_repositioned(&mut self, _: PopupSurface) {
        self.request_redraw();
    }
    fn dismiss_popup(&mut self, surface: PopupSurface) {
        if let Some(parent) = surface.get_parent().map(|parent| parent.surface.clone()) {
            let _ = PopupManager::dismiss_popup(&parent, &PopupKind::from(surface));
        }
        self.request_redraw();
    }
    fn parent_geometry(&self, parent: &WlSurface) -> Rectangle<i32, Logical> {
        self.space
            .elements()
            .find_map(|window| {
                (window.wl_surface().as_deref() == Some(parent)).then(|| window.geometry())
            })
            .unwrap_or_default()
    }
}
delegate_text_input_manager!(OrbitCompositor);
delegate_input_method_manager!(OrbitCompositor);

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn untrusted_client_cannot_claim_input_method_privilege() {
        let (stream, _peer) = std::os::unix::net::UnixStream::pair().unwrap();
        assert!(!trusted_ime_stream(&stream));
        assert!(!trusted_keyboard_stream(&stream));
        assert!(!trusted_pid(-1, 0,false));
    }
}

delegate_virtual_keyboard_manager!(OrbitCompositor);
