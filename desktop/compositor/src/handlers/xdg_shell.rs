use smithay::{
    delegate_xdg_shell,
    desktop::{
        find_popup_root_surface, get_popup_toplevel_coords, PopupKind, PopupManager, PopupKeyboardGrab, PopupPointerGrab, PopupUngrabStrategy, Space, Window,
    },
    input::{
        pointer::{Focus, GrabStartData as PointerGrabStartData},
        Seat,
    },
    reexports::{
        wayland_protocols::xdg::shell::server::xdg_toplevel,
        wayland_server::{
            protocol::{wl_seat, wl_surface::WlSurface},
            Resource,
        },
    },
    utils::{Rectangle, Serial},
    wayland::{
        compositor::with_states,
        shell::xdg::{
            PopupSurface, PositionerState, ToplevelSurface, XdgShellHandler, XdgShellState,
            XdgToplevelSurfaceData,
        },
    },
};

use crate::{
    grabs::{MoveSurfaceGrab, ResizeSurfaceGrab},
    OrbitCompositor,
};

impl XdgShellHandler for OrbitCompositor {
    fn xdg_shell_state(&mut self) -> &mut XdgShellState {
        &mut self.xdg_shell_state
    }

    fn title_changed(&mut self, _surface: ToplevelSurface) {
        self.request_redraw();
    }
    fn app_id_changed(&mut self, _surface: ToplevelSurface) {
        self.request_redraw();
    }
    fn new_toplevel(&mut self, surface: ToplevelSurface) {
        let window = Window::new_wayland_window(surface);
        self.windows.push((self.next_window_id, window.clone()));
        self.queue_window_open(self.next_window_id);
        self.next_window_id += 1;
        self.pending_initial_focus.insert(self.next_window_id - 1);
        self.space.map_element(window, (80, 80), true);
        // Keyboard enter is only legal/useful once the configured toplevel has
        // committed its first buffer. Some clients initialize keyboard state
        // using that configure and cannot handle focus during role creation.
        self.request_redraw();
    }

    fn minimize_request(&mut self, surface: ToplevelSurface) {
        if self.protocols.is_locked() {
            return;
        }
        if let Some(id) = self
            .windows
            .iter()
            .find(|(_, w)| w.toplevel().map(|s| s.wl_surface()) == Some(surface.wl_surface()))
            .map(|(id, _)| *id)
        {
            self.minimize_window(id);
        }
    }
    fn maximize_request(&mut self, surface: ToplevelSurface) {
        let Some((id, window)) = self
            .windows
            .iter()
            .find(|(_, w)| w.toplevel().map(|s| s.wl_surface()) == Some(surface.wl_surface()))
            .cloned()
        else {
            return;
        };
        let location = self
            .space
            .element_location(&window)
            .unwrap_or((0, 0).into());
        let Some(output) = self
            .space
            .outputs()
            .find(|output| {
                self.space
                    .output_geometry(output)
                    .is_some_and(|area| area.contains(location))
            })
            .cloned()
            .or_else(|| self.space.outputs().next().cloned())
        else {
            return;
        };
        if let Some(location) = self.space.element_location(&window) {
            self.normal_geometry
                .entry(id)
                .or_insert(Rectangle::new(location, window.geometry().size));
        }
        let mut area = smithay::desktop::layer_map_for_output(&output).non_exclusive_zone();
        if let Some(geometry) = self.space.output_geometry(&output) {
            area.loc += geometry.loc;
        }
        surface.with_pending_state(|state| {
            state.size = Some(area.size);
            state.states.set(xdg_toplevel::State::Maximized);
        });
        if let Some(from)=self.window_rect(id){self.start_window_resize(id,from,area);}
        self.space.map_element(window, area.loc, true);
        surface.send_configure();
        self.request_redraw();
    }
    fn unmaximize_request(&mut self, surface: ToplevelSurface) {
        let Some((id, window)) = self
            .windows
            .iter()
            .find(|(_, w)| w.toplevel().map(|s| s.wl_surface()) == Some(surface.wl_surface()))
            .cloned()
        else {
            return;
        };
        if let Some(rect) = self.normal_geometry.remove(&id) {
            if let Some(from)=self.window_rect(id){self.start_window_resize(id,from,rect);}
            surface.with_pending_state(|state| {
                state.size = Some(rect.size);
                state.states.unset(xdg_toplevel::State::Maximized);
            });
            self.space.map_element(window, rect.loc, true);
            surface.send_configure();
            self.request_redraw();
        }
    }
    fn toplevel_destroyed(&mut self, surface: ToplevelSurface) {
        let windows: Vec<_> = self
            .windows
            .iter()
            .filter(|(_, w)| w.toplevel().map(|s| s.wl_surface()) == Some(surface.wl_surface()))
            .cloned()
            .collect();
        for (id, window) in windows {
            self.space.unmap_elem(&window);
            for space in &mut self.workspaces {
                space.unmap_elem(&window);
            }
            self.refocus_after_unmap(&window);
            self.pending_initial_focus.remove(&id);
            self.normal_geometry.remove(&id);
            self.window_motions.active.remove(&id);
            self.window_motions.pending_open.remove(&id);
            self.windows.retain(|(other, _)| *other != id);
        }
        self.request_redraw();
    }
    fn new_popup(&mut self, surface: PopupSurface, _positioner: PositionerState) {
        self.unconstrain_popup(&surface);
        let _ = self.popups.track_popup(PopupKind::Xdg(surface));
    }

