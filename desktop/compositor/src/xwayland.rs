//! Rootless Xwayland owned by this compositor, with native scene/window IDs.
//! Derived from Smithay v0.7.0's MIT-licensed Anvil XWM example.
use crate::{CalloopData, OrbitCompositor};
use smithay::{
    delegate_xwayland_shell,
    desktop::{layer_map_for_output, Window},
    input::pointer::Focus,
    reexports::{
        calloop::{EventLoop, LoopHandle},
        wayland_server::{protocol::wl_surface::WlSurface, DisplayHandle},
    },
    utils::{Logical, Point, Rectangle, SERIAL_COUNTER},
    wayland::{
        selection::{
            data_device::{
                clear_data_device_selection, current_data_device_selection_userdata,
                request_data_device_client_selection, set_data_device_selection,
            },
            SelectionSource, SelectionTarget,
        },
        xwayland_shell::{XWaylandShellHandler, XWaylandShellState},
    },
    xwayland::{
        xwm::{Reorder, ResizeEdge, WmWindowProperty, XwmId},
        X11Surface, X11Wm, XWayland, XWaylandEvent, XwmHandler,
    },
};
use std::{collections::HashMap, os::unix::io::OwnedFd, process::Stdio};
#[path = "x11_grab.rs"]
mod grab;

pub struct NativeXwayland {
    pub xwm: Option<X11Wm>,
    pub display: Option<u32>,
    pub shell: XWaylandShellState,
    pub error: Option<String>,
    pub minimized: HashMap<u64, (usize, Point<i32, Logical>)>,
    pub restore: HashMap<u64, Rectangle<i32, Logical>>,
    pub selection_handle: Option<LoopHandle<'static, CalloopData>>,
}
impl NativeXwayland {
    pub fn new(display: &DisplayHandle) -> Self {
        Self {
            xwm: None,
            display: None,
            shell: XWaylandShellState::new::<OrbitCompositor>(display),
            error: None,
            minimized: HashMap::new(),
            restore: HashMap::new(),
            selection_handle: None,
        }
    }
}

/// Starts a separate rootless server; never connects to the parent's DISPLAY.
pub fn start(
    event_loop: &mut EventLoop<'static, CalloopData>,
    data: &mut CalloopData,
) -> Result<(), Box<dyn std::error::Error>> {
    let (source, client) = XWayland::spawn(
        &data.display_handle,
        None,
        std::iter::empty::<(String, String)>(),
        false,
        Stdio::null(),
        Stdio::inherit(),
        |_| (),
    )?;
    let handle = event_loop.handle();
    data.state.xwayland.selection_handle = Some(handle.clone());
    handle
        .clone()
        .insert_source(source, move |event, _, data| match event {
            XWaylandEvent::Ready {
                x11_socket,
                display_number,
            } => {
                match X11Wm::start_wm(handle.clone(), x11_socket, client.clone()) {
                    Ok(mut xwm) => {
                        // A small server-owned arrow avoids an invisible initial X cursor.
                        let mut pixels = vec![0u8; 16 * 20 * 4];
                        for y in 0..16 {
                            for x in 0..=(y / 2).min(7) {
                                let i = (y * 16 + x) * 4;
                                pixels[i..i + 4].copy_from_slice(&[238, 238, 238, 255]);
                            }
                        }
                        let _ = xwm.set_cursor(&pixels, (16, 20).into(), (0, 0).into());
                        data.state.xwayland.xwm = Some(xwm);
                        data.state.xwayland.display = Some(display_number);
                        data.state.xwayland.error = None;
                        data.state.request_redraw();
                    }
                    Err(error) => {
                        data.state.xwayland.error =
                            Some(format!("Could not initialize Xwayland WM: {error}"))
                    }
                }
            }
            XWaylandEvent::Error => {
                data.state.xwayland.error = Some("Xwayland stopped".into());
                data.state.xwayland.display = None;
            }
        })?;
    Ok(())
}

