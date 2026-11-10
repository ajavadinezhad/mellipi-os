use crate::OrbitCompositor;
use smithay::{
    delegate_layer_shell,
    desktop::{layer_map_for_output, LayerSurface},
    output::Output,
    reexports::wayland_server::protocol::wl_output,
    wayland::shell::wlr_layer::{
        Layer, LayerSurface as WlrLayerSurface, WlrLayerShellHandler, WlrLayerShellState,
    },
};
impl WlrLayerShellHandler for OrbitCompositor {
    fn shell_state(&mut self) -> &mut WlrLayerShellState {
        &mut self.layer_shell_state
    }
    fn new_layer_surface(
        &mut self,
        surface: WlrLayerSurface,
        output: Option<wl_output::WlOutput>,
        _layer: Layer,
        namespace: String,
    ) {
        let Some(output) = output
            .as_ref()
            .and_then(Output::from_resource)
            .or_else(|| self.space.outputs().next().cloned())
        else {
            return;
        };
        layer_map_for_output(&output)
            .map_layer(&LayerSurface::new(surface, namespace))
            .ok();
        self.request_redraw();
    }
    fn layer_destroyed(&mut self, surface: WlrLayerSurface) {
        for output in self.space.outputs() {
            let mut map = layer_map_for_output(output);
            let layer = map
                .layers()
                .find(|l| l.layer_surface() == &surface)
                .cloned();
            if let Some(layer) = layer {
                map.unmap_layer(&layer);
            }
        }
        self.sync_layer_focus();
        self.update_idle_inhibition();
        self.request_redraw();
    }
}
delegate_layer_shell!(OrbitCompositor);

impl OrbitCompositor {
    /// Layer surfaces only steal keyboard focus when explicitly exclusive.
    /// On-demand sheets receive it on click; closing either restores the app.
    pub fn sync_layer_focus(&mut self) {
        if self.protocols.is_locked() {
            return;
        }
        use smithay::{
            reexports::wayland_server::Resource, wayland::seat::WaylandFocus,
            wayland::shell::wlr_layer::KeyboardInteractivity,
        };
        let keyboard = self.seat.get_keyboard().unwrap();
        let current = keyboard.current_focus();
        let mut exclusive = None;
        let mut current_layer = false;
        let mut current_eligible = false;
        for output in self.space.outputs() {
            let map = layer_map_for_output(output);
            for layer in map.layers().rev() {
                if !mapped(layer.wl_surface()) {
                    continue;
                }
                let state = layer.cached_state();
                if current.as_ref() == Some(layer.wl_surface()) {
                    current_layer = true;
                    current_eligible = layer.can_receive_keyboard_focus();
                }
                if exclusive.is_none()
                    && matches!(layer.layer(), Layer::Overlay | Layer::Top)
                    && state.keyboard_interactivity == KeyboardInteractivity::Exclusive
                {
                    exclusive = Some(layer.wl_surface().clone());
                }
            }
        }
        if let Some(surface) = exclusive {
            if current.as_ref() != Some(&surface) {
                if let Some(ref current) = current {
                    if self.windows.iter().any(|(_, window)| {
                        window.wl_surface().is_some_and(|w| w.as_ref() == current)
                    }) {
                        self.protocols.last_window_focus = Some(current.clone());
                    }
                }
                keyboard.set_focus(
                    self,
                    Some(surface),
                    smithay::utils::SERIAL_COUNTER.next_serial(),
                );
            }
        } else if current_layer && !current_eligible
            || current.as_ref().is_some_and(|s| !s.is_alive())
            || current.as_ref().is_some_and(|s| {
                !current_layer
                    && !self
                        .windows
                        .iter()
                        .any(|(_, w)| w.wl_surface().is_some_and(|w| w.as_ref() == s))
            })
        {
            let focus = self
                .protocols
                .last_window_focus
                .take()
                .filter(|s| {
                    s.is_alive()
                        && self.space.elements().any(|window| {
                            window
                                .wl_surface()
                                .is_some_and(|surface| surface.as_ref() == s)
                        })
                })
                .or_else(|| {
                    self.space
                        .elements()
                        .rev()
                        .find_map(|w| w.wl_surface().map(|s| s.into_owned()))
                });
            keyboard.set_focus(self, focus, smithay::utils::SERIAL_COUNTER.next_serial());
        }
    }
    pub fn pointer_layer_focus(
        &mut self,
        pos: smithay::utils::Point<f64, smithay::utils::Logical>,
    ) -> bool {
        use smithay::{desktop::WindowSurfaceType, wayland::seat::WaylandFocus};
        let exclusive = self.space.outputs().any(|output| {
            layer_map_for_output(output).layers().any(|layer| {
                mapped(layer.wl_surface())
                    && matches!(layer.layer(), Layer::Top | Layer::Overlay)
                    && layer.cached_state().keyboard_interactivity
                        == smithay::wayland::shell::wlr_layer::KeyboardInteractivity::Exclusive
            })
        });
        if exclusive {
            return true;
        }
        let target = self.surface_under(pos).map(|(surface, _)| surface);
        let Some(target) = target else {
            return false;
        };
        let mut clicked = None;
        for output in self.space.outputs() {
            let map = layer_map_for_output(output);
            if let Some(layer) = map.layer_for_surface(&target, WindowSurfaceType::ALL) {
                clicked = Some((
                    layer.wl_surface().clone(),
                    layer.can_receive_keyboard_focus(),
                ));
                break;
            }
        }
        let Some((surface, eligible)) = clicked else {
            return false;
        };
        if eligible {
            let keyboard = self.seat.get_keyboard().unwrap();
            if let Some(current) = keyboard.current_focus() {
                if self
                    .windows
                    .iter()
                    .any(|(_, window)| window.wl_surface().is_some_and(|w| w.as_ref() == &current))
                {
                    self.protocols.last_window_focus = Some(current);
                }
            }
            keyboard.set_focus(
                self,
                Some(surface),
                smithay::utils::SERIAL_COUNTER.next_serial(),
            );
        }
        true
    }
}
fn mapped(surface: &smithay::reexports::wayland_server::protocol::wl_surface::WlSurface) -> bool {
    smithay::wayland::compositor::with_states(surface, |states| {
        states
            .data_map
            .get::<smithay::backend::renderer::utils::RendererSurfaceStateUserData>()
            .is_some_and(|state| state.lock().unwrap().buffer().is_some())
    })
}
