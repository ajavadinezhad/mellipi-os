//! Standalone Linux seat/DRM backend. Never acquire a seat from a running desktop.
//!
//! Uses libseat for device/VT ownership, libinput for real input, GBM scanout
//! swapchains, EGL/GLES for composition, and KMS vblank completion for pacing.
//! No screen captures, polling frame loop, or direct /dev/input opens.
use crate::{CalloopData, OrbitCompositor};
use smithay::{
    backend::{
        allocator::{
            gbm::{GbmAllocator, GbmBufferFlags, GbmDevice},
            Fourcc,
        },
        drm::{DrmDevice, DrmDeviceFd, DrmEvent, GbmBufferedSurface},
        egl::{EGLContext, EGLDisplay},
        input::{Event as InputTime, InputEvent, KeyState, KeyboardKeyEvent, PointerMotionEvent},
        libinput::{LibinputInputBackend, LibinputSessionInterface},
        renderer::{
            damage::OutputDamageTracker,
            element::{
                memory::{MemoryRenderBuffer, MemoryRenderBufferRenderElement},
                surface::WaylandSurfaceRenderElement,
                AsRenderElements, Kind,
            },
            gles::GlesRenderer,
            Bind, ImportAll, ImportMem, ImportDma,
        },
        session::{libseat::LibSeatSession, Event as SessionEvent, Session},
        udev::{primary_gpu, UdevBackend, UdevEvent},
    },
    desktop::layer_map_for_output,
    input::pointer::MotionEvent,
    output::{Mode, Output, PhysicalProperties, Subpixel},
    reexports::{
        calloop::{
            ping::make_ping,
            timer::{TimeoutAction, Timer},
            EventLoop,
        },
        drm::control::{connector, crtc, Device, ModeTypeFlags},
        input::Libinput,
        rustix::fs::OFlags,
        wayland_server::backend::GlobalId,
    },
    utils::{DeviceFd, Logical, Point, Transform, SERIAL_COUNTER},
    wayland::shell::wlr_layer::Layer,
};
use std::{
    cell::RefCell,
    collections::{HashMap, HashSet},
    error::Error,
    path::PathBuf,
    rc::Rc,
    time::Duration,
};

smithay::backend::renderer::element::render_elements! {
 pub DrmRenderElement<R> where R: ImportAll + ImportMem;
 Surface=WaylandSurfaceRenderElement<R>,
 Window=crate::window_motion::WindowRenderElement<R>,
 Cursor=MemoryRenderBufferRenderElement<R>,
}

type Scanout = GbmBufferedSurface<GbmAllocator<DrmDeviceFd>, ()>;
struct Surface {
    connector: connector::Handle,
    output: Output,
    global: GlobalId,
    scanout: Scanout,
    damage: OutputDamageTracker,
    pending: bool,
    queued_locked: bool,
    dirty: bool,
}
struct Backend {
    session: LibSeatSession,
    path: PathBuf,
    drm: DrmDevice,
    gbm: GbmDevice<DrmDeviceFd>,
    renderer: GlesRenderer,
    surfaces: HashMap<crtc::Handle, Surface>,
    active: bool,
    powered_off: bool,
    initializing: bool,
    saved_restores: HashMap<String, serde_json::Value>,
    cursor: (MemoryRenderBuffer,Point<i32,Logical>),
    cursor_light: (MemoryRenderBuffer,Point<i32,Logical>),
}

/// Read-only readiness information. This never creates a libseat session or
/// opens a card, changes its mode, grabs input, or switches a VT.
pub fn preflight() -> serde_json::Value {
    let cards = std::fs::read_dir("/dev/dri")
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .map(|name| name.to_string_lossy().starts_with("card"))
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();
    let displays=std::fs::read_dir("/sys/class/drm").into_iter().flatten().filter_map(Result::ok).filter_map(|entry|{
  let status=std::fs::read_to_string(entry.path().join("status")).ok()?;
  Some(serde_json::json!({"name":entry.file_name().to_string_lossy(),"status":status.trim()}))
 }).collect::<Vec<_>>();
    serde_json::json!({"backend":"drm","compiled":true,"cards":cards,"connectors":displays,"hardware_validated":false,"seat_acquired":false,"in_graphical_session":in_graphical_session()})
}
fn in_graphical_session() -> bool {
    ["WAYLAND_DISPLAY", "DISPLAY", "SWAYSOCK"]
        .iter()
        .any(|key| {
            std::env::var_os(key)
                .map(|v| !v.is_empty())
                .unwrap_or(false)
        })
}

fn saved_output_path() -> PathBuf {
    std::env::var_os("ORBIT_DATA").map(PathBuf::from).unwrap_or_else(|| {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().join("data")
    }).join("outputs-native.json")
}

fn saved_output_settings(path: &std::path::Path) -> HashMap<String, serde_json::Value> {
    use std::{io::Read, os::unix::fs::{MetadataExt, OpenOptionsExt}};
    // Reopen after a connector event so later confirmed edits are picked up.
    // A bounded no-follow read cannot chase a swapped symlink or oversized file.
    let read = || -> Option<HashMap<String, serde_json::Value>> {
        let file=std::fs::OpenOptions::new().read(true).custom_flags(
            (smithay::reexports::rustix::fs::OFlags::NOFOLLOW | smithay::reexports::rustix::fs::OFlags::NONBLOCK).bits() as i32
        ).open(path).ok()?;
        let metadata=file.metadata().ok()?;
        if !metadata.is_file() || metadata.uid()!=smithay::reexports::rustix::process::getuid().as_raw() || metadata.mode() & 0o022 != 0 || metadata.len()>65536 { return None; }
        let mut text=String::new();file.take(65537).read_to_string(&mut text).ok()?;
        if text.len()>65536 { return None; }
        let value:serde_json::Value=serde_json::from_str(&text).ok()?;
        let rows=value.as_object()?;
        if rows.len()>32 { return None; }
        Some(rows.iter().filter(|(name,settings)| {
            !name.is_empty() && name.len()<=128 && name.bytes().all(|c|c.is_ascii_alphanumeric() || b"_.-".contains(&c))
                && settings.is_object() && settings["name"].as_str()==Some(name.as_str())
        }).map(|(name,settings)|(name.clone(),settings.clone())).collect())
    };
    read().unwrap_or_default()
}