impl XWaylandShellHandler for OrbitCompositor {
    fn xwayland_shell_state(&mut self) -> &mut XWaylandShellState {
        &mut self.xwayland.shell
    }
    fn surface_associated(&mut self, _xwm: XwmId, surface: WlSurface, window: X11Surface) {
        if !self.protocols.is_locked()
            && window.is_activated()
            && self
                .x11_window(&window)
                .is_some_and(|(_, w)| self.space.element_location(&w).is_some())
        {
            self.seat.get_keyboard().unwrap().set_focus(
                self,
                Some(surface),
                SERIAL_COUNTER.next_serial(),
            );
        }
        self.request_redraw();
    }
}
delegate_xwayland_shell!(OrbitCompositor);

impl OrbitCompositor {
    pub fn x11_window(&self, surface: &X11Surface) -> Option<(u64, Window)> {
        self.windows
            .iter()
            .find(|(_, w)| w.x11_surface() == Some(surface))
            .cloned()
    }
    fn register_x11(&mut self, surface: &X11Surface) -> (u64, Window) {
        if let Some(found) = self.x11_window(surface) {
            return found;
        }
        let id = self.next_window_id;
        self.next_window_id += 1;
        let window = Window::new_x11_window(surface.clone());
        self.windows.push((id, window.clone()));
        (id, window)
    }
    fn x11_area(&self, surface: &X11Surface, fullscreen: bool) -> Option<Rectangle<i32, Logical>> {
        let output = self
            .space
            .outputs()
            .find(|output| {
                self.space
                    .output_geometry(output)
                    .is_some_and(|r| r.contains(surface.geometry().loc))
            })
            .or_else(|| self.space.outputs().next())?;
        let output_rect = self.space.output_geometry(output)?;
        if fullscreen {
            Some(output_rect)
        } else {
            let mut area = layer_map_for_output(output).non_exclusive_zone();
            area.loc += output_rect.loc;
            Some(
                self.x11_window(surface)
                    .map(|(_, window)| crate::decoration::client_area(&window, area))
                    .unwrap_or(area),
            )
        }
    }
    pub(crate) fn bounded_x11_geometry(
        &self,
        surface: &X11Surface,
        mut geometry: Rectangle<i32, Logical>,
    ) -> Rectangle<i32, Logical> {
        if let Some(area) = self
            .x11_area(surface, false)
            .filter(|r| r.size.w > 0 && r.size.h > 0)
        {
            let mut min = surface.min_size().unwrap_or((1, 1).into());
            if self
                .x11_window(surface)
                .is_some_and(|(_, window)| crate::decoration::needs_header(&window))
            {
                min.w = min.w.max(110);
                min.h = min.h.max(1);
            }
            let mut max = surface.max_size().unwrap_or(area.size);
            if max.w <= 0 {
                max.w = area.size.w;
            }
            if max.h <= 0 {
                max.h = area.size.h;
            }
            geometry.size.w = geometry.size.w.max(1).clamp(
                min.w.max(1).min(area.size.w),
                max.w.max(min.w).max(1).min(area.size.w),
            );
            geometry.size.h = geometry.size.h.max(1).clamp(
                min.h.max(1).min(area.size.h),
                max.h.max(min.h).max(1).min(area.size.h),
            );
            geometry.loc.x = geometry
                .loc
                .x
                .clamp(area.loc.x, area.loc.x + area.size.w - geometry.size.w);
            geometry.loc.y = geometry
                .loc
                .y
                .clamp(area.loc.y, area.loc.y + area.size.h - geometry.size.h);
        }
        geometry
    }
    pub fn position_x11(&mut self, surface: &X11Surface, geometry: Rectangle<i32, Logical>) {
        if let Some((_, window)) = self.x11_window(surface) {
            if self.space.element_location(&window).is_some() {
                self.space.map_element(window, geometry.loc, false);
            } else if let Some(index) = self
                .workspaces
                .iter()
                .position(|s| s.element_location(&window).is_some())
            {
                self.workspaces[index].map_element(window, geometry.loc, false);
            }
        }
        self.request_redraw();
    }
    pub fn maximize_x11(&mut self, surface: &X11Surface, maximized: bool, fullscreen: bool) {
        let Some((id, window)) = self.x11_window(surface) else {
            return;
        };
        let motion_from=self.window_rect(id);
        let mut motion_to=None;
        if maximized {
            self.xwayland
                .restore
                .entry(id)
                .or_insert(surface.geometry());
            if let Some(geometry) = self.x11_area(surface, fullscreen) {
                if fullscreen {
                    let _ = surface.set_fullscreen(true);
                } else {
                    let _ = surface.set_maximized(true);
                }
                let _ = surface.configure(geometry);
                self.position_x11(surface, geometry);
                motion_to=Some(geometry);
            }
        } else {
            if fullscreen {
                let _ = surface.set_fullscreen(false);
            } else {
                let _ = surface.set_maximized(false);
            }
            if let Some(geometry) = self.xwayland.restore.remove(&id) {
                let geometry = self.bounded_x11_geometry(surface, geometry);
                let _ = surface.configure(geometry);
                self.position_x11(surface, geometry);
                motion_to=Some(geometry);
            }
        }
        if self.space.element_location(&window).is_some() {
            self.space.raise_element(&window, true);
        }
        if let (Some(from),Some(to))=(motion_from,motion_to){self.start_window_resize(id,from,to);}
        self.request_redraw();
    }
    pub fn minimize_x11(&mut self, surface: &X11Surface) {
        let Some((id, window)) = self.x11_window(surface) else {
            return;
        };
        let location = self
            .space
            .element_location(&window)
            .map(|loc| (self.current_workspace, loc))
            .or_else(|| {
                self.workspaces
                    .iter()
                    .enumerate()
                    .find_map(|(i, s)| s.element_location(&window).map(|loc| (i, loc)))
            });
        if let Some(location) = location {
            self.start_window_minimize(id);
            self.xwayland.minimized.insert(id, location);
            self.space.unmap_elem(&window);
            for space in &mut self.workspaces {
                space.unmap_elem(&window);
            }
            let _ = surface.set_suspended(true);
            self.refocus_after_unmap(&window);
        }
        self.request_redraw();
    }
    pub fn restore_x11(&mut self, surface: &X11Surface) {
        let Some((id, window)) = self.x11_window(surface) else {
            return;
        };
        self.window_motions.active.remove(&id);
        if let Some((workspace, location)) = self.xwayland.minimized.remove(&id) {
            let _ = surface.set_suspended(false);
            if workspace == self.current_workspace {
                self.space.map_element(window, location, true);
                self.start_window_open(id);
            } else {
                self.workspaces[workspace].map_element(window, location, false);
            }
        }
        self.request_redraw();
    }
    fn remove_x11(&mut self, surface: &X11Surface, destroyed: bool) {
        if let Some((id, window)) = self.x11_window(surface) {
            self.space.unmap_elem(&window);
            for space in &mut self.workspaces {
                space.unmap_elem(&window);
            }
            self.xwayland.minimized.remove(&id);
            self.refocus_after_unmap(&window);
            if destroyed {
                self.windows.retain(|(other, _)| *other != id);
                self.xwayland.restore.remove(&id);
                self.normal_geometry.remove(&id);
            self.window_motions.active.remove(&id);
            self.window_motions.pending_open.remove(&id);
            }
        }
        self.request_redraw();
    }
    /// Called by the regular Wayland SelectionHandler for client selections.
    pub fn wayland_selection_to_x11(
        &mut self,
        target: SelectionTarget,
        source: Option<SelectionSource>,
    ) {
        if let Some(xwm) = &mut self.xwayland.xwm {
            let _ = xwm.new_selection(target, source.map(|s| s.mime_types()));
        }
    }
    /// Called by SelectionHandler::send_selection for compositor-owned X offers.
    pub fn send_x11_selection(&mut self, target: SelectionTarget, mime: String, fd: OwnedFd) {
        if let (Some(xwm), Some(handle)) = (
            &mut self.xwayland.xwm,
            self.xwayland.selection_handle.clone(),
        ) {
            let _ = xwm.send_selection(target, mime, fd, handle);
        }
    }
}

