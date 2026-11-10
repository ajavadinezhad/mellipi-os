use crate::{grabs::resize_grab, state::ClientState, OrbitCompositor};
use smithay::{
    backend::renderer::utils::on_commit_buffer_handler,
    delegate_compositor, delegate_shm,
    reexports::wayland_server::{
        protocol::{wl_buffer, wl_surface::WlSurface},
        Client,
    },
    wayland::{
        buffer::BufferHandler,
        compositor::{
            get_parent, is_sync_subsurface, CompositorClientState, CompositorHandler,
            CompositorState,
        },
        seat::WaylandFocus,
        shm::{ShmHandler, ShmState},
    },
};

use super::xdg_shell;

impl CompositorHandler for OrbitCompositor {
    fn compositor_state(&mut self) -> &mut CompositorState {
        &mut self.compositor_state
    }

    fn client_compositor_state<'a>(&self, client: &'a Client) -> &'a CompositorClientState {
        if let Some(state) = client.get_data::<ClientState>() {
            &state.compositor_state
        } else {
            &client
                .get_data::<smithay::xwayland::XWaylandClientData>()
                .expect("registered native or Xwayland client")
                .compositor_state
        }
    }

    fn commit(&mut self, surface: &WlSurface) {
        on_commit_buffer_handler::<Self>(surface);
        self.protocol_commit(surface);
        if !is_sync_subsurface(surface) {
            let mut root = surface.clone();
            while let Some(parent) = get_parent(&root) {
                root = parent;
            }
            if let Some(window) = self
                .space
                .elements()
                .find(|w| w.wl_surface().is_some_and(|s| s.as_ref() == &root))
            {
                window.on_commit();
            }
        };

        xdg_shell::handle_commit(&mut self.popups, &self.space, surface);
        resize_grab::handle_commit(&mut self.space, surface);
        let mapped = smithay::wayland::compositor::with_states(surface, |states| {
            states.data_map.get::<smithay::backend::renderer::utils::RendererSurfaceStateUserData>()
                .is_some_and(|state| state.lock().unwrap().buffer().is_some())
        });
        let first_map = self.windows.iter().find(|(id, window)| {
            self.pending_initial_focus.contains(id)
                && window.toplevel().is_some_and(|top| top.wl_surface() == surface)
        }).map(|(id, _)| *id);
        if let Some(id) = first_map.filter(|_| mapped) {
            self.pending_initial_focus.remove(&id);
            if !self.protocols.is_locked() && self.space.elements().any(|window| {
                window.toplevel().is_some_and(|top| top.wl_surface() == surface)
            }) {
                self.seat.get_keyboard().unwrap().set_focus(
                    self, Some(surface.clone()), smithay::utils::SERIAL_COUNTER.next_serial(),
                );
                self.sync_layer_focus();
            }
        }

        for output in self.space.outputs() {
            let mut map = smithay::desktop::layer_map_for_output(output);
            map.arrange();
            if let Some(layer) =
                map.layer_for_surface(surface, smithay::desktop::WindowSurfaceType::TOPLEVEL)
            {
                if layer.layer_surface().has_pending_changes() {
                    layer.layer_surface().send_configure();
                }
            }
        }
        self.request_redraw();
    }
}

impl BufferHandler for OrbitCompositor {
    fn buffer_destroyed(&mut self, _buffer: &wl_buffer::WlBuffer) {}
}

impl ShmHandler for OrbitCompositor {
    fn shm_state(&self) -> &ShmState {
        &self.shm_state
    }
}

delegate_compositor!(OrbitCompositor);
delegate_shm!(OrbitCompositor);