    fn reposition_request(
        &mut self,
        surface: PopupSurface,
        positioner: PositionerState,
        token: u32,
    ) {
        surface.with_pending_state(|state| {
            let geometry = positioner.get_geometry();
            state.geometry = geometry;
            state.positioner = positioner;
        });
        self.unconstrain_popup(&surface);
        surface.send_repositioned(token);
    }

    fn move_request(&mut self, surface: ToplevelSurface, seat: wl_seat::WlSeat, serial: Serial) {
        if self.protocols.is_locked() {
            return;
        }
        let seat = Seat::from_resource(&seat).unwrap();

        let wl_surface = surface.wl_surface();

        if let Some(start_data) = check_grab(&seat, wl_surface, serial) {
            let pointer = seat.get_pointer().unwrap();

            let window = self
                .space
                .elements()
                .find(|w| w.toplevel().is_some_and(|s| s.wl_surface() == wl_surface))
                .unwrap()
                .clone();
            let initial_window_location = self.space.element_location(&window).unwrap();

            let grab = MoveSurfaceGrab {
                start_data,
                window,
                initial_window_location,
            };

            pointer.set_grab(self, grab, serial, Focus::Clear);
        }
    }

    fn resize_request(
        &mut self,
        surface: ToplevelSurface,
        seat: wl_seat::WlSeat,
        serial: Serial,
        edges: xdg_toplevel::ResizeEdge,
    ) {
        if self.protocols.is_locked() {
            return;
        }
        let seat = Seat::from_resource(&seat).unwrap();

        let wl_surface = surface.wl_surface();

        if let Some(start_data) = check_grab(&seat, wl_surface, serial) {
            let pointer = seat.get_pointer().unwrap();

            let window = self
                .space
                .elements()
                .find(|w| w.toplevel().is_some_and(|s| s.wl_surface() == wl_surface))
                .unwrap()
                .clone();
            let initial_window_location = self.space.element_location(&window).unwrap();
            let initial_window_size = window.geometry().size;

            surface.with_pending_state(|state| {
                state.states.set(xdg_toplevel::State::Resizing);
            });

            surface.send_pending_configure();

            let grab = ResizeSurfaceGrab::start(
                start_data,
                window,
                edges.into(),
                Rectangle::new(initial_window_location, initial_window_size),
            );

            pointer.set_grab(self, grab, serial, Focus::Clear);
        }
    }