impl XwmHandler for OrbitCompositor {
    fn property_notify(&mut self, _xwm: XwmId, _window: X11Surface, _property: WmWindowProperty) {
        self.request_redraw();
    }
    fn xwm_state(&mut self, _xwm: XwmId) -> &mut X11Wm {
        self.xwayland
            .xwm
            .as_mut()
            .expect("XWM callbacks require an attached server")
    }
    fn new_window(&mut self, _xwm: XwmId, _window: X11Surface) {}
    fn new_override_redirect_window(&mut self, _xwm: XwmId, _window: X11Surface) {}
    fn map_window_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        if surface.set_mapped(true).is_err() {
            return;
        }
        let (id, window) = self.register_x11(&surface);
        self.queue_window_open(id);
        let mut geometry = surface.geometry();
        if geometry.size.w <= 1 || geometry.size.h <= 1 {
            geometry.size = (640, 420).into();
        }
        if geometry.loc == (0, 0).into() {
            geometry.loc = (80, 80).into();
        }
        geometry = self.bounded_x11_geometry(&surface, geometry);
        let _ = surface.configure(geometry);
        self.space.map_element(window, geometry.loc, true);
        if let Some(focus) = surface.wl_surface().filter(|_| !self.protocols.is_locked()) {
            self.seat.get_keyboard().unwrap().set_focus(
                self,
                Some(focus),
                SERIAL_COUNTER.next_serial(),
            );
        }
        self.request_redraw();
    }
    fn mapped_override_redirect_window(&mut self, _xwm: XwmId, surface: X11Surface) {
        let (_, window) = self.register_x11(&surface);
        self.space
            .map_element(window, surface.geometry().loc, false);
        self.request_redraw();
    }
    fn unmapped_window(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.remove_x11(&surface, false);
        if !surface.is_override_redirect() {
            let _ = surface.set_mapped(false);
        }
    }
    fn destroyed_window(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.remove_x11(&surface, true);
    }
    fn configure_request(
        &mut self,
        _xwm: XwmId,
        surface: X11Surface,
        x: Option<i32>,
        y: Option<i32>,
        w: Option<u32>,
        h: Option<u32>,
        _reorder: Option<Reorder>,
    ) {
        let mut geometry = surface.geometry();
        if let Some(x) = x {
            geometry.loc.x = x;
        }
        if let Some(y) = y {
            geometry.loc.y = y;
        }
        if let Some(w) = w {
            geometry.size.w = w.min(i32::MAX as u32) as i32;
        }
        if let Some(h) = h {
            geometry.size.h = h.min(i32::MAX as u32) as i32;
        }
        if !surface.is_override_redirect() {
            geometry = self.bounded_x11_geometry(&surface, geometry);
        }
        let _ = surface.configure(geometry);
    }
    fn configure_notify(
        &mut self,
        _xwm: XwmId,
        surface: X11Surface,
        geometry: Rectangle<i32, Logical>,
        _above: Option<u32>,
    ) {
        self.position_x11(&surface, geometry);
    }
    fn maximize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.maximize_x11(&surface, true, false);
    }
    fn unmaximize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.maximize_x11(&surface, false, false);
    }
    fn fullscreen_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.maximize_x11(&surface, true, true);
    }
    fn unfullscreen_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.maximize_x11(&surface, false, true);
    }
    fn minimize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.minimize_x11(&surface);
    }
    fn unminimize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        self.restore_x11(&surface);
    }
    fn move_request(&mut self, _xwm: XwmId, surface: X11Surface, button: u32) {
        self.begin_x11_grab(surface, button, None);
    }
    fn resize_request(&mut self, _xwm: XwmId, surface: X11Surface, button: u32, edge: ResizeEdge) {
        self.begin_x11_grab(surface, button, Some(edge));
    }
    fn allow_selection_access(&mut self, _xwm: XwmId, target: SelectionTarget) -> bool {
        !self.protocols.is_locked() && matches!(target, SelectionTarget::Clipboard | SelectionTarget::Primary)
            && self
                .seat
                .get_keyboard()
                .and_then(|k| k.current_focus())
                .is_some_and(|focus| {
                    self.windows.iter().any(|(_, w)| {
                        w.x11_surface()
                            .is_some_and(|x| x.wl_surface().as_ref() == Some(&focus))
                    })
                })
    }
    fn send_selection(&mut self, _xwm: XwmId, target: SelectionTarget, mime: String, fd: OwnedFd) {
        match target {
            SelectionTarget::Clipboard=>{
                let data=current_data_device_selection_userdata(&self.seat).map(|data|data.clone());
                match data {
                    Some(crate::clipboard::SelectionData::Png(bytes)) if mime=="image/png"=>crate::clipboard::send_png(bytes,fd),
                    Some(data) if data.bytes_for(&mime).is_some()=>crate::clipboard::send_png(data.bytes_for(&mime).unwrap(),fd),
                    _=>{let _=request_data_device_client_selection(&self.seat,mime,fd);}
                }
            },
            SelectionTarget::Primary=>{let _=smithay::wayland::selection::primary_selection::request_primary_client_selection(&self.seat,mime,fd);}
        }
    }
    fn new_selection(&mut self, _xwm: XwmId, target: SelectionTarget, mimes: Vec<String>) {
        match target {
            SelectionTarget::Clipboard=>{self.retain_x11_selection(&mimes);set_data_device_selection(&self.display_handle,&self.seat,mimes,crate::clipboard::SelectionData::X11)},
            SelectionTarget::Primary=>smithay::wayland::selection::primary_selection::set_primary_selection(&self.display_handle,&self.seat,mimes,crate::clipboard::SelectionData::X11),
        }
    }
    fn cleared_selection(&mut self, _xwm: XwmId, target: SelectionTarget) {
        match target {
            SelectionTarget::Clipboard=>{
                let owned=current_data_device_selection_userdata(&self.seat).is_some_and(|data|matches!(&*data,crate::clipboard::SelectionData::X11));
                if owned {clear_data_device_selection(&self.display_handle,&self.seat);self.orphan_x11_clipboard();}
            },
            SelectionTarget::Primary=>{
                let owned=smithay::wayland::selection::primary_selection::current_primary_selection_userdata(&self.seat).is_some_and(|data|matches!(&*data,crate::clipboard::SelectionData::X11));
                if owned {smithay::wayland::selection::primary_selection::clear_primary_selection(&self.display_handle,&self.seat);}
            }
        }
    }
    fn disconnected(&mut self, _xwm: XwmId) {
        self.xwayland.display = None;
        self.xwayland.error = Some("Xwayland WM disconnected".into());
    }
}