fn selected_saved_outputs(saved: &HashMap<String,serde_json::Value>, added: &HashSet<String>) -> HashMap<String,serde_json::Value> {
    saved.iter().filter(|(name,_)|added.contains(*name)).map(|(name,settings)|(name.clone(),settings.clone())).collect()
}

fn saved_restore_names(saved: &mut HashMap<String,serde_json::Value>, current: &HashMap<String,bool>, transaction: Option<&str>) -> Vec<String> {
    // A disconnected output or a user-owned transaction cancels its queued
    // restore. A frame still in flight merely defers it to a completion event.
    saved.retain(|name,_|current.contains_key(name) && transaction!=Some(name.as_str()));
    saved.keys().filter(|name|current.get(*name)==Some(&false)).cloned().collect()
}

pub fn init_drm(
    event_loop: &mut EventLoop<'static, CalloopData>,
    data: &mut CalloopData,
) -> Result<(), Box<dyn Error>> {
    if in_graphical_session() {
        return Err("Refusing DRM acquisition inside a running graphical session; use nested mode, or start the native login session from the greeter/TTY".into());
    }
    let (mut session, notifier) = LibSeatSession::new()?;
    let seat = session.seat();
    let path = if let Some(path) = std::env::var_os("ORBIT_DRM_DEVICE") {
        PathBuf::from(path)
    } else {
        primary_gpu(&seat)?.ok_or("No primary DRM GPU on this seat")?
    };
    let owned = session.open(
        &path,
        OFlags::RDWR | OFlags::CLOEXEC | OFlags::NOCTTY | OFlags::NONBLOCK,
    )?;
    let fd = DrmDeviceFd::new(DeviceFd::from(owned));
    let (drm, drm_events) = DrmDevice::new(fd.clone(), true)?;
    let gbm = GbmDevice::new(fd)?;
    // Safety: GBM device remains alive in Backend while EGL and the renderer use it.
    let egl = unsafe { EGLDisplay::new(gbm.clone())? };
    let context = EGLContext::new(&egl)?;
    let renderer = unsafe { GlesRenderer::new(context)? };
    let backend = Rc::new(RefCell::new(Backend {
        session: session.clone(),
        path,
        drm,
        gbm,
        renderer,
        surfaces: HashMap::new(),
        active: true,
        powered_off: false,
        initializing: true,
        saved_restores: HashMap::new(),
        cursor: default_cursor(false),
        cursor_light:default_cursor(true),
    }));
    use std::os::unix::fs::MetadataExt;
    let formats=backend.borrow().renderer.dmabuf_formats().iter().copied().collect();
    let device=crate::dmabuf::renderer_device(&backend.borrow().renderer).or_else(||std::fs::metadata(&backend.borrow().path).ok().map(|meta|meta.rdev()));
    let importer=backend.clone();
    data.state.setup_dmabuf(formats,device,Box::new(move|buffer|importer.try_borrow_mut().is_ok_and(|mut backend|crate::dmabuf::validate(&mut backend.renderer,buffer))));
    backend.borrow_mut().scan_outputs(&mut data.state)?;
    data.state.load_native_input();
    let system_backend = backend.clone();
    data.state.native_system.output = Some(Box::new(move |state, value| {
        system_backend.borrow_mut().system_control(state, value)
    }));
    // Initial connector discovery queued the same bounded confirmed settings
    // used for later reconnects. No frame is submitted until startup is ready.
    backend.borrow_mut().restore_saved_outputs(&mut data.state);
    backend.borrow_mut().initializing = false;
    if backend.borrow().surfaces.is_empty() {
        return Err("No connected display with a usable CRTC/mode".into());
    }
    let (ping, ping_source) = make_ping()?;
    let redraw = ping.clone();
    data.state.redraw = Some(Box::new(move || redraw.ping()));
    let handle = event_loop.handle();
    let timer_handle = handle.clone();
    let paint = backend.clone();
    handle.insert_source(ping_source, move |_, _, data| {
        let mut backend = paint.borrow_mut();
        for surface in backend.surfaces.values_mut() {
            surface.dirty = true;
        }
        backend.restore_saved_outputs(&mut data.state);
        if let Err(error) = backend.render(&mut data.state) {
            tracing::error!(%error,"DRM composition failed");
        }
        if backend.active && !backend.powered_off {
            schedule_animation(&timer_handle, &mut data.state);
        }
    })?;
    let vblank = backend.clone();
    let timer_handle = handle.clone();
    handle.insert_source(drm_events, move |event, _, data| {
        let mut backend = vblank.borrow_mut();
        match event {
            DrmEvent::VBlank(crtc) => {
                if let Some(surface) = backend.surfaces.get_mut(&crtc) {
                    if let Err(error) = surface.scanout.frame_submitted() {
                        tracing::warn!(%error,"DRM pageflip completion failed");
                        return;
                    }
                    if surface.pending && surface.queued_locked && data.state.protocols.is_locked()
                    {
                        data.state.protocols.output_presented(&surface.output);
                        data.state
                            .protocols
                            .lock_send_frames(&surface.output, data.state.start_time.elapsed());
                    }
                    surface.pending = false;
                }
                backend.restore_saved_outputs(&mut data.state);
                if let Err(error) = backend.render(&mut data.state) {
                    tracing::error!(%error,"DRM repaint failed");
                }
                if backend.active && !backend.powered_off {
                    schedule_animation(&timer_handle, &mut data.state);
                }
            }
            DrmEvent::Error(error) => tracing::error!(%error,"DRM event error"),
        }
    })?;
    let mut libinput =
        Libinput::new_with_udev::<LibinputSessionInterface<LibSeatSession>>(session.clone().into());
    libinput
        .udev_assign_seat(&seat)
        .map_err(|_| "Cannot assign libinput to the login seat")?;
    let input = LibinputInputBackend::new(libinput.clone());
    let input_backend = backend.clone();
    let input_token=handle.insert_source(input, move |event, _, data| {
        data.state.notify_activity();
        match &event {
            InputEvent::DeviceAdded { device } => {
                data.state
                    .native_system
                    .devices
                    .retain(|d| d.sysname() != device.sysname());
                data.state.native_system.devices.push(device.clone());
                let values = data.state.native_system.values.clone();
                let fields = data.state.native_system.configured.clone();
                let _ = data.state.apply_native_input(&values, &fields, "");
                let profile = data
                    .state
                    .native_system
                    .overrides
                    .get(&crate::native_system::native_device_id(device))
                    .cloned();
                if let Some(profile) = profile {
                    if let Some(keys) = profile["configured"].as_array() {
                        let keys = keys
                            .iter()
                            .filter_map(|v| v.as_str().map(str::to_owned))
                            .collect::<Vec<_>>();
                        let _ = data.state.apply_native_input(
                            &profile["values"],
                            &keys,
                            &crate::native_system::native_device_id(device),
                        );
                    }
                }
                data.state.request_redraw();
                return;
            }
            InputEvent::DeviceRemoved { device } => {
                data.state
                    .native_system
                    .devices
                    .retain(|d| d.sysname() != device.sysname());
                data.state.request_redraw();
                return;
            }
            _ => {}
        }
        if input_backend.borrow().powered_off {
            let _ = input_backend.borrow_mut().wake(&mut data.state);
        }

        if !input_backend.borrow().active {
            return;
        }
        match &event {
            InputEvent::Keyboard { event, .. } if event.state() == KeyState::Pressed => {
                let modifiers = data.state.seat.get_keyboard().unwrap().modifier_state();
                if modifiers.ctrl && modifiers.alt {
                    let code = event.key_code().raw();
                    let vt = if (67..=76).contains(&code) {
                        Some((code - 66) as i32)
                    } else if code == 95 {
                        Some(11)
                    } else if code == 96 {
                        Some(12)
                    } else {
                        None
                    };
                    if let Some(vt) = vt {
                        if let Err(error) = input_backend.borrow_mut().session.change_vt(vt) {
                            tracing::warn!(%error,"VT switch failed");
                        }
                        return;
                    }
                }
            }
            _ => {}
        }
        if data.state.protocols.is_locked() {
            data.state.process_locked_input(event);
            let _ = data.display_handle.flush_clients();
            data.state.request_redraw();
            return;
        }
        if let InputEvent::PointerMotion { event, .. } = &event {
            let pointer = data.state.seat.get_pointer().unwrap();
            let current = pointer.current_location();
            let next = clamp_pointer(&data.state, current + event.delta());
            let focus = data.state.surface_under(next);
            pointer.motion(
                &mut data.state,
                focus,
                &MotionEvent {
                    location: next,
                    serial: SERIAL_COUNTER.next_serial(),
                    time: event.time_msec(),
                },
            );
            pointer.frame(&mut data.state);
        } else {
            data.state.process_input_event(event);
        }
        let _ = data.display_handle.flush_clients();
        data.state.request_redraw();
    })?;
    let resume = backend.clone();
    let input_handle=handle.clone();
    handle.insert_source(notifier, move |event, _, data| {
        let mut backend = resume.borrow_mut();
        match event {
            SessionEvent::PauseSession => {
                backend.active = false;
                data.state.native_system.devices.clear();
                libinput.suspend();
                backend.drm.pause();
                for surface in backend.surfaces.values_mut() {
                    surface.pending = false;
                    surface.dirty = true;
                    surface.scanout.reset_buffers();
                }
            }
            SessionEvent::ActivateSession => {
                if let Err(error) = libinput.resume() {
                    tracing::error!(?error, "libinput resume failed");
                }
                // Re-arm the normal one-shot dispatch for libinput's internally
                // queued device events; do not drain or drop input manually.
                if let Err(error)=input_handle.update(&input_token) {
                    tracing::warn!(%error,"Input event source resume registration failed");
                }
                if let Err(error) = backend.drm.activate(true) {
                    tracing::error!(%error,"DRM resume failed");
                    return;
                }
                backend.active = true;
                data.state.redraw_pending = false;
                for surface in backend.surfaces.values_mut() {
                    surface.pending = false;
                    surface.dirty = true;
                    surface.scanout.reset_buffers();
                }
                if let Err(error) = backend.scan_outputs(&mut data.state) {
                    tracing::error!(%error,"Display rescan after resume failed");
                }
                data.state.request_redraw();
            }
        }
    })?;
    let udev = UdevBackend::new(&seat)?;
    let hotplug = backend.clone();
    handle.insert_source(udev, move |event, _, data| match event {
        UdevEvent::Changed { .. } | UdevEvent::Added { .. } | UdevEvent::Removed { .. } => {
            let mut backend = hotplug.borrow_mut();
            if let Err(error) = backend.scan_outputs(&mut data.state) {
                tracing::warn!(%error,"DRM hotplug rescan failed");
            }
            data.state.request_redraw();
        }
    })?;
    std::env::set_var("WAYLAND_DISPLAY", &data.state.socket_name);
    data.state.redraw_pending = false;
    data.state.request_redraw();
    Ok(())
}

