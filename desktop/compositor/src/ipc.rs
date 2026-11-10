//! User-private bounded JSON IPC for the experimental nested backend.
use crate::{CalloopData, OrbitCompositor};
use serde_json::{json, Value};
use smithay::reexports::calloop::{channel, EventLoop};
use smithay::reexports::wayland_server::Resource;
use smithay::{
    desktop::{layer_map_for_output, Window},
    reexports::wayland_protocols::xdg::shell::server::xdg_toplevel,
    utils::{Logical, Point, Rectangle, SERIAL_COUNTER},
    wayland::{
        compositor::with_states,
        seat::WaylandFocus,
        shell::xdg::{XdgShellHandler, XdgToplevelSurfaceData},
    },
};
use std::collections::HashMap;
#[derive(Default)]
pub struct NativeIpc {
    subscribers: Vec<(u64, std::sync::mpsc::SyncSender<Value>)>,
    next_subscription: u64,
    last: Option<Value>,
    pub minimized: HashMap<u64, (usize, Point<i32, Logical>)>,
    pub shortcuts: Vec<NativeShortcut>,
    show_desktop: HashMap<usize, Vec<u64>>,
    suspend_publish: bool,
    fullscreen_restore: HashMap<u64, Rectangle<i32, Logical>>,
}

#[derive(Clone)]
pub struct NativeShortcut {
    pub action: String,
    pub keysym: u32,
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
    pub logo: bool,
}
impl NativeShortcut {
    pub fn matches(&self, modifiers: &smithay::input::keyboard::ModifiersState, sym: u32) -> bool {
        let normalize = |value: u32| {
            if (65..=90).contains(&value) {
                value + 32
            } else {
                value
            }
        };
        self.ctrl == modifiers.ctrl
            && self.alt == modifiers.alt
            && self.shift == modifiers.shift
            && self.logo == modifiers.logo
            && normalize(self.keysym) == normalize(sym)
    }
}
fn parse_shortcuts(value: &Value) -> Result<Vec<NativeShortcut>, String> {
    let Some(bindings) = value.as_object().filter(|v| v.len() <= 32) else {
        return Err("invalid shortcut map".into());
    };
    let mut shortcuts = vec![];
    let mut used = std::collections::HashSet::new();
    for (action, chord) in bindings {
        if !matches!(
            action.as_str(),
            "launcher"
                | "quick"
                | "screenshot"
                | "terminal"
                | "volume-up"
                | "volume-down"
                | "volume-mute"
                | "microphone-mute"
                | "media-play-pause"
                | "media-next"
                | "media-previous"
                | "brightness-up"
                | "brightness-down"
                | "snap-left"
                | "snap-right"
                | "maximize"
                | "restore"
                | "next-layout"
        ) {
            return Err("unsupported shortcut action".into());
        }
        let Some(chord) = chord.as_str().filter(|s| s.len() <= 64) else {
            return Err("invalid shortcut chord".into());
        };
        if chord.is_empty() {
            continue;
        }
        if !used.insert(chord) {
            return Err("duplicate shortcut".into());
        }
        let parts: Vec<_> = chord.split('+').collect();
        let key = parts.last().unwrap();
        let modifiers = &parts[..parts.len() - 1];
        if modifiers.len() > 4
            || modifiers
                .iter()
                .any(|v| !matches!(*v, "Ctrl" | "Mod1" | "Shift" | "Mod4"))
            || modifiers
                .iter()
                .collect::<std::collections::HashSet<_>>()
                .len()
                != modifiers.len()
        {
            return Err("invalid shortcut modifiers".into());
        }
        if !(key.len() == 1 && key.as_bytes()[0].is_ascii_alphanumeric()
            || matches!(
                *key,
                "Left"
                    | "Right"
                    | "Up"
                    | "Down"
                    | "Home"
                    | "End"
                    | "Page_Up"
                    | "Page_Down"
                    | "space"
                    | "Return"
                    | "Tab"
                    | "Escape"
                    | "Print"
            )
            || key
                .strip_prefix('F')
                .and_then(|s| s.parse::<u8>().ok())
                .is_some_and(|n| (1..=35).contains(&n)))
        {
            return Err("invalid shortcut key".into());
        }
        if modifiers.is_empty() && *key != "Print" {
            return Err("shortcut needs modifier".into());
        }
        let keysym = smithay::input::keyboard::xkb::keysym_from_name(
            key,
            smithay::input::keyboard::xkb::KEYSYM_NO_FLAGS,
        )
        .raw();
        if keysym == 0 {
            return Err("unknown shortcut keysym".into());
        }
        shortcuts.push(NativeShortcut {
            action: action.clone(),
            keysym,
            ctrl: modifiers.contains(&"Ctrl"),
            alt: modifiers.contains(&"Mod1"),
            shift: modifiers.contains(&"Shift"),
            logo: modifiers.contains(&"Mod4"),
        });
    }
    Ok(shortcuts)
}

