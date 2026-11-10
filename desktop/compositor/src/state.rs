use std::{ffi::OsString, sync::Arc};

use smithay::{
    desktop::{PopupManager, Space, Window, WindowSurfaceType},
    input::{Seat, SeatState},
    reexports::{
        calloop::{generic::Generic, EventLoop, Interest, LoopSignal, Mode, PostAction},
        wayland_server::{
            backend::{ClientData, ClientId, DisconnectReason},
            protocol::wl_surface::WlSurface,
            Display, DisplayHandle,
        },
    },
    utils::{Logical, Point},
    wayland::{
        compositor::{CompositorClientState, CompositorState},
        output::OutputManagerState,
        selection::data_device::DataDeviceState,
        shell::xdg::XdgShellState,
        shm::ShmState,
        socket::ListeningSocketSource,
    },
};

use crate::CalloopData;

pub struct OrbitCompositor {
    pub dmabuf:crate::dmabuf::NativeDmabuf,
    pub clipboard_retention:crate::clipboard::Retention,
    pub clipboard_loop:smithay::reexports::calloop::LoopHandle<'static,CalloopData>,
    pub cursor_light:bool,
    pub cursor_status: smithay::input::pointer::CursorImageStatus,
    pub native_system: crate::native_system::NativeSystem,
    pub ipc: crate::ipc::NativeIpc,
    pub protocols: crate::protocols::NativeProtocols,
    pub xwayland: crate::xwayland::NativeXwayland,
    pub start_time: std::time::Instant,
    pub socket_name: OsString,
    pub display_handle: DisplayHandle,

    pub space: Space<Window>,
    pub workspaces: Vec<Space<Window>>,
    pub current_workspace: usize,
    pub window_motions: crate::window_motion::WindowMotions,
    pub transition: Option<crate::workspaces::Transition>,
    pub pending_workspace: Option<(usize, i32)>,
    pub redraw: Option<Box<dyn Fn()>>,
    pub redraw_pending: bool,
    pub animation_timer_pending: bool,
    pub rendered_frames: u64,
    pub animation_frames: u64,
    pub economy: bool,
    pub reduced_motion: bool,
    pub window_motion_enabled: bool,
    pub windows: Vec<(u64, Window)>,
    pub next_window_id: u64,
    pub pending_initial_focus: std::collections::HashSet<u64>,
    pub normal_geometry: std::collections::HashMap<u64, smithay::utils::Rectangle<i32, Logical>>,
    pub control_path: std::path::PathBuf,
    pub layer_shell_state: smithay::wayland::shell::wlr_layer::WlrLayerShellState,
    pub loop_signal: LoopSignal,

    // Smithay State
    pub compositor_state: CompositorState,
    pub xdg_shell_state: XdgShellState,
    pub shm_state: ShmState,
    pub output_manager_state: OutputManagerState,
    pub seat_state: SeatState<OrbitCompositor>,
    pub data_device_state: DataDeviceState,
    pub primary_selection_state:smithay::wayland::selection::primary_selection::PrimarySelectionState,
    pub popups: PopupManager,
    pub recent_key_serials: Vec<(smithay::utils::Serial, WlSurface)>,

    pub seat: Seat<Self>,
}

impl OrbitCompositor {
    pub fn new(event_loop: &mut EventLoop<'static,CalloopData>, display: Display<Self>) -> Self {
        let start_time = std::time::Instant::now();

        let dh = display.handle();

        let compositor_state = CompositorState::new::<Self>(&dh);
        let xdg_shell_state = XdgShellState::new::<Self>(&dh);
        let shm_state = ShmState::new::<Self>(&dh, vec![]);
        let output_manager_state = OutputManagerState::new_with_xdg_output::<Self>(&dh);
        let mut seat_state = SeatState::new();
        let data_device_state = DataDeviceState::new::<Self>(&dh);
        let primary_selection_state=smithay::wayland::selection::primary_selection::PrimarySelectionState::new::<Self>(&dh);
        let popups = PopupManager::default();

        // A seat is a group of keyboards, pointer and touch devices.
        // A seat typically has a pointer and maintains a keyboard focus and a pointer focus.
        let mut seat: Seat<Self> = seat_state.new_wl_seat(&dh, "winit");

        // Notify clients that we have a keyboard, for the sake of the example we assume that keyboard is always present.
        // You may want to track keyboard hot-plug in real compositor.
        seat.add_keyboard(Default::default(), 200, 25).unwrap();

        // Notify clients that we have a pointer (mouse)
        // Here we assume that there is always pointer plugged in
        seat.add_pointer();

        // A space represents a two-dimensional plane. Windows and Outputs can be mapped onto it.
        //
        // Windows get a position and stacking order through mapping.
        // Outputs become views of a part of the Space and can be rendered via Space::render_output.
        let space = Space::default();

        let socket_name = Self::init_wayland_listener(display, event_loop);

        // Get the loop signal, used to stop the event loop
        let loop_signal = event_loop.get_signal();

        Self {
            dmabuf:Default::default(),
            clipboard_retention:Default::default(),
            clipboard_loop:event_loop.handle(),
            cursor_light:false,
            cursor_status: smithay::input::pointer::CursorImageStatus::default_named(),
            native_system: Default::default(),
            ipc: Default::default(),
            protocols: crate::protocols::NativeProtocols::new(&dh),
            xwayland: crate::xwayland::NativeXwayland::new(&dh),
            start_time,
            display_handle: dh.clone(),

            space,
            workspaces: (0..4).map(|_| Space::default()).collect(),
            current_workspace: 0,
            window_motions: Default::default(),
            transition: None,
            pending_workspace: None,
            redraw: None,
            redraw_pending: false,
            animation_timer_pending: false,
            rendered_frames: 0,
            animation_frames: 0,
            economy: std::env::var("ORBIT_NATIVE_PROFILE").unwrap_or_default() == "economy",
            reduced_motion: std::env::var("ORBIT_NATIVE_REDUCED_MOTION").unwrap_or_default() == "1",
            window_motion_enabled: std::env::var("ORBIT_NATIVE_REDUCED_MOTION").unwrap_or_default() != "1",
            windows: vec![],
            next_window_id: 1,
            pending_initial_focus: std::collections::HashSet::new(),
            normal_geometry: Default::default(),
            control_path: Default::default(),
            layer_shell_state: smithay::wayland::shell::wlr_layer::WlrLayerShellState::new::<Self>(
                &dh,
            ),
            loop_signal,
            socket_name,

            compositor_state,
            xdg_shell_state,
            shm_state,
            output_manager_state,
            seat_state,
            data_device_state,
            primary_selection_state,
            popups,
            recent_key_serials: Vec::new(),
            seat,
        }
    }

