mod compositor;
mod layer_shell;
mod xdg_shell;

use crate::OrbitCompositor;

//
// Wl Seat
//

use smithay::input::{Seat, SeatHandler, SeatState};
use smithay::reexports::wayland_server::protocol::wl_surface::WlSurface;
use smithay::reexports::wayland_server::Resource;
use smithay::wayland::output::OutputHandler;
use smithay::wayland::selection::data_device::{
    set_data_device_focus, ClientDndGrabHandler, DataDeviceHandler, DataDeviceState,
    ServerDndGrabHandler,
};
use smithay::wayland::selection::SelectionHandler;
use smithay::{delegate_data_device, delegate_output, delegate_seat};

impl SeatHandler for OrbitCompositor {
    type KeyboardFocus = WlSurface;
    type PointerFocus = WlSurface;
    type TouchFocus = WlSurface;

    fn seat_state(&mut self) -> &mut SeatState<OrbitCompositor> {
        &mut self.seat_state
    }

    fn cursor_image(
        &mut self,
        _seat: &Seat<Self>,
        image: smithay::input::pointer::CursorImageStatus,
    ) {
        self.cursor_status = image;
        self.request_redraw();
    }

    fn focus_changed(&mut self, seat: &Seat<Self>, focused: Option<&WlSurface>) {
        let dh = &self.display_handle;
        let client = focused.and_then(|s| dh.get_client(s.id()).ok());
        set_data_device_focus(dh, seat, client.clone());
        smithay::wayland::selection::primary_selection::set_primary_focus(dh,seat,client);
    }
}

delegate_seat!(OrbitCompositor);

//
// Wl Data Device
//

impl SelectionHandler for OrbitCompositor {
    type SelectionUserData = crate::clipboard::SelectionData;
    fn new_selection(
        &mut self,
        target: smithay::wayland::selection::SelectionTarget,
        source: Option<smithay::wayland::selection::SelectionSource>,
        _seat: Seat<Self>,
    ) {
        self.retain_selection(target,source.clone());
        self.wayland_selection_to_x11(target, source);
    }
    fn send_selection(
        &mut self,
        target: smithay::wayland::selection::SelectionTarget,
        mime: String,
        fd: std::os::fd::OwnedFd,
        _seat: Seat<Self>,
        userdata: &Self::SelectionUserData,
    ) {
        if let Some(bytes)=userdata.bytes_for(&mime){crate::clipboard::send_png(bytes,fd);}
        else if matches!(userdata,crate::clipboard::SelectionData::X11){self.send_x11_selection(target,mime,fd);}

    }
}

impl DataDeviceHandler for OrbitCompositor {
    fn data_device_state(&self) -> &DataDeviceState {
        &self.data_device_state
    }
}

impl ClientDndGrabHandler for OrbitCompositor {}
impl ServerDndGrabHandler for OrbitCompositor {}

delegate_data_device!(OrbitCompositor);

//
// Wl Output & Xdg Output
//

impl OutputHandler for OrbitCompositor {}
delegate_output!(OrbitCompositor);

impl smithay::wayland::selection::primary_selection::PrimarySelectionHandler for OrbitCompositor {
    fn primary_selection_state(&self)->&smithay::wayland::selection::primary_selection::PrimarySelectionState{&self.primary_selection_state}
}
smithay::delegate_primary_selection!(OrbitCompositor);