    fn grab(&mut self, surface: PopupSurface, seat: wl_seat::WlSeat, serial: Serial) {
        if self.protocols.is_locked() { return; }
        let Some(seat) = Seat::<OrbitCompositor>::from_resource(&seat) else { return; };
        let popup = PopupKind::Xdg(surface);
        let Ok(root) = find_popup_root_surface(&popup) else { return; };
        let Some(pointer) = seat.get_pointer() else { return; };
        let Some(keyboard) = seat.get_keyboard() else { return; };
        if !keyboard.current_focus().is_some_and(|focus| focus.id().same_client_as(&root.id())) { return; }
        let key_serial = self.recent_key_serials.iter().any(|(sent, focus)| *sent == serial && focus.id().same_client_as(&root.id()));
        if check_grab(&seat, &root, serial).is_none() && !keyboard.has_grab(serial) && !key_serial { return; }
        if let Ok(mut grab) = self.popups.grab_popup(root, popup, &seat, serial) {
            let previous = grab.previous_serial().unwrap_or(serial);
            if (keyboard.is_grabbed() && !keyboard.has_grab(serial) && !keyboard.has_grab(previous))
                || (pointer.is_grabbed() && !pointer.has_grab(serial) && !pointer.has_grab(previous)) {
                grab.ungrab(PopupUngrabStrategy::All);
                return;
            }
            keyboard.set_focus(self, grab.current_grab(), serial);
            keyboard.set_grab(self, PopupKeyboardGrab::new(&grab), serial);
            pointer.set_grab(self, PopupPointerGrab::new(&grab), serial, Focus::Keep);
        }
    }
}

// Xdg Shell
delegate_xdg_shell!(OrbitCompositor);

fn check_grab(
    seat: &Seat<OrbitCompositor>,
    surface: &WlSurface,
    serial: Serial,
) -> Option<PointerGrabStartData<OrbitCompositor>> {
    let pointer = seat.get_pointer()?;

    // Check that this surface has a click grab.
    if !pointer.has_grab(serial) {
        return None;
    }

    let start_data = pointer.grab_start_data()?;

    let (focus, _) = start_data.focus.as_ref()?;
    // If the focus was for a different surface, ignore the request.
    if !focus.id().same_client_as(&surface.id()) {
        return None;
    }

    Some(start_data)
}

/// Should be called on `WlSurface::commit`
pub fn handle_commit(popups: &mut PopupManager, space: &Space<Window>, surface: &WlSurface) {
    // Handle toplevel commits.
    if let Some(window) = space
        .elements()
        .find(|w| w.toplevel().is_some_and(|s| s.wl_surface() == surface))
        .cloned()
    {
        let initial_configure_sent = with_states(surface, |states| {
            states
                .data_map
                .get::<XdgToplevelSurfaceData>()
                .unwrap()
                .lock()
                .unwrap()
                .initial_configure_sent
        });

        if !initial_configure_sent {
            window.toplevel().unwrap().send_configure();
        }
    }

    // Handle popup commits.
    popups.commit(surface);
    if let Some(popup) = popups.find_popup(surface) {
        match popup {
            PopupKind::Xdg(ref xdg) => {
                if !xdg.is_initial_configure_sent() {
                    // NOTE: This should never fail as the initial configure is always
                    // allowed.
                    xdg.send_configure().expect("initial configure failed");
                }
            }
            PopupKind::InputMethod(ref _input_method) => {}
        }
    }
}

impl OrbitCompositor {
    fn unconstrain_popup(&self, popup: &PopupSurface) {
        let Ok(root) = find_popup_root_surface(&PopupKind::Xdg(popup.clone())) else {
            return;
        };
        let Some(window) = self
            .space
            .elements()
            .find(|w| w.toplevel().is_some_and(|s| s.wl_surface() == &root))
        else {
            return;
        };

        let output = self.space.outputs().next().unwrap();
        let output_geo = self.space.output_geometry(output).unwrap();
        let window_geo = self.space.element_geometry(window).unwrap();

        // The target geometry for the positioner should be relative to its parent's geometry, so
        // we will compute that here.
        let mut target = output_geo;
        target.loc -= get_popup_toplevel_coords(&PopupKind::Xdg(popup.clone()));
        target.loc -= window_geo.loc;

        popup.with_pending_state(|state| {
            state.geometry = state.positioner.get_unconstrained_geometry(target);
        });
    }
}
