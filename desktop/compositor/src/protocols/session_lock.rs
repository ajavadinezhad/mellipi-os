//! Ownership-checked ext-session-lock, including fail-closed locker failure.
use crate::{protocols::NativeProtocols, OrbitCompositor};
use smithay::wayland::seat::WaylandFocus;
use smithay::{
    backend::renderer::{
        buffer_dimensions,
        element::surface::{render_elements_from_surface_tree, WaylandSurfaceRenderElement},
        element::Kind,
        gles::GlesRenderer,
    },
    output::Output,
    reexports::{
        wayland_protocols::ext::session_lock::v1::server::{
            ext_session_lock_manager_v1 as manager, ext_session_lock_surface_v1 as lock_surface,
            ext_session_lock_v1 as lock,
        },
        wayland_server::{
            protocol::wl_surface::WlSurface, Client, DataInit, Dispatch, DisplayHandle,
            GlobalDispatch, New, Resource,
        },
    },
    utils::{Logical, Point, Size, SERIAL_COUNTER},
    wayland::{
        compositor::{self, BufferAssignment, SurfaceAttributes},
        viewporter::ViewportCachedState,
    },
};
use std::sync::{Arc, Mutex};
#[derive(Default)]
pub(crate) struct LockState {
    pub owner: Option<lock::ExtSessionLockV1>,
    acknowledged: bool,
    awaiting: Vec<Output>,
    surfaces: Vec<LockView>,
}
#[derive(Clone)]
struct LockView {
    surface: WlSurface,
    output: Output,
    resource: lock_surface::ExtSessionLockSurfaceV1,
    buffer: Arc<Mutex<LockBuffer>>,
}
#[derive(Default)]
pub struct LockBuffer {
    serial: u32,
    size: Size<i32, Logical>,
    acked: bool,
    committed: bool,
    valid_commit: bool,
}
#[derive(Clone)]
pub struct LockSurfaceData {
    buffer: Arc<Mutex<LockBuffer>>,
}
pub fn register(display: &DisplayHandle) {
    display.create_global::<OrbitCompositor, manager::ExtSessionLockManagerV1, _>(1, ());
}
fn size(output: &Output) -> Size<i32, Logical> {
    output
        .current_mode()
        .map(|mode| {
            output
                .current_transform()
                .transform_size(mode.size)
                .to_f64()
                .to_logical(output.current_scale().fractional_scale())
                .to_i32_round()
        })
        .unwrap_or((1, 1).into())
}
impl LockState {
    fn configure(view: &LockView) {
        let mut buffer = view.buffer.lock().unwrap();
        buffer.serial = SERIAL_COUNTER.next_serial().into();
        buffer.size = size(&view.output);
        buffer.acked = false;
        buffer.committed = false;
        view.resource.configure(
            buffer.serial,
            buffer.size.w.max(1) as u32,
            buffer.size.h.max(1) as u32,
        );
    }
    pub fn output_presented(&mut self, output: &Output) {
        if self.owner.is_none() || self.acknowledged {
            return;
        }
        self.awaiting.retain(|candidate| candidate != output);
        if self.awaiting.is_empty() {
            if let Some(owner) = &self.owner {
                if owner.is_alive() {
                    owner.locked();
                    self.acknowledged = true;
                }
            }
        }
    }
    pub fn output_changed(&mut self, output: &Output) {
        if self.owner.is_none() {
            return;
        }
        if !self.acknowledged && !self.awaiting.contains(output) {
            self.awaiting.push(output.clone());
        }
        for view in &self.surfaces {
            if &view.output == output {
                Self::configure(view);
            }
        }
    }
    pub fn output_removed(&mut self, output: &Output) {
        self.awaiting.retain(|candidate| candidate != output);
        self.surfaces.retain(|view| &view.output != output);
    }
}
impl NativeProtocols {
    /// A lock owner exists and every output completed an opaque lock pageflip.
    pub fn lock_ready(&self) -> bool {
        self.lock.owner.is_some() && self.lock.acknowledged
    }
    pub fn lock_render_elements(
        &self,
        output: &Output,
        renderer: &mut GlesRenderer,
    ) -> Vec<WaylandSurfaceRenderElement<GlesRenderer>> {
        if !self.is_locked() {
            return vec![];
        }
        self.lock
            .surfaces
            .iter()
            .filter(|view| {
                &view.output == output
                    && view.surface.is_alive()
                    && view.buffer.lock().unwrap().committed
            })
            .flat_map(|view| {
                render_elements_from_surface_tree(
                    renderer,
                    &view.surface,
                    (0, 0),
                    output.current_scale().fractional_scale(),
                    1.0,
                    Kind::Unspecified,
                )
            })
            .collect()
    }
    /// Supply callbacks to the locker only while its output is opaque/locked.
    pub fn lock_send_frames(&self, output: &Output, time: std::time::Duration) {
        if !self.is_locked() {
            return;
        }
        for view in self
            .lock
            .surfaces
            .iter()
            .filter(|view| &view.output == output && view.buffer.lock().unwrap().committed)
        {
            smithay::desktop::utils::send_frames_surface_tree(
                &view.surface,
                output,
                time,
                Some(std::time::Duration::ZERO),
                |_, _| Some(output.clone()),
            );
        }
    }
    pub fn lock_surface_under(
        &self,
        pos: Point<f64, Logical>,
        outputs: impl IntoIterator<Item = (Output, Point<i32, Logical>)>,
    ) -> Option<(WlSurface, Point<f64, Logical>)> {
        for (output, location) in outputs {
            for view in &self.lock.surfaces {
                if view.output == output
                    && view.surface.is_alive()
                    && view.buffer.lock().unwrap().committed
                {
                    let area = smithay::utils::Rectangle::new(location, size(&output)).to_f64();
                    if area.contains(pos) {
                        return Some((view.surface.clone(), location.to_f64()));
                    }
                }
            }
        }
        None
    }
}
impl OrbitCompositor {
    /// Call after on_commit_buffer_handler; this never focuses an ordinary view.
    pub fn protocol_commit(&mut self, surface: &WlSurface) {
        self.update_idle_inhibition();
        if !self.protocols.is_locked() {
            self.sync_layer_focus();
            return;
        }
        let owned = self
            .protocols
            .lock
            .surfaces
            .iter()
            .any(|view| view.surface == *surface && view.buffer.lock().unwrap().committed);
        if owned {
            self.seat.get_keyboard().unwrap().set_focus(
                self,
                Some(surface.clone()),
                SERIAL_COUNTER.next_serial(),
            );
            self.request_redraw();
        }
    }
}
impl GlobalDispatch<manager::ExtSessionLockManagerV1, ()> for OrbitCompositor {
    fn bind(
        _state: &mut Self,
        _display: &DisplayHandle,
        _client: &Client,
        resource: New<manager::ExtSessionLockManagerV1>,
        _data: &(),
        init: &mut DataInit<'_, Self>,
    ) {
        init.init(resource, ());
    }
}
impl Dispatch<manager::ExtSessionLockManagerV1, ()> for OrbitCompositor {
    fn request(
        state: &mut Self,
        _client: &Client,
        _resource: &manager::ExtSessionLockManagerV1,
        request: manager::Request,
        _data: &(),
        _display: &DisplayHandle,
        init: &mut DataInit<'_, Self>,
    ) {
        match request {
            manager::Request::Lock { id } => {
                let owner = init.init(id, ());
                if state.protocols.is_locked() {
                    owner.finished();
                    return;
                }
                state.cancel_touch_sequence();
                state.protocols.lock.owner = Some(owner);
                state.protocols.lock.acknowledged = false;
                state.protocols.lock.awaiting = state.space.outputs().cloned().collect();
                for capture in state.protocols.captures.drain(..) {
                    capture.frame.failed();
                }
                state.protocols.super_pending = false;
                state.protocols.alt_switching = false;
                state.transition = None;
                state.pending_workspace = None;
                let serial = SERIAL_COUNTER.next_serial();
                state.seat.get_keyboard().unwrap().unset_grab(state);
                state
                    .seat
                    .get_pointer()
                    .unwrap()
                    .unset_grab(state, serial, 0);
                state.seat.get_keyboard().unwrap().set_focus(
                    state,
                    Option::<WlSurface>::None,
                    serial,
                );
                let pointer = state.seat.get_pointer().unwrap();
                pointer.motion(
                    state,
                    None,
                    &smithay::input::pointer::MotionEvent {
                        location: pointer.current_location(),
                        serial,
                        time: 0,
                    },
                );
                pointer.frame(state);
                state.request_redraw();
            }
            manager::Request::Destroy => {}
            _ => {}
        }
    }
}
impl Dispatch<lock::ExtSessionLockV1, ()> for OrbitCompositor {
    fn request(
        state: &mut Self,
        _client: &Client,
        resource: &lock::ExtSessionLockV1,
        request: lock::Request,
        _data: &(),
        _display: &DisplayHandle,
        init: &mut DataInit<'_, Self>,
    ) {
        let owner = state.protocols.lock.owner.as_ref() == Some(resource);
        match request {
            lock::Request::UnlockAndDestroy => {
                if !owner || !state.protocols.lock.acknowledged {
                    resource.post_error(
                        lock::Error::InvalidUnlock,
                        "Only the acknowledged lock owner can unlock",
                    );
                    return;
                }
                state.cancel_touch_sequence();
                state.protocols.lock = LockState::default();
                let focus = state
                    .space
                    .elements()
                    .rev()
                    .find_map(|window| window.wl_surface().map(|surface| surface.into_owned()));
                state.seat.get_keyboard().unwrap().set_focus(
                    state,
                    focus,
                    SERIAL_COUNTER.next_serial(),
                );
                state.request_redraw();
            }
            lock::Request::Destroy => {
                if owner {
                    resource.post_error(
                        lock::Error::InvalidDestroy,
                        "An accepted lock must authenticate and unlock",
                    );
                }
            }
            lock::Request::GetLockSurface {
                id,
                surface,
                output,
            } => {
                if !owner {
                    resource.post_error(
                        lock::Error::InvalidUnlock,
                        "Rejected lock cannot create surfaces",
                    );
                    return;
                }
                let Some(output) = Output::from_resource(&output) else {
                    resource.post_error(lock::Error::DuplicateOutput, "Unknown output");
                    return;
                };
                if state
                    .protocols
                    .lock
                    .surfaces
                    .iter()
                    .any(|view| view.output == output)
                {
                    resource.post_error(
                        lock::Error::DuplicateOutput,
                        "Output already has a lock surface",
                    );
                    return;
                }
                if compositor::give_role(&surface, "orbit-session-lock").is_err() {
                    resource.post_error(lock::Error::Role, "Surface already has a role");
                    return;
                }
                let has_buffer = compositor::with_states(&surface, |states| {
                    let mut guard = states.cached_state.get::<SurfaceAttributes>();
                    matches!(guard.pending().buffer, Some(BufferAssignment::NewBuffer(_)))
                        || states
                            .data_map
                            .get::<smithay::backend::renderer::utils::RendererSurfaceStateUserData>(
                            )
                            .is_some_and(|state| state.lock().unwrap().buffer().is_some())
                        || matches!(guard.current().buffer, Some(BufferAssignment::NewBuffer(_)))
                });
                if has_buffer {
                    resource.post_error(
                        lock::Error::AlreadyConstructed,
                        "Lock surface already has content",
                    );
                    return;
                }
                let buffer = Arc::new(Mutex::new(LockBuffer::default()));
                let data = LockSurfaceData {
                    buffer: buffer.clone(),
                };
                let handle = init.init(id, data);
                let view = LockView {
                    surface: surface.clone(),
                    output,
                    resource: handle.clone(),
                    buffer: buffer.clone(),
                };
                LockState::configure(&view);
                state.protocols.lock.surfaces.push(view);
                let check = buffer.clone();
                let errors = handle;
                compositor::add_pre_commit_hook::<Self, _>(&surface, move |_, _, surface| {
                    let mut lock = check.lock().unwrap();
                    lock.valid_commit = false;
                    if !lock.acked {
                        errors.post_error(
                            lock_surface::Error::CommitBeforeFirstAck,
                            "Lock configure not acknowledged",
                        );
                        return;
                    }
                    compositor::with_states(surface, |states| {
                        let mut guard = states.cached_state.get::<SurfaceAttributes>();
                        let attrs = guard.pending();
                        match attrs.buffer.as_ref() {
                            Some(BufferAssignment::Removed) => {
                                lock.committed = false;
                                errors.post_error(
                                    lock_surface::Error::NullBuffer,
                                    "A lock surface cannot detach its buffer",
                                );
                            }
                            Some(BufferAssignment::NewBuffer(buffer)) => {
                                let Some(dimensions) = buffer_dimensions(buffer) else {
                                    errors.post_error(
                                        lock_surface::Error::DimensionsMismatch,
                                        "Unknown lock buffer dimensions",
                                    );
                                    return;
                                };
                                let logical = dimensions
                                    .to_logical(attrs.buffer_scale, attrs.buffer_transform.into());
                                let destination = states
                                    .cached_state
                                    .get::<ViewportCachedState>()
                                    .pending()
                                    .dst;
                                let actual = destination.unwrap_or(logical);
                                if actual != lock.size {
                                    lock.committed = false;
                                    errors.post_error(
                                        lock_surface::Error::DimensionsMismatch,
                                        "Lock buffer must cover its output",
                                    );
                                } else {
                                    lock.valid_commit = true;
                                }
                            }
                            None => {
                                lock.valid_commit = lock.committed;
                            }
                        }
                    });
                });
                compositor::add_post_commit_hook::<Self, _>(&surface, move |_, _, _| {
                    let mut lock = buffer.lock().unwrap();
                    if lock.valid_commit {
                        lock.committed = true;
                    }
                });
                state.request_redraw();
            }
            _ => {}
        }
    }
    // Deliberately no unlock-on-destroy: a crashing or malicious locker leaves
    // an opaque compositor-owned cover until the authenticated owner unlocks.
}
impl Dispatch<lock_surface::ExtSessionLockSurfaceV1, LockSurfaceData> for OrbitCompositor {
    fn request(
        _state: &mut Self,
        _client: &Client,
        resource: &lock_surface::ExtSessionLockSurfaceV1,
        request: lock_surface::Request,
        data: &LockSurfaceData,
        _display: &DisplayHandle,
        _init: &mut DataInit<'_, Self>,
    ) {
        match request {
            lock_surface::Request::AckConfigure { serial } => {
                let mut buffer = data.buffer.lock().unwrap();
                if serial != buffer.serial {
                    resource.post_error(
                        lock_surface::Error::InvalidSerial,
                        "Stale or unknown lock configure",
                    );
                } else {
                    buffer.acked = true;
                }
            }
            lock_surface::Request::Destroy => {}
            _ => {}
        }
    }
}