fn schedule_animation(
    handle: &smithay::reexports::calloop::LoopHandle<'static, CalloopData>,
    state: &mut OrbitCompositor,
) {
    if state.has_animations() && !state.animation_timer_pending {
        state.animation_timer_pending = true;
        let delay = Duration::from_millis(if state.economy { 33 } else { 16 });
        if let Err(error) = handle.insert_source(Timer::from_duration(delay), |_, _, data| {
            data.state.animation_timer_pending = false;
            data.state.request_redraw();
            TimeoutAction::Drop
        }) {
            tracing::error!(%error,"Cannot schedule native animation");
            state.animation_timer_pending = false;
        }
    }
}
fn clamp_pointer(state: &OrbitCompositor, point: Point<f64, Logical>) -> Point<f64, Logical> {
    let rectangles = state
        .space
        .outputs()
        .filter_map(|output| state.space.output_geometry(output))
        .collect::<Vec<_>>();
    if rectangles.iter().any(|rect| rect.to_f64().contains(point)) {
        return point;
    }
    rectangles
        .iter()
        .map(|rect| {
            Point::from((
                point
                    .x
                    .clamp(rect.loc.x as f64, (rect.loc.x + rect.size.w - 1) as f64),
                point
                    .y
                    .clamp(rect.loc.y as f64, (rect.loc.y + rect.size.h - 1) as f64),
            ))
        })
        .min_by(|a, b| {
            ((a.x - point.x).powi(2) + (a.y - point.y).powi(2))
                .total_cmp(&((b.x - point.x).powi(2) + (b.y - point.y).powi(2)))
        })
        .unwrap_or(point)
}
fn default_cursor(light:bool) -> (MemoryRenderBuffer,Point<i32,Logical>) {
    let image=crate::cursor_theme::load(light);
    (MemoryRenderBuffer::from_slice(&image.pixels,Fourcc::Argb8888,(image.width,image.height),1,Transform::Normal,None),(image.xhot,image.yhot).into())
}