use std::{
    io::{BufRead, BufReader, Read, Write},
    os::unix::{fs::PermissionsExt, net::UnixListener},
    time::Duration,
};
struct Request {
    value: Value,
    reply: std::sync::mpsc::SyncSender<Value>,
    subscription: bool,
}
pub fn install(
    event_loop: &mut EventLoop<'static, CalloopData>,
    data: &mut CalloopData,
) -> Result<(), Box<dyn std::error::Error>> {
    let runtime = std::env::var_os("XDG_RUNTIME_DIR").ok_or("XDG_RUNTIME_DIR is required")?;
    let path =
        std::path::PathBuf::from(runtime).join(format!("orbit-native-{}.sock", std::process::id()));
    let listener = UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    data.state.control_path = path;
    data.state.native_system.loop_handle = Some(event_loop.handle());
    let (sender, receiver) = channel::channel::<Request>();
    event_loop
        .handle()
        .insert_source(receiver, |event, _, data| {
            if let channel::Event::Msg(request) = event {
                if request.subscription {
                    let snapshot = data.state.snapshot();
                    data.state.ipc.subscribers.retain(|(_, subscriber)| {
                        subscriber
                            .try_send(json!({"event":"snapshot","snapshot":snapshot}))
                            .is_ok()
                    });
                    if data.state.ipc.subscribers.len() >= 8 {
                        let _ = request
                            .reply
                            .try_send(json!({"ok":false,"error":"too many subscribers"}));
                        return;
                    }
                    data.state.ipc.next_subscription += 1;
                    let subscription = data.state.ipc.next_subscription;
                    let _ = request.reply.try_send(
                        json!({"event":"snapshot","subscription":subscription,"snapshot":snapshot}),
                    );
                    data.state
                        .ipc
                        .subscribers
                        .push((subscription, request.reply));
                    return;
                }
                let result = data.state.control(request.value);
                let _ = data.display_handle.flush_clients();
                let _ = request.reply.try_send(result);
            }
        })?;
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut stream) = stream else { break };
            let _ = stream.set_read_timeout(Some(Duration::from_secs(1)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
            let mut text = String::new();
            let mut reader = BufReader::new(&stream);
            if reader.by_ref().take(4096).read_line(&mut text).is_err() {
                continue;
            }
            let Ok(value) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            let subscription = value["command"] == "subscribe";
            let (tx, rx) = std::sync::mpsc::sync_channel(if subscription { 4 } else { 1 });
            if sender
                .send(Request {
                    value,
                    reply: tx,
                    subscription,
                })
                .is_err()
            {
                break;
            }
            if subscription {
                std::thread::spawn(move || {
                    for reply in rx {
                        if writeln!(stream, "{reply}").is_err() {
                            break;
                        }
                    }
                });
            } else if let Ok(reply) = rx.recv_timeout(Duration::from_secs(2)) {
                let _ = writeln!(stream, "{reply}");
            }
        }
    });
    Ok(())
}
impl OrbitCompositor {
    fn control(&mut self, value: Value) -> Value {
        if self.protocols.is_locked()
            && !matches!(
                value["command"].as_str(),
                Some(
                    "status"
                        | "snapshot"
                        | "windows"
                        | "unsubscribe"
                        | "input_get"
                        | "output_power"
                        | "output_resume"
                        | "output_rollback"
                )
            )
        {
            return json!({"ok":false,"error":"session is locked"});
        }
        match value["command"].as_str().unwrap_or("") {
            "status" => {
                json!({"backend":"orbit-native","protocol_version":1,"capabilities":{"native_workspace_slide":true,"native_window_motion":true,"trusted_virtual_keyboard":true,"touch":self.seat.get_touch().is_some(),"primary_selection":true,"clipboard_text_retention":true,"client_dmabuf":self.dmabuf.global.is_some(),"clipboard_png":true,"native_png_clipboard":true,"themed_cursor":true,"layer_shell":true,"xdg_shell":true,"maximize_restore":true,"xwayland":self.xwayland.xwm.is_some(),"secure_lock":std::env::args().any(|arg|arg=="--drm"),"idle_notify":true,"idle_inhibit":true,"hardware_validated":false,"screen_copy":true,"screencopy_version":2,"legacy_ssd":true,"orbit_shell_adapter":true,"login_session":std::env::args().any(|arg|arg=="--drm")},"control_capabilities":self.native_system_capabilities(),"experimental":true,"xdisplay":self.xwayland.display,"xwayland_error":self.xwayland.error,"locked":self.protocols.is_locked(),"pointer":self.seat.get_pointer().map(|p|{let pos=p.current_location();json!({"x":pos.x,"y":pos.y,"header":self.header_at(pos).map(|(id,_,_)|id.to_string()),"grabbed":p.is_grabbed()})}),"workspace":self.current_workspace+1,"workspaces":4,"animating":self.has_animations(),"window_animations":self.window_motions.active.len(),"window_motion_enabled":self.window_motion_enabled,"rendered_frames":self.rendered_frames,"animation_frames":self.animation_frames,"wayland_display":self.socket_name.to_string_lossy(),"capture_based":false,"progress":self.transition.map(|t|(t.started.elapsed().as_secs_f64()/if self.economy {0.18}else{0.24}).min(1.0)).unwrap_or(1.0),"direction":self.transition.map(|t|t.direction as i32),"economy":self.economy,"reduced_motion":self.reduced_motion})
            }
            "clipboard_png" => {
                match crate::clipboard::read_png(value["path"].as_str().unwrap_or("")){
                    Ok(bytes)=>{
                        self.retain_selection(smithay::wayland::selection::SelectionTarget::Clipboard,None);
                        smithay::wayland::selection::data_device::set_data_device_selection(&self.display_handle,&self.seat,vec!["image/png".into()],crate::clipboard::SelectionData::Png(bytes));
                        if let Some(xwm)=&mut self.xwayland.xwm {let _=xwm.new_selection(smithay::wayland::selection::SelectionTarget::Clipboard,Some(vec!["image/png".into()]));}
                        serde_json::json!({"ok":true})
                    },Err(error)=>serde_json::json!({"ok":false,"error":error})
                }
            }
            "snapshot" => self.snapshot(),
            "theme" => {
                let mode = value["mode"].as_str().unwrap_or("");
                let accent = value["accent"].as_str().unwrap_or("");
                let outline = match crate::decoration::outline_setting(value.get("outline")) {
                    Ok(enabled)=>enabled,Err(error)=>return json!({"ok":false,"error":error}),
                };
                let result = if value.get("palette").is_some() {
                    crate::decoration::set_theme_palette(mode,accent,value.get("palette"))
                } else {crate::decoration::set_theme(mode,accent)};
                match result {
                    Ok(()) => {
                        crate::decoration::set_outline(outline);
                        self.cursor_light=mode=="light";
                        if let Some(xwm)=&mut self.xwayland.xwm {
                            let image=crate::cursor_theme::load(self.cursor_light);
                            let _=xwm.set_cursor(&image.pixels,(image.width as u16,image.height as u16).into(),(image.xhot as u16,image.yhot as u16).into());
                        }
                        self.request_redraw();
                        let palette_applied = value.get("palette").and_then(|p|p.as_object()).is_some_and(|p|!p.is_empty());
                        json!({"ok":true,"palette_applied":palette_applied,"outline_enabled":outline})
                    }
                    Err(error) => json!({"ok":false,"error":error}),
                }
            }
            "motion" => {
                let settings = &value["settings"];
                if !settings.is_object()
                    || ["economy", "reduced_motion", "enabled"]
                        .iter()
                        .any(|key| !settings[key].is_boolean())
                {
                    return json!({"ok":false,"error":"motion settings need economy, reduced_motion and enabled booleans"});
                }
                self.economy = settings["economy"].as_bool().unwrap();
                self.window_motion_enabled = !settings["reduced_motion"].as_bool().unwrap();
                if !self.window_motion_enabled {self.clear_window_motions();}
                self.reduced_motion = settings["reduced_motion"].as_bool().unwrap()
                    || !settings["enabled"].as_bool().unwrap();
                if self.reduced_motion {
                    self.transition = None;
                    if let Some((workspace, direction)) = self.pending_workspace.take() {
                        self.switch_workspace(workspace, direction);
                    }
                }
                self.request_redraw();
                json!({"ok":true})
            }
            "unsubscribe" => {
                let id = window_id(&value);
                self.ipc.subscribers.retain(|(other, _)| *other != id);
                json!({"ok":true})
            }
            "show_desktop" => {
                self.ipc.suspend_publish = true;
                if let Some(ids) = self.ipc.show_desktop.remove(&self.current_workspace) {
                    for id in ids {
                        self.restore_native(id);
                    }
                } else {
                    let ids: Vec<_> = self
                        .windows
                        .iter()
                        .filter_map(|(id, w)| {
                            self.window_location(*id, w)
                                .filter(|(workspace, _, minimized)| {
                                    *workspace == self.current_workspace && !*minimized
                                })
                                .map(|_| *id)
                        })
                        .collect();
                    for id in &ids {
                        self.minimize_window(*id);
                    }
                    self.ipc.show_desktop.insert(self.current_workspace, ids);
                }
                self.ipc.suspend_publish = false;
                self.request_redraw();
                json!({"ok":true})
            }
            "shortcuts" => match parse_shortcuts(&value["bindings"]) {
                Ok(bindings) => {
                    self.ipc.shortcuts = bindings;
                    json!({"ok":true})
                }
                Err(error) => json!({"ok":false,"error":error}),
            },
            "input_get" | "input_configure" | "output_configure" | "output_power" | "output_resume" | "output_checkpoint" | "output_commit" | "output_rollback" => {
                self.native_system_control(&value)
            }
            "focus" | "minimize" | "restore" | "snap" | "resize" | "fullscreen" | "constrain" => {
                self.window_action(&value)
            }
            "workspace" => {
                let Some(index) = value["workspace"].as_u64().filter(|v| (1..=4).contains(v))
                else {
                    return json!({"ok":false,"error":"workspace must be 1–4"});
                };
                let direction = value["direction"].as_i64().unwrap_or(
                    if index as usize > self.current_workspace + 1 {
                        1
                    } else {
                        -1
                    },
                );
                self.switch_workspace(index as usize - 1, direction as i32);
                json!({"ok":true})
            }
            "step" => {
                self.step_workspace(if value["direction"].as_i64().unwrap_or(1) < 0 {
                    -1
                } else {
                    1
                });
                json!({"ok":true})
            }
            "windows" => json!({"windows":self.snapshot()["windows"]}),
            "move" => {
                json!({"ok":self.move_window_to_workspace(window_id(&value),value["workspace"].as_u64().unwrap_or(0).wrapping_sub(1) as usize)})
            }
            "maximize" => {
                self.restore_native(window_id(&value));
                let x11 = self
                    .windows
                    .iter()
                    .find(|(id, _)| *id == window_id(&value))
                    .and_then(|(_, w)| w.x11_surface().cloned());
                if let Some(surface) = x11 {
                    self.maximize_x11(
                        &surface,
                        !value["restore"].as_bool().unwrap_or(false),
                        false,
                    );
                    return json!({"ok":true});
                }
                let surface = self
                    .windows
                    .iter()
                    .find(|(id, _)| *id == window_id(&value))
                    .and_then(|(_, w)| w.toplevel().cloned());
                if let Some(surface) = surface {
                    if value["restore"].as_bool().unwrap_or(false) {
                        self.unmaximize_request(surface);
                    } else {
                        self.maximize_request(surface);
                    }
                    json!({"ok":true})
                } else {
                    json!({"ok":false})
                }
            }
            "close" => {
                if let Some((_, window)) =
                    self.windows.iter().find(|(id, _)| *id == window_id(&value))
                {
                    if let Some(surface) = window.toplevel() {
                        surface.send_close();
                        return json!({"ok":true});
                    }
                    if let Some(surface) = window.x11_surface() {
                        return json!({"ok":surface.close().is_ok()});
                    }
                }
                json!({"ok":false})
            }
            "quit" => {
                self.loop_signal.stop();
                json!({"ok":true})
            }
            _ => json!({"ok":false,"error":"Unknown command"}),
        }
    }
}
fn window_id(value: &Value) -> u64 {
    value["id"]
        .as_u64()
        .or_else(|| value["id"].as_str().and_then(|s| s.parse().ok()))
        .unwrap_or(0)
}
fn rect_value(rect: Rectangle<i32, Logical>) -> Value {
    json!({"x":rect.loc.x,"y":rect.loc.y,"width":rect.size.w,"height":rect.size.h})
}
impl OrbitCompositor {
    pub fn publish_action(&mut self, action: &str) {
        if self.protocols.is_locked() {
            return;
        }
        self.ipc.subscribers.retain(|(_, subscriber)| {
            subscriber
                .try_send(json!({"event":"action","action":action}))
                .is_ok()
        });
    }
    pub fn publish_snapshot(&mut self) {
        if self.ipc.suspend_publish || self.ipc.subscribers.is_empty() {
            return;
        }
        self.ipc
            .minimized
            .retain(|id, _| self.windows.iter().any(|(other, _)| other == id));
        let snapshot = self.snapshot();
        if self.ipc.last.as_ref() == Some(&snapshot) {
            return;
        }
        self.ipc.last = Some(snapshot.clone());
        self.ipc.subscribers.retain(|(_, subscriber)| {
            subscriber
                .try_send(json!({"event":"snapshot","snapshot":snapshot}))
                .is_ok()
        });
    }
    fn window_location(
        &self,
        id: u64,
        window: &Window,
    ) -> Option<(usize, Point<i32, Logical>, bool)> {
        self.ipc
            .minimized
            .get(&id)
            .or_else(|| self.xwayland.minimized.get(&id))
            .map(|(ws, loc)| (*ws, *loc, true))
            .or_else(|| {
                self.space
                    .element_location(window)
                    .map(|loc| (self.current_workspace, loc, false))
            })
            .or_else(|| {
                self.workspaces
                    .iter()
                    .enumerate()
                    .find_map(|(index, space)| {
                        space
                            .element_location(window)
                            .map(|loc| (index, loc, false))
                    })
            })
    }
    pub fn snapshot(&self) -> Value {
        let locked = self.protocols.is_locked();
        let outputs:Vec<_>=self.space.outputs().filter_map(|output|{let rect=self.space.output_geometry(output)?;let mut workarea=layer_map_for_output(output).non_exclusive_zone();workarea.loc+=rect.loc;let mode=output.current_mode();Some(json!({"name":output.name(),"active":true,"focused":true,"rect":rect_value(rect),"workarea":rect_value(workarea),"scale":output.current_scale().fractional_scale(),"transform":crate::native_system::transform_name(output.current_transform()),"current_mode":mode.map(|m|json!({"width":m.size.w,"height":m.size.h,"refresh":m.refresh})),"modes":output.modes().into_iter().map(|m|json!({"width":m.size.w,"height":m.size.h,"refresh":m.refresh})).collect::<Vec<_>>() }))}).collect();
        let default_area = outputs
            .first()
            .map(|o| o["workarea"].clone())
            .unwrap_or(json!({"x":0,"y":0,"width":800,"height":600}));
        let focus = self.seat.get_keyboard().and_then(|k| k.current_focus());
        let windows: Vec<_> = if locked {
            vec![]
        } else {
            self.windows.iter().filter_map(|(id,window)|{
            let (workspace,location,minimized)=self.window_location(*id,window)?;
            let mut title=String::new();let mut klass=String::new();let mut pid=0;let mut maximized=false;let mut fullscreen=false;
            if let Some(surface)=window.toplevel(){with_states(surface.wl_surface(),|states|{if let Some(data)=states.data_map.get::<XdgToplevelSurfaceData>(){let data=data.lock().unwrap();title=data.title.clone().unwrap_or_default();klass=data.app_id.clone().unwrap_or_default();}});let states=surface.current_state();maximized=states.states.contains(xdg_toplevel::State::Maximized);fullscreen=states.states.contains(xdg_toplevel::State::Fullscreen);pid=surface.wl_surface().client().and_then(|c|c.get_credentials(&self.display_handle).ok()).map(|c|c.pid).unwrap_or(0);
            }else if let Some(surface)=window.x11_surface(){if surface.is_override_redirect(){return None;}title=surface.title();klass=surface.class();pid=surface.pid().unwrap_or(0) as i32;maximized=surface.is_maximized();fullscreen=surface.is_fullscreen();}
            let active=!minimized&&window.wl_surface().is_some_and(|surface|focus.as_ref()==Some(surface.as_ref()));
            let mut geometry=window.geometry();geometry.loc=location;
            if let Some(surface)=window.x11_surface(){geometry=surface.geometry();}
            let area=outputs.iter().find(|o|{let r=&o["rect"];location.x>=r["x"].as_i64().unwrap_or(0) as i32&&location.x<(r["x"].as_i64().unwrap_or(0)+r["width"].as_i64().unwrap_or(0)) as i32}).map(|o|o["workarea"].clone()).unwrap_or(default_area.clone());
            let frame=if !minimized&&crate::decoration::needs_header(window){json!({"x":geometry.loc.x,"y":geometry.loc.y-crate::decoration::HEIGHT,"width":geometry.size.w,"height":crate::decoration::HEIGHT})}else{json!({})};
            Some(json!({"id":id.to_string(),"workspace":workspace+1,"desktop":workspace,"pid":pid,"klass":klass.chars().take(256).collect::<String>().to_lowercase(),"app_id":klass.chars().take(256).collect::<String>(),"title":title.chars().take(512).collect::<String>(),"active":active,"minimized":minimized,"maximized":maximized,"fullscreen":fullscreen,"workarea":area,"rect":rect_value(geometry),"x":geometry.loc.x,"y":geometry.loc.y,"width":geometry.size.w,"height":geometry.size.h,"frame":frame,"native":true}))
        }).take(256).collect()
        };
        json!({"backend":"orbit-native","windows":windows,"desktops":(0..self.workspaces.len()).map(|index|json!({"id":index,"active":index==self.current_workspace,"name":format!("Space {}",index+1)})).collect::<Vec<_>>(),"outputs":outputs,"locked":locked})
    }
    pub fn minimize_window(&mut self, id: u64) -> bool {
        self.window_action(&json!({"command":"minimize","id":id}))["ok"] == true
    }
    pub fn send_window_activation_configures(&self) {
        for (_, window) in &self.windows {
            if let Some(surface) = window.toplevel() {
                surface.send_pending_configure();
            }
        }
    }
    pub fn refocus_after_unmap(&mut self, window: &Window) {
        let keyboard = self.seat.get_keyboard().unwrap();
        if window
            .wl_surface()
            .is_some_and(|surface| keyboard.current_focus().as_ref() == Some(surface.as_ref()))
        {
            window.set_activated(false);
            let top = self.space.elements().last().cloned();
            if let Some(top) = &top {
                self.space.raise_element(top, true);
            }
            let focus = top.and_then(|w| w.wl_surface().map(|s| s.into_owned()));
            keyboard.set_focus(self, focus, SERIAL_COUNTER.next_serial());
            self.send_window_activation_configures();
            self.request_redraw();
        }
    }
    fn restore_native(&mut self, id: u64) -> bool {
        let Some((_, window)) = self.windows.iter().find(|(other, _)| *other == id).cloned() else {
            return false;
        };
        if let Some(surface) = window.x11_surface() {
            let surface = surface.clone();
            self.restore_x11(&surface);
            return true;
        }
        self.window_motions.active.remove(&id);
        if let Some((workspace, location)) = self.ipc.minimized.remove(&id) {
            let space = if workspace == self.current_workspace {
                &mut self.space
            } else {
                &mut self.workspaces[workspace]
            };
            space.map_element(window, location, false);
            if workspace==self.current_workspace {self.start_window_open(id);}
            self.request_redraw();
        }
        true
    }
    fn set_native_rect(&mut self, id: u64, geometry: Rectangle<i32, Logical>) -> bool {
        self.window_motions.active.remove(&id);
        self.window_motions.pending_open.remove(&id);
        let Some((_, window)) = self.windows.iter().find(|(other, _)| *other == id).cloned() else {
            return false;
        };
        if let Some(surface) = window.x11_surface() {
            let surface = surface.clone();
            let geometry = self.bounded_x11_geometry(&surface, geometry);
            let _ = surface.set_maximized(false);
            let _ = surface.set_fullscreen(false);
            let _ = surface.configure(geometry);
            self.position_x11(&surface, geometry);
        } else if let Some(surface) = window.toplevel() {
            surface.with_pending_state(|state| {
                state.size = Some(geometry.size);
                state.states.unset(xdg_toplevel::State::Maximized);
                state.states.unset(xdg_toplevel::State::Fullscreen);
            });
            surface.send_pending_configure();
            if self.space.element_location(&window).is_some() {
                self.space.map_element(window, geometry.loc, false);
            } else {
                for space in &mut self.workspaces {
                    if space.element_location(&window).is_some() {
                        space.map_element(window.clone(), geometry.loc, false);
                        break;
                    }
                }
            }
        }
        self.request_redraw();
        true
    }
    fn window_action(&mut self, value: &Value) -> Value {
        let id = window_id(value);
        let Some((_, window)) = self.windows.iter().find(|(other, _)| *other == id).cloned() else {
            return json!({"ok":false,"error":"window has closed"});
        };
        let command = value["command"].as_str().unwrap_or("");
        if command == "minimize" {
            if let Some(surface) = window.x11_surface() {
                let surface = surface.clone();
                self.minimize_x11(&surface);
            } else if let Some((workspace, location, _)) = self.window_location(id, &window) {
                if self.ipc.minimized.len() >= 256 && !self.ipc.minimized.contains_key(&id) {
                    return json!({"ok":false,"error":"too many minimized windows"});
                }
                self.start_window_minimize(id);
                self.ipc.minimized.insert(id, (workspace, location));
                self.space.unmap_elem(&window);
                for space in &mut self.workspaces {
                    space.unmap_elem(&window);
                }
                self.request_redraw();
            }
            self.refocus_after_unmap(&window);
            return json!({"ok":true});
        }
        self.restore_native(id);
        if command == "restore" {
            return json!({"ok":true});
        }
        if command == "focus" {
            let Some((workspace, _, _)) = self.window_location(id, &window) else {
                return json!({"ok":false,"error":"window is not mapped"});
            };
            if workspace != self.current_workspace {
                self.transition = None;
                self.pending_workspace = None;
                self.switch_workspace(
                    workspace,
                    if workspace > self.current_workspace {
                        1
                    } else {
                        -1
                    },
                );
            }
            self.space.raise_element(&window, true);
            self.seat.get_keyboard().unwrap().set_focus(
                self,
                window.wl_surface().map(|s| s.into_owned()),
                SERIAL_COUNTER.next_serial(),
            );
            self.send_window_activation_configures();
            self.request_redraw();
            return json!({"ok":true});
        }
        if command == "fullscreen" {
            let enabled = value["enabled"].as_bool().unwrap_or(false);
            let Some((_, location, _)) = self.window_location(id, &window) else {
                return json!({"ok":false,"error":"window is not mapped"});
            };
            let Some(output) = self
                .space
                .outputs()
                .find(|output| {
                    self.space
                        .output_geometry(output)
                        .is_some_and(|area| area.contains(location))
                })
                .or_else(|| self.space.outputs().next())
                .cloned()
            else {
                return json!({"ok":false,"error":"no output"});
            };
            let geometry = if enabled {
                self.ipc
                    .fullscreen_restore
                    .entry(id)
                    .or_insert(Rectangle::new(location, window.geometry().size));
                self.space.output_geometry(&output).unwrap()
            } else {
                self.ipc
                    .fullscreen_restore
                    .remove(&id)
                    .unwrap_or(Rectangle::new(location, window.geometry().size))
            };
            if let Some(surface) = window.x11_surface() {
                let _ = surface.set_fullscreen(enabled);
                let _ = surface.configure(geometry);
                let surface = surface.clone();
                self.position_x11(&surface, geometry);
            } else if let Some(surface) = window.toplevel() {
                surface.with_pending_state(|state| {
                    state.size = Some(geometry.size);
                    if enabled {
                        state.states.set(xdg_toplevel::State::Fullscreen);
                    } else {
                        state.states.unset(xdg_toplevel::State::Fullscreen);
                    }
                });
                surface.send_pending_configure();
                if self.space.element_location(&window).is_some() {
                    self.space.map_element(window.clone(), geometry.loc, false);
                } else {
                    for space in &mut self.workspaces {
                        if space.element_location(&window).is_some() {
                            space.map_element(window.clone(), geometry.loc, false);
                            break;
                        }
                    }
                }
            }
            self.request_redraw();
            return json!({"ok":true});
        }
        let Some((_, location, _)) = self.window_location(id, &window) else {
            return json!({"ok":false,"error":"window is not mapped"});
        };
        let Some(output) = self
            .space
            .outputs()
            .find(|output| {
                self.space
                    .output_geometry(output)
                    .is_some_and(|r| r.contains(location))
            })
            .or_else(|| self.space.outputs().next())
            .cloned()
        else {
            return json!({"ok":false,"error":"no output"});
        };
        let mut area = layer_map_for_output(&output).non_exclusive_zone();
        area.loc += self.space.output_geometry(&output).unwrap().loc;
        area = crate::decoration::client_area(&window, area);
        let mut rect = Rectangle::new(location, window.geometry().size);
        match command {
            "snap" => {
                self.normal_geometry.entry(id).or_insert(rect);
                let side = value["side"].as_str().unwrap_or("");
                if !matches!(side, "left" | "right" | "top" | "bottom") {
                    return json!({"ok":false,"error":"invalid snap side"});
                }
                rect = area;
                if matches!(side, "left" | "right") {
                    rect.size.w /= 2;
                    if side == "right" {
                        rect.loc.x += area.size.w - rect.size.w;
                    }
                } else {
                    rect.size.h /= 2;
                    if side == "bottom" {
                        rect.loc.y += area.size.h - rect.size.h;
                    }
                }
            }
            "resize" => {
                let r = &value["rect"];
                let fields = ["x", "y", "width", "height"];
                if fields
                    .iter()
                    .any(|key| r[key].as_i64().is_none_or(|n| n.abs() > 2_000_000))
                    || r["width"].as_i64().unwrap_or(0) <= 0
                    || r["height"].as_i64().unwrap_or(0) <= 0
                {
                    return json!({"ok":false,"error":"invalid rectangle"});
                }
                rect = Rectangle::new(
                    (
                        r["x"].as_i64().unwrap() as i32,
                        r["y"].as_i64().unwrap() as i32,
                    )
                        .into(),
                    (
                        r["width"].as_i64().unwrap() as i32,
                        r["height"].as_i64().unwrap() as i32,
                    )
                        .into(),
                );
            }
            "constrain" => {}
            _ => return json!({"ok":false,"error":"unsupported action"}),
        }
        rect.size.w = rect.size.w.max(1).min(area.size.w.max(1));
        rect.size.h = rect.size.h.max(1).min(area.size.h.max(1));
        rect.loc.x = rect
            .loc
            .x
            .clamp(area.loc.x, area.loc.x + (area.size.w - rect.size.w).max(0));
        rect.loc.y = rect
            .loc
            .y
            .clamp(area.loc.y, area.loc.y + (area.size.h - rect.size.h).max(0));
        json!({"ok":self.set_native_rect(id,rect)})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shortcut_configuration_is_finite_and_rejects_invalid_maps() {
        assert!(
            parse_shortcuts(&json!({"launcher":"Ctrl+Mod1+space","screenshot":"Print"})).is_ok()
        );
        for invalid in [
            json!({"exec":"Mod4+x"}),
            json!({"launcher":"x"}),
            json!({"launcher":"Mod4+$(touch /tmp/no)"}),
            json!({"launcher":"Mod4+space","quick":"Mod4+space"}),
            json!({"launcher":false}),
        ] {
            assert!(parse_shortcuts(&invalid).is_err());
        }
    }
    #[test]
    fn configured_shortcut_matches_modifiers_and_caps_without_stealing_others() {
        let bindings = parse_shortcuts(&json!({"quick":"Ctrl+Mod1+s"})).unwrap();
        let mut modifiers = smithay::input::keyboard::ModifiersState::default();
        modifiers.ctrl = true;
        modifiers.alt = true;
        assert!(bindings[0].matches(&modifiers, b'S' as u32));
        assert!(!bindings[0].matches(&modifiers, b'x' as u32));
        modifiers.shift = true;
        assert!(!bindings[0].matches(&modifiers, b's' as u32));
    }
    #[test]
    fn window_identifier_accepts_typed_snapshot_strings_without_coercing_booleans() {
        assert_eq!(window_id(&json!({"id":"42"})), 42);
        assert_eq!(window_id(&json!({"id":42})), 42);
        assert_eq!(window_id(&json!({"id":true})), 0);
        assert_eq!(window_id(&json!({"id":"42; close"})), 0);
    }
}

impl OrbitCompositor {
    /// Reconfigure live maximized/fullscreen clients after an output workarea
    /// changes, without replacing their pre-maximize restore geometry.
    pub fn reconfigure_output_windows(&mut self, output: &smithay::output::Output) {
        let Some(output_rect) = self.space.output_geometry(output) else {
            return;
        };
        let sole_output = self.space.outputs().count() == 1;
        let mut area = layer_map_for_output(output).non_exclusive_zone();
        area.loc += output_rect.loc;
        let windows = self.windows.clone();
        let was_suspended = self.ipc.suspend_publish;
        self.ipc.suspend_publish = true;
        for (id, window) in windows {
            let Some((_, location, minimized)) = self.window_location(id, &window) else {
                continue;
            };
            if minimized || !sole_output && !output_rect.contains(location) {
                continue;
            }
            if let Some(surface) = window.x11_surface() {
                if !surface.is_maximized() && !surface.is_fullscreen() {
                    continue;
                }
                let geometry = if surface.is_fullscreen() {
                    output_rect
                } else {
                    crate::decoration::client_area(&window, area)
                };
                let _ = surface.configure(geometry);
                let surface = surface.clone();
                self.position_x11(&surface, geometry);
            } else if let Some(surface) = window.toplevel() {
                let state = surface.current_state();
                let fullscreen = state.states.contains(xdg_toplevel::State::Fullscreen);
                if !fullscreen && !state.states.contains(xdg_toplevel::State::Maximized) {
                    continue;
                }
                let geometry = if fullscreen { output_rect } else { area };
                surface.with_pending_state(|state| state.size = Some(geometry.size));
                surface.send_pending_configure();
                if self.space.element_location(&window).is_some() {
                    self.space.map_element(window.clone(), geometry.loc, false);
                } else {
                    for space in &mut self.workspaces {
                        if space.element_location(&window).is_some() {
                            space.map_element(window.clone(), geometry.loc, false);
                            break;
                        }
                    }
                }
            }
        }
        self.ipc.suspend_publish = was_suspended;
        self.request_redraw();
    }
}