impl OrbitCompositor {
    pub(crate) fn begin_x11_grab(
        &mut self,
        surface: X11Surface,
        button: u32,
        resize: Option<ResizeEdge>,
    ) {
        if self.protocols.is_locked() || self.transition.is_some() || surface.is_override_redirect()
        {
            return;
        }
        let Some(pointer) = self.seat.get_pointer() else {
            return;
        };
        let Some(start_data) = pointer.grab_start_data() else {
            return;
        };
        let Some((_, window)) = self.x11_window(&surface) else {
            return;
        };
        if self.space.element_location(&window).is_none() {
            return;
        }
        let grab = grab::X11SurfaceGrab {
            start_data,
            initial_rect: surface.geometry(),
            window: surface,
            resize,
            button: match button {
                2 => 0x112,
                3 => 0x111,
                _ => 0x110,
            },
        };
        pointer.set_grab(self, grab, SERIAL_COUNTER.next_serial(), Focus::Clear);
    }
}

// The event loop owns the display and compositor together; protocol dispatch
// still targets OrbitCompositor, while XWM event sources target CalloopData.
impl XWaylandShellHandler for CalloopData {
    fn xwayland_shell_state(&mut self) -> &mut XWaylandShellState {
        &mut self.state.xwayland.shell
    }
    fn surface_associated(&mut self, xwm: XwmId, surface: WlSurface, window: X11Surface) {
        <OrbitCompositor as XWaylandShellHandler>::surface_associated(
            &mut self.state,
            xwm,
            surface,
            window,
        );
    }
}
impl XwmHandler for CalloopData {
    fn property_notify(&mut self, xwm: XwmId, window: X11Surface, property: WmWindowProperty) {
        <OrbitCompositor as XwmHandler>::property_notify(&mut self.state, xwm, window, property);
    }
    fn xwm_state(&mut self, _xwm: XwmId) -> &mut X11Wm {
        <OrbitCompositor as XwmHandler>::xwm_state(&mut self.state, _xwm)
    }
    fn new_window(&mut self, _xwm: XwmId, _window: X11Surface) {
        <OrbitCompositor as XwmHandler>::new_window(&mut self.state, _xwm, _window)
    }
    fn new_override_redirect_window(&mut self, _xwm: XwmId, _window: X11Surface) {
        <OrbitCompositor as XwmHandler>::new_override_redirect_window(
            &mut self.state,
            _xwm,
            _window,
        )
    }
    fn map_window_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::map_window_request(&mut self.state, _xwm, surface)
    }
    fn mapped_override_redirect_window(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::mapped_override_redirect_window(
            &mut self.state,
            _xwm,
            surface,
        )
    }
    fn unmapped_window(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::unmapped_window(&mut self.state, _xwm, surface)
    }
    fn destroyed_window(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::destroyed_window(&mut self.state, _xwm, surface)
    }
    fn configure_request(
        &mut self,
        _xwm: XwmId,
        surface: X11Surface,
        x: Option<i32>,
        y: Option<i32>,
        w: Option<u32>,
        h: Option<u32>,
        _reorder: Option<Reorder>,
    ) {
        <OrbitCompositor as XwmHandler>::configure_request(
            &mut self.state,
            _xwm,
            surface,
            x,
            y,
            w,
            h,
            _reorder,
        )
    }
    fn configure_notify(
        &mut self,
        _xwm: XwmId,
        surface: X11Surface,
        geometry: Rectangle<i32, Logical>,
        _above: Option<u32>,
    ) {
        <OrbitCompositor as XwmHandler>::configure_notify(
            &mut self.state,
            _xwm,
            surface,
            geometry,
            _above,
        )
    }
    fn maximize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::maximize_request(&mut self.state, _xwm, surface)
    }
    fn unmaximize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::unmaximize_request(&mut self.state, _xwm, surface)
    }
    fn fullscreen_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::fullscreen_request(&mut self.state, _xwm, surface)
    }
    fn unfullscreen_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::unfullscreen_request(&mut self.state, _xwm, surface)
    }
    fn minimize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::minimize_request(&mut self.state, _xwm, surface)
    }
    fn unminimize_request(&mut self, _xwm: XwmId, surface: X11Surface) {
        <OrbitCompositor as XwmHandler>::unminimize_request(&mut self.state, _xwm, surface)
    }
    fn move_request(&mut self, _xwm: XwmId, surface: X11Surface, button: u32) {
        <OrbitCompositor as XwmHandler>::move_request(&mut self.state, _xwm, surface, button)
    }
    fn resize_request(&mut self, _xwm: XwmId, surface: X11Surface, button: u32, edge: ResizeEdge) {
        <OrbitCompositor as XwmHandler>::resize_request(
            &mut self.state,
            _xwm,
            surface,
            button,
            edge,
        )
    }
    fn allow_selection_access(&mut self, _xwm: XwmId, target: SelectionTarget) -> bool {
        <OrbitCompositor as XwmHandler>::allow_selection_access(&mut self.state, _xwm, target)
    }
    fn send_selection(&mut self, _xwm: XwmId, target: SelectionTarget, mime: String, fd: OwnedFd) {
        <OrbitCompositor as XwmHandler>::send_selection(&mut self.state, _xwm, target, mime, fd)
    }
    fn new_selection(&mut self, _xwm: XwmId, target: SelectionTarget, mimes: Vec<String>) {
        <OrbitCompositor as XwmHandler>::new_selection(&mut self.state, _xwm, target, mimes)
    }
    fn cleared_selection(&mut self, _xwm: XwmId, target: SelectionTarget) {
        <OrbitCompositor as XwmHandler>::cleared_selection(&mut self.state, _xwm, target)
    }
    fn disconnected(&mut self, _xwm: XwmId) {
        <OrbitCompositor as XwmHandler>::disconnected(&mut self.state, _xwm)
    }
}