    fn init_wayland_listener(
        display: Display<OrbitCompositor>,
        event_loop: &mut EventLoop<CalloopData>,
    ) -> OsString {
        // Creates a new listening socket, automatically choosing the next available `wayland` socket name.
        let listening_socket = ListeningSocketSource::new_auto().unwrap();

        // Get the name of the listening socket.
        // Clients will connect to this socket.
        let socket_name = listening_socket.socket_name().to_os_string();

        let loop_handle = event_loop.handle();

        loop_handle
            .insert_source(listening_socket, move |client_stream, _, state| {
                // Inside the callback, you should insert the client into the display.
                //
                // You may also associate some data with the client when inserting the client.
                let trusted_input_method = crate::protocols::trusted_ime_stream(&client_stream);
                let trusted_virtual_keyboard=crate::protocols::trusted_keyboard_stream(&client_stream);
                state
                    .display_handle
                    .insert_client(
                        client_stream,
                        Arc::new(ClientState {
                            trusted_input_method,
                            trusted_virtual_keyboard,
                            ..Default::default()
                        }),
                    )
                    .unwrap();
            })
            .expect("Failed to init the wayland event source.");

        // You also need to add the display itself to the event loop, so that client events will be processed by wayland-server.
        loop_handle
            .insert_source(
                Generic::new(display, Interest::READ, Mode::Level),
                |_, display, state| {
                    // Safety: we don't drop the display
                    unsafe {
                        display
                            .get_mut()
                            .dispatch_clients(&mut state.state)
                            .unwrap();
                        state.state.promote_orphan_clipboard();
                        display.get_mut().flush_clients().unwrap();
                    }
                    Ok(PostAction::Continue)
                },
            )
            .unwrap();

        socket_name
    }

    pub fn surface_under(
        &self,
        pos: Point<f64, Logical>,
    ) -> Option<(WlSurface, Point<f64, Logical>)> {
        if self.transition.is_some() {
            return None;
        }
        let layer_at = |layers: &[smithay::wayland::shell::wlr_layer::Layer]| {
            for output in self.space.outputs() {
                let Some(output_geometry) = self.space.output_geometry(output) else {
                    continue;
                };
                if !output_geometry.to_f64().contains(pos) {
                    continue;
                }
                let local = pos - output_geometry.loc.to_f64();
                let map = smithay::desktop::layer_map_for_output(output);
                for level in layers {
                    if let Some(layer) = map.layer_under(*level, local) {
                        if let Some(geometry) = map.layer_geometry(layer) {
                            if let Some((surface, point)) = layer.surface_under(
                                local - geometry.loc.to_f64(),
                                WindowSurfaceType::ALL,
                            ) {
                                return Some((
                                    surface,
                                    (point + geometry.loc + output_geometry.loc).to_f64(),
                                ));
                            }
                        }
                    }
                }
            }
            None
        };
        use smithay::wayland::shell::wlr_layer::Layer;
        layer_at(&[Layer::Overlay, Layer::Top])
            .or_else(|| {
                self.space
                    .element_under(pos)
                    .and_then(|(window, location)| {
                        window
                            .surface_under(pos - location.to_f64(), WindowSurfaceType::ALL)
                            .map(|(surface, point)| (surface, (point + location).to_f64()))
                    })
            })
            .or_else(|| layer_at(&[Layer::Bottom, Layer::Background]))
    }
}

#[derive(Default)]
pub struct ClientState {
    pub trusted_input_method: bool,
    pub trusted_virtual_keyboard:bool,
    pub compositor_state: CompositorClientState,
}

impl ClientData for ClientState {
    fn initialized(&self, _client_id: ClientId) {}
    fn disconnected(&self, _client_id: ClientId, _reason: DisconnectReason) {}
}