impl Backend {
    fn scan_outputs(&mut self, state: &mut OrbitCompositor) -> Result<(), Box<dyn Error>> {
        if !self.active {
            return Ok(());
        }
        let previous_names = self.surfaces.values().map(|surface|surface.output.name()).collect::<HashSet<_>>();
        let resources = self.drm.resource_handles()?;
        let mut plans = Vec::new();
        let mut used = HashSet::new();
        for handle in resources.connectors() {
            let info = self.drm.get_connector(*handle, true)?;
            if info.state() != connector::State::Connected {
                continue;
            }
            let previous_mode = self
                .surfaces
                .values()
                .find(|s| s.connector == *handle)
                .map(|s| s.scanout.pending_mode());
            let Some(mode) = info
                .modes()
                .iter()
                .find(|mode| previous_mode == Some(**mode))
                .or_else(|| {
                    info.modes()
                        .iter()
                        .find(|mode| mode.mode_type().contains(ModeTypeFlags::PREFERRED))
                })
                .or_else(|| info.modes().first())
                .copied()
            else {
                continue;
            };
            let mut candidates = Vec::new();
            for encoder in info.encoders() {
                if let Ok(encoder) = self.drm.get_encoder(*encoder) {
                    candidates.extend(resources.filter_crtcs(encoder.possible_crtcs()));
                }
            }
            let existing = self
                .surfaces
                .iter()
                .find(|(_, s)| s.connector == *handle)
                .map(|(c, _)| *c);
            let selected = existing
                .filter(|c| candidates.contains(c) && !used.contains(c))
                .or_else(|| candidates.into_iter().find(|c| !used.contains(c)));
            if let Some(crtc) = selected {
                used.insert(crtc);
                plans.push((crtc, info, mode));
            }
        }
        let obsolete = self
            .surfaces
            .iter()
            .filter(|(crtc, s)| {
                !plans.iter().any(|(c, i, m)| {
                    c == *crtc && i.handle() == s.connector && *m == s.scanout.pending_mode()
                })
            })
            .map(|(c, _)| *c)
            .collect::<Vec<_>>();
        for crtc in obsolete {
            if let Some(surface) = self.surfaces.remove(&crtc) {
                state.protocols.output_removed(&surface.output);
                state.space.unmap_output(&surface.output);
                for space in &mut state.workspaces {
                    space.unmap_output(&surface.output);
                }
                state
                    .display_handle
                    .remove_global::<OrbitCompositor>(surface.global);
            }
        }
        plans.sort_by_key(|(_, info, _)| format!("{:?}-{}", info.interface(), info.interface_id()));
        let mut x = 0;
        for (crtc, info, mode) in plans {
            if !self.surfaces.contains_key(&crtc) {
                let drm_surface = self.drm.create_surface(crtc, mode, &[info.handle()])?;
                let allocator = GbmAllocator::new(
                    self.gbm.clone(),
                    GbmBufferFlags::RENDERING | GbmBufferFlags::SCANOUT,
                );
                let formats = self
                    .renderer
                    .egl_context()
                    .dmabuf_render_formats()
                    .iter()
                    .copied()
                    .collect::<Vec<_>>();
                let scanout = GbmBufferedSurface::new(
                    drm_surface,
                    allocator,
                    &[Fourcc::Argb8888, Fourcc::Xrgb8888],
                    formats,
                )?;
                let output = Output::new(
                    format!("{:?}-{}", info.interface(), info.interface_id()),
                    PhysicalProperties {
                        size: info
                            .size()
                            .map(|(w, h)| (w as i32, h as i32))
                            .unwrap_or((0, 0))
                            .into(),
                        subpixel: Subpixel::Unknown,
                        make: "Orbit DRM".into(),
                        model: format!("{:?}", info.interface()),
                    },
                );
                let global = output.create_global::<OrbitCompositor>(&state.display_handle);
                let wlmode = Mode::from(mode);
                output.change_current_state(
                    Some(wlmode),
                    Some(Transform::Normal),
                    None,
                    Some((x, 0).into()),
                );
                output.set_preferred(wlmode);
                state.protocols.output_changed(&output);
                for mode in info.modes() {
                    output.add_mode(Mode::from(*mode));
                }
                self.surfaces.insert(
                    crtc,
                    Surface {
                        connector: info.handle(),
                        damage: OutputDamageTracker::from_output(&output),
                        output,
                        global,
                        scanout,
                        pending: false,
                        queued_locked: false,
                        dirty: true,
                    },
                );
            }
            let surface = self.surfaces.get_mut(&crtc).unwrap();
            state
                .space
                .map_output(&surface.output, surface.output.current_location());
            for space in &mut state.workspaces {
                space.map_output(&surface.output, surface.output.current_location());
            }
            layer_map_for_output(&surface.output).arrange();
            state.reconfigure_output_windows(&surface.output);
            x += surface.output.current_mode().unwrap().size.w;
        }
        // Keep windows reachable when an unplugged monitor disappears.
        let outputs = state
            .space
            .outputs()
            .filter_map(|o| state.space.output_geometry(o))
            .collect::<Vec<_>>();
        if let Some(first) = outputs.first() {
            for space in std::iter::once(&mut state.space).chain(state.workspaces.iter_mut()) {
                let stranded = space
                    .elements()
                    .filter_map(|window| {
                        let geometry = space.element_geometry(window)?;
                        (!outputs.iter().any(|output| output.overlaps(geometry)))
                            .then(|| window.clone())
                    })
                    .collect::<Vec<_>>();
                for window in stranded {
                    space.map_element(window, (first.loc.x + 24, first.loc.y + 24), false);
                }
            }
        }
        let current_names = self.surfaces.values().map(|surface|surface.output.name()).collect::<HashSet<_>>();
        self.saved_restores.retain(|name,_|current_names.contains(name));
        let added = current_names.difference(&previous_names).cloned().collect::<HashSet<_>>();
        if !added.is_empty() {
            self.saved_restores.extend(selected_saved_outputs(&saved_output_settings(&saved_output_path()), &added));
        }
        tracing::info!(device=%self.path.display(),outputs=self.surfaces.len(),"Native display configuration ready");
        Ok(())
    }
    fn restore_saved_outputs(&mut self, state: &mut OrbitCompositor) {
        if !self.active || self.powered_off { return; }
        let current=self.surfaces.values().map(|surface|(surface.output.name(),surface.pending)).collect::<HashMap<_,_>>();
        let transaction=state.native_system.pending_output.as_ref().and_then(|(_,settings)|settings["name"].as_str());
        let names=saved_restore_names(&mut self.saved_restores,&current,transaction);
        for name in names {
            let Some(surface) = self.surfaces.values().find(|surface|surface.output.name()==name) else {
                self.saved_restores.remove(&name);
                continue;
            };
            // Configuring one output may queue frames on the others. Retry only
            // on their normal frame-completion/redraw events, without a timer.
            if surface.pending { continue; }
            let settings=self.saved_restores.remove(&name).unwrap();
            if let Err(error)=self.system_control(state,&serde_json::json!({"command":"output_configure","settings":settings})) {
                tracing::warn!(%name,%error,"Saved native output configuration skipped");
            }
        }
    }
    fn render(&mut self, state: &mut OrbitCompositor) -> Result<(), Box<dyn Error>> {
        state.redraw_pending = false;
        if !self.active || self.powered_off {
            return Ok(());
        }
        state.advance_window_motions();
                let progress = state.animation_progress();
        let transition = state.transition;
        for surface in self.surfaces.values_mut().filter(|s| s.dirty && !s.pending) {
            let output = &surface.output;
            let scale = output.current_scale().fractional_scale();
            let origin = state
                .space
                .output_geometry(output)
                .map(|g| g.loc)
                .unwrap_or_default();
            let (mut buffer, age) = surface.scanout.next_buffer()?;
            let mut framebuffer = self.renderer.bind(&mut buffer)?;
            let renderer = &mut self.renderer;
            let mut elements: Vec<DrmRenderElement<GlesRenderer>> = Vec::new();
            let locked = state.protocols.is_locked();
            if locked {
                let locked_elements: Vec<WaylandSurfaceRenderElement<GlesRenderer>> =
                    state.protocols.lock_render_elements(output, renderer);
                elements.extend(locked_elements.into_iter().map(Into::into));
            } else {
                let pointer = state.seat.get_pointer().unwrap().current_location();
                if state
                    .space
                    .output_geometry(output)
                    .map(|g| g.to_f64().contains(pointer))
                    .unwrap_or(false)
                {
                    use smithay::input::pointer::{CursorImageStatus, CursorImageSurfaceData};
                    match &state.cursor_status {
                        CursorImageStatus::Hidden => {}
                        CursorImageStatus::Surface(cursor) => {
                            let hotspot =
                                smithay::wayland::compositor::with_states(cursor, |states| {
                                    states
                                        .data_map
                                        .get::<CursorImageSurfaceData>()
                                        .and_then(|data| data.lock().ok().map(|data| data.hotspot))
                                        .unwrap_or_default()
                                });
                            let position = (pointer - origin.to_f64() - hotspot.to_f64())
                                .to_physical_precise_round(scale);
                            let rendered:Vec<WaylandSurfaceRenderElement<GlesRenderer>>=smithay::backend::renderer::element::surface::render_elements_from_surface_tree(renderer,cursor,position,scale,1.0,Kind::Cursor);
                            elements.extend(rendered.into_iter().map(Into::into));
                        }
                        CursorImageStatus::Named(_) => {
                            let cursor=if state.cursor_light {&self.cursor_light}else{&self.cursor};
                            elements.push(
                                MemoryRenderBufferRenderElement::from_buffer(
                                    renderer,
                                    (pointer - origin.to_f64() - cursor.1.to_f64()).to_physical(scale),
                                    &cursor.0,
                                    None,
                                    None,
                                    None,
                                    Kind::Cursor,
                                )?
                                .into(),
                            );
                        }
                    }
                }
                let map = layer_map_for_output(output);
                for layer in map
                    .layers()
                    .rev()
                    .filter(|l| matches!(l.layer(), Layer::Overlay | Layer::Top))
                {
                    if let Some(g) = map.layer_geometry(layer) {
                        let rendered: Vec<WaylandSurfaceRenderElement<GlesRenderer>> = layer
                            .render_elements(
                                renderer,
                                g.loc.to_physical_precise_round(scale),
                                scale.into(),
                                1.0,
                            );
                        elements.extend(rendered.into_iter().map(Into::into));
                    }
                }
                let (outgoing, incoming) = transition
                    .map(|t| {
                        crate::motion::offsets(
                            progress,
                            t.direction,
                            output.current_mode().unwrap().size.h as f64,
                        )
                    })
                    .unwrap_or((0., 0.));
                for (window,loc) in state.minimizing_windows() {
                    let pos=(loc-window.geometry().loc-origin).to_physical_precise_round(scale);
                    elements.extend(crate::window_motion::elements(renderer,&window,pos,scale,state.window_visual(&window),loc).into_iter().map(Into::into));
                }
                for window in state.space.elements().rev() {
                    if let Some(loc) = state.space.element_location(window) {
                        let mut pos =
                            (loc - window.geometry().loc - origin).to_physical_precise_round(scale);
                        pos.y += incoming.round() as i32;
                        elements.extend(crate::window_motion::elements(renderer,window,pos,scale,state.window_visual(window),loc).into_iter().map(Into::into));
                    }
                }
                if let Some(t) = transition {
                    let space = &state.workspaces[t.from];
                    for window in space.elements().rev() {
                        if let Some(loc) = space.element_location(window) {
                            let mut pos = (loc - window.geometry().loc - origin)
                                .to_physical_precise_round(scale);
                            pos.y += outgoing.round() as i32;
                            elements.extend(crate::window_motion::elements(renderer,window,pos,scale,state.window_visual(window),loc).into_iter().map(Into::into));
                        }
                    }
                }
                for layer in map
                    .layers()
                    .rev()
                    .filter(|l| matches!(l.layer(), Layer::Background | Layer::Bottom))
                {
                    if let Some(g) = map.layer_geometry(layer) {
                        let rendered: Vec<WaylandSurfaceRenderElement<GlesRenderer>> = layer
                            .render_elements(
                                renderer,
                                g.loc.to_physical_precise_round(scale),
                                scale.into(),
                                1.0,
                            );
                        elements.extend(rendered.into_iter().map(Into::into));
                    }
                }
            }
            let result = surface.damage.render_output(
                renderer,
                &mut framebuffer,
                if locked && !state.protocols.lock_ready() {
                    0
                } else {
                    age as usize
                },
                &elements,
                if locked {
                    [0., 0., 0., 1.]
                } else {
                    [0.027, 0.035, 0.047, 1.]
                },
            )?;
            let damage = result.damage.cloned();
            let sync = result.sync;
            state
                .protocols
                .capture_output(output, renderer, &framebuffer);
            drop(framebuffer);
            if let Some(damage) = damage {
                surface.scanout.queue_buffer(Some(sync), Some(damage), ())?;
                surface.pending = true;
                surface.queued_locked = locked;
                state.rendered_frames += 1;
                if transition.is_some() {
                    state.animation_frames += 1;
                }
            }
            surface.dirty = false;
            if !locked {
                if let smithay::input::pointer::CursorImageStatus::Surface(cursor) =
                    &state.cursor_status
                {
                    let pointer = state.seat.get_pointer().unwrap().current_location();
                    if state
                        .space
                        .output_geometry(output)
                        .is_some_and(|geometry| geometry.to_f64().contains(pointer))
                    {
                        smithay::desktop::utils::send_frames_surface_tree(
                            cursor,
                            output,
                            state.start_time.elapsed(),
                            Some(Duration::ZERO),
                            |_, _| Some(output.clone()),
                        );
                    }
                }
                for window in state.space.elements() {
                    window.send_frame(
                        output,
                        state.start_time.elapsed(),
                        Some(Duration::ZERO),
                        |_, _| Some(output.clone()),
                    );
                }
                if let Some(t) = transition {
                    for window in state.workspaces[t.from].elements() {
                        window.send_frame(
                            output,
                            state.start_time.elapsed(),
                            Some(Duration::ZERO),
                            |_, _| Some(output.clone()),
                        );
                    }
                }
                for layer in layer_map_for_output(output).layers() {
                    layer.send_frame(
                        output,
                        state.start_time.elapsed(),
                        Some(Duration::ZERO),
                        |_, _| Some(output.clone()),
                    );
                }
            }
        }
        state.space.refresh();
        for space in &mut state.workspaces {
            space.refresh();
        }
        state.popups.cleanup();
        state.display_handle.flush_clients()?;
        Ok(())
    }
}

impl Backend {
    fn wake(&mut self, state: &mut OrbitCompositor) -> Result<(), String> {
        if !self.powered_off {
            return Ok(());
        }
        self.powered_off = false;
        for surface in self.surfaces.values_mut() {
            surface.scanout.reset_buffers();
            surface.pending = false;
            surface.dirty = true;
            surface.damage = OutputDamageTracker::from_output(&surface.output);
        }
        state.redraw_pending = false;
        state.request_redraw();
        Ok(())
    }
    fn system_control(
        &mut self,
        state: &mut OrbitCompositor,
        value: &serde_json::Value,
    ) -> Result<serde_json::Value, String> {
        use serde_json::json;
        if !self.active {
            return Err("The login seat is inactive".into());
        }
        if value["command"] == "output_power" {
            let on = value["on"]
                .as_bool()
                .ok_or("Expected boolean output power")?;
            if on {
                self.wake(state)?;
                return Ok(json!({"ok":true}));
            }
            if !state.protocols.lock_ready() {
                return Err("Displays can power off only after the lock is visibly acknowledged on every output".into());
            }
            if self.surfaces.values().any(|s| s.pending) {
                return Err("Display pageflip pending; retry power request".into());
            }
            self.powered_off = true;
            for surface in self.surfaces.values() {
                if let Err(error) = surface.scanout.surface().clear() {
                    let _ = self.wake(state);
                    return Err(error.to_string());
                }
            }
            self.powered_off = true;
            return Ok(json!({"ok":true}));
        }
        if self.powered_off {
            return Err("Wake displays before changing configuration".into());
        }
        let settings = &value["settings"];
        let name = settings["name"].as_str().ok_or("Missing display name")?;
        let mode_name = settings["mode"].as_str().ok_or("Missing display mode")?;
        let scale = settings["scale"].as_f64().ok_or("Missing display scale")?;
        if ![0.5, 0.75, 1., 1.25, 1.5, 1.75, 2., 2.5, 3.].contains(&scale) {
            return Err("Unsupported display scale".into());
        }
        let transform = match settings["transform"].as_str().unwrap_or("") {
            "normal" => Transform::Normal,
            "90" => Transform::_90,
            "180" => Transform::_180,
            "270" => Transform::_270,
            "flipped" => Transform::Flipped,
            "flipped-90" => Transform::Flipped90,
            "flipped-180" => Transform::Flipped180,
            "flipped-270" => Transform::Flipped270,
            _ => return Err("Unsupported display transform".into()),
        };
        let x = settings["x"]
            .as_i64()
            .filter(|v| (-32768..=32768).contains(v))
            .ok_or("Invalid display position")? as i32;
        let y = settings["y"]
            .as_i64()
            .filter(|v| (-32768..=32768).contains(v))
            .ok_or("Invalid display position")? as i32;
        let crtc = *self
            .surfaces
            .iter()
            .find(|(_, s)| s.output.name() == name)
            .map(|(c, _)| c)
            .ok_or("Display disconnected")?;
        let surface = self.surfaces.get_mut(&crtc).unwrap();
        if surface.pending {
            return Err("Display pageflip pending; retry configuration".into());
        }
        let connector = self
            .drm
            .get_connector(surface.connector, true)
            .map_err(|e| e.to_string())?;
        let mode = connector
            .modes()
            .iter()
            .find(|mode| {
                let (w, h) = mode.size();
                mode_name
                    == format!(
                        "{w}x{h}@{:.3}Hz",
                        Mode::from(**mode).refresh as f64 / 1000.0
                    )
                    || mode_name == format!("{w}x{h}")
            })
            .copied()
            .ok_or("Unsupported display mode")?;
        let old_mode = surface.scanout.pending_mode();
        let output = surface.output.clone();
        let old_scale = output.current_scale();
        let old_transform = output.current_transform();
        let old_geometry = state.space.output_geometry(&output);
        let old_origin = old_geometry.map(|g| g.loc).unwrap_or_default();
        // Smithay tests mode compatibility before staging; queue_buffer then performs
        // the atomic modeset. Restore the exact original state if rendering rejects it.
        surface.scanout.use_mode(mode).map_err(|e| e.to_string())?;
        output.change_current_state(
            Some(Mode::from(mode)),
            Some(transform),
            Some(smithay::output::Scale::Fractional(scale)),
            Some((x, y).into()),
        );
        state.space.map_output(&output, (x, y));
        for space in &mut state.workspaces {
            space.map_output(&output, (x, y));
        }
        state.protocols.output_changed(&output);
        layer_map_for_output(&output).arrange();
        state.reconfigure_output_windows(&output);
        surface.scanout.reset_buffers();
        surface.damage = OutputDamageTracker::from_output(&output);
        surface.dirty = true;
        if let Err(error) = if self.initializing {
            Ok(())
        } else {
            self.render(state)
        } {
            let surface = self.surfaces.get_mut(&crtc).unwrap();
            let _ = surface.scanout.use_mode(old_mode);
            surface.scanout.reset_buffers();
            surface.pending = false;
            surface.dirty = true;
            output.change_current_state(
                Some(Mode::from(old_mode)),
                Some(old_transform),
                Some(old_scale),
                Some(old_origin),
            );
            state.space.map_output(&output, old_origin);
            for space in &mut state.workspaces {
                space.map_output(&output, old_origin);
            }
            surface.damage = OutputDamageTracker::from_output(&output);
            layer_map_for_output(&output).arrange();
            state.reconfigure_output_windows(&output);
            state.protocols.output_changed(&output);
            state.request_redraw();
            return Err(error.to_string());
        }
        let delta = smithay::utils::Point::<i32, Logical>::from((x, y)) - old_origin;
        if delta != (0, 0).into() {
            for space in std::iter::once(&mut state.space).chain(state.workspaces.iter_mut()) {
                let windows = space
                    .elements()
                    .filter_map(|window| {
                        use smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State;
                        if window.toplevel().is_some_and(|surface|{let state=surface.current_state();state.states.contains(State::Maximized)||state.states.contains(State::Fullscreen)})||window.x11_surface().is_some_and(|surface|surface.is_maximized()||surface.is_fullscreen()){return None;}
                        let loc = space.element_location(window)?;
                        if !old_geometry.is_some_and(|g| g.contains(loc)) {
                            return None;
                        }
                        Some((window.clone(), loc + delta))
                    })
                    .collect::<Vec<_>>();
                for (window, loc) in windows {
                    space.map_element(window, loc, false);
                }
            }
        }
        if delta != (0, 0).into() {
            for geometry in state.normal_geometry.values_mut() {
                if old_geometry.is_some_and(|output| output.contains(geometry.loc)) {
                    geometry.loc += delta;
                }
            }
        }
        state.request_redraw();
        Ok(json!({"ok":true}))
    }
}

#[cfg(test)]
mod saved_output_tests {
    use super::*;
    use serde_json::json;
    use std::os::unix::fs::{symlink, PermissionsExt};
    fn fixture() -> PathBuf {
        static SERIAL:std::sync::atomic::AtomicUsize=std::sync::atomic::AtomicUsize::new(0);
        let root=std::env::temp_dir().join(format!("abstract-output-settings-{}-{}",std::process::id(),SERIAL.fetch_add(1,std::sync::atomic::Ordering::Relaxed)));
        std::fs::create_dir(&root).unwrap();root
    }
    fn settings(name:&str) -> serde_json::Value {json!({"name":name,"mode":"1920x1080@60.000Hz","scale":1.25,"transform":"90","x":1920,"y":0})}
    #[test]
    fn reconnect_plan_selects_only_new_names_and_preserves_confirmed_values() {
        let saved=HashMap::from([("HDMI-A-1".to_owned(),settings("HDMI-A-1")),("DP-1".to_owned(),settings("DP-1"))]);
        let added=HashSet::from(["DP-1".to_owned(),"DP-2".to_owned()]);
        let selected=selected_saved_outputs(&saved,&added);
        assert_eq!(selected.len(),1);assert_eq!(selected["DP-1"],saved["DP-1"]);
        assert!(selected_saved_outputs(&saved,&HashSet::new()).is_empty());
    }
    #[test]
    fn restore_queue_preserves_inflight_frames_and_drops_user_transaction_or_disconnected_targets() {
        let mut queued=["DP-1","DP-2","DP-3","DP-4"].into_iter().map(|name|(name.to_owned(),settings(name))).collect::<HashMap<_,_>>();
        let mut current=HashMap::from([("DP-1".to_owned(),true),("DP-2".to_owned(),false),("DP-3".to_owned(),false)]);
        assert_eq!(saved_restore_names(&mut queued,&current,Some("DP-3")),vec!["DP-2"]);
        assert!(queued.contains_key("DP-1"));assert!(!queued.contains_key("DP-3"));assert!(!queued.contains_key("DP-4"));
        queued.remove("DP-2");current.insert("DP-1".to_owned(),false);
        assert_eq!(saved_restore_names(&mut queued,&current,None),vec!["DP-1"]);
    }
    #[test]
    fn saved_output_read_picks_up_later_confirmation_and_rejects_mismatched_name() {
        let root=fixture();let path=root.join("outputs-native.json");
        std::fs::write(&path,json!({"HDMI-A-1":settings("HDMI-A-1"),"DP-1":settings("DP-2")}).to_string()).unwrap();
        std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
        let first=saved_output_settings(&path);assert_eq!(first.len(),1);
        let mut updated=settings("HDMI-A-1");updated["scale"]=json!(2.);
        std::fs::write(&path,json!({"HDMI-A-1":updated}).to_string()).unwrap();
        assert_eq!(saved_output_settings(&path)["HDMI-A-1"]["scale"],2.);
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn saved_output_read_rejects_symlink_writable_malformed_and_oversized_files() {
        let root=fixture();let path=root.join("outputs-native.json");let link=root.join("linked.json");
        std::fs::write(&path,json!({"DP-1":settings("DP-1")}).to_string()).unwrap();symlink(&path,&link).unwrap();
        assert!(saved_output_settings(&link).is_empty());
        std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o666)).unwrap();assert!(saved_output_settings(&path).is_empty());
        std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
        std::fs::write(&path,"x".repeat(65537)).unwrap();assert!(saved_output_settings(&path).is_empty());
        for text in ["[]","null","{bad"] {std::fs::write(&path,text).unwrap();assert!(saved_output_settings(&path).is_empty());}
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn saved_output_read_rejects_more_than_32_rows() {
        let root=fixture();let path=root.join("outputs-native.json");
        let rows=(0..33).map(|index|{let name=format!("DP-{index}");(name.clone(),settings(&name))}).collect::<serde_json::Map<_,_>>();
        std::fs::write(&path,serde_json::Value::Object(rows).to_string()).unwrap();
        std::fs::set_permissions(&path,std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(saved_output_settings(&path).is_empty());
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[cfg(test)]
mod input_bootstrap_tests {
    use smithay::{backend::libinput::LibinputInputBackend,reexports::{calloop::{Dispatcher,EventLoop,EventSource},input::{Libinput,LibinputInterface}}};
    use std::{os::fd::OwnedFd,path::Path,time::{Duration,Instant}};
    struct NoHardware;
    impl LibinputInterface for NoHardware {
        fn open_restricted(&mut self,_path:&Path,_flags:i32)->Result<OwnedFd,i32>{panic!("This fixture must never open an input device")}
        fn close_restricted(&mut self,_fd:OwnedFd){}
    }
    #[test]
    fn initial_libinput_dispatch_is_one_shot_quiet_and_rearmed_after_reregistration() {
        // No seat assignment and no /dev/input access: an empty real libinput
        // event source still exercises calloop's bootstrap and blocking behavior.
        let context=Libinput::new_with_udev(NoHardware);
        let source=LibinputInputBackend::new(context);
        let dispatcher=Dispatcher::new(source,|_,_,events:&mut usize|*events+=1);
        assert!(dispatcher.as_source_mut().before_sleep().unwrap().is_none());
        let mut event_loop=EventLoop::<usize>::try_new().unwrap();
        let token=event_loop.handle().register_dispatcher(dispatcher.clone()).unwrap();
        let mut events=0;
        event_loop.dispatch(Duration::ZERO,&mut events).unwrap();
        assert!(dispatcher.as_source_mut().before_sleep().unwrap().is_none());
        let started=Instant::now();event_loop.dispatch(Duration::from_millis(30),&mut events).unwrap();
        assert!(started.elapsed()>=Duration::from_millis(20),"Bootstrap must not spin an idle loop");
        event_loop.handle().update(&token).unwrap();
        assert!(dispatcher.as_source_mut().before_sleep().unwrap().is_some());
        assert!(dispatcher.as_source_mut().before_sleep().unwrap().is_none());
        assert_eq!(events,0,"No synthetic device or key event may be invented");
    }
}
