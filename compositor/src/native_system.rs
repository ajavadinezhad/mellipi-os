//! Typed native session controls. Hardware operations are installed only by DRM.
use crate::OrbitCompositor;
use serde_json::{json, Value};
use smithay::input::keyboard::xkb;
pub type OutputControl = Box<dyn FnMut(&mut OrbitCompositor, &Value) -> Result<Value, String>>;
pub struct NativeSystem {
    pub output: Option<OutputControl>,
    pub values: Value,
    pub configured: Vec<String>,
    pub overrides: Value,
    pub pending_output: Option<(String, Value)>,
    completed_rollback: Option<String>,
    pub loop_handle: Option<smithay::reexports::calloop::LoopHandle<'static, crate::CalloopData>>,
    #[cfg(feature = "drm")]
    pub devices: Vec<smithay::reexports::input::Device>,
}
impl Default for NativeSystem {
    fn default() -> Self {
        Self {
            output: None,
            values: json!({"layout":"us","repeatRate":25,"repeatDelay":600,"pointerSpeed":0.,"naturalScroll":false,"tapToClick":false}),
            configured: vec![],
            overrides: json!({}),
            pending_output: None,
            completed_rollback: None,
            loop_handle: None,
            #[cfg(feature = "drm")]
            devices: vec![],
        }
    }
}
fn keys(value: &Value) -> Result<Vec<String>, String> {
    let keys = value.as_array().ok_or("Expected input field list")?;
    if keys.len() > 6 {
        return Err("Too many input fields".into());
    }
    keys.iter()
        .map(|key| match key.as_str() {
            Some(
                k @ ("layout" | "repeatRate" | "repeatDelay" | "pointerSpeed" | "naturalScroll"
                | "tapToClick"),
            ) => Ok(k.to_string()),
            _ => Err("Unsupported input field".into()),
        })
        .collect()
}
fn validate_layout_codes(layout: &str) -> Result<(), String> {
    if layout.is_empty() || layout.len()>131 {return Err("Choose up to four distinct installed keyboard layouts".into());}
    let codes=layout.split(',').collect::<Vec<_>>();
    if codes.is_empty() || codes.len()>4 || codes.iter().any(|code|code.is_empty() || code.len()>32 || !code.bytes().all(|c|c.is_ascii_alphanumeric() || b"_-".contains(&c)))
        || codes.iter().enumerate().any(|(index,code)|codes[..index].contains(code)) {
        return Err("Choose up to four distinct installed keyboard layouts".into());
    }
    Ok(())
}

fn compile_layout(layout: &str) -> Result<String,String> {
    validate_layout_codes(layout)?;
    let context=xkb::Context::new(xkb::CONTEXT_NO_FLAGS);
    let keymap=xkb::Keymap::new_from_names(&context,"","",layout,"",Some("grp:alt_shift_toggle".into()),xkb::KEYMAP_COMPILE_NO_FLAGS)
        .ok_or_else(||"The installed XKB rules cannot compile this keyboard layout".to_owned())?;
    Ok(keymap.get_as_string(xkb::KEYMAP_FORMAT_TEXT_V1))
}

fn validate(values: &Value) -> Result<(), String> {
    let layout = values["layout"].as_str().ok_or("Missing keyboard layout")?;
    validate_layout_codes(layout)?;
    for (key, low, high) in [("repeatRate", 1, 100), ("repeatDelay", 100, 2000)] {
        let n = values[key].as_i64().ok_or("Invalid keyboard repeat")?;
        if n < low || n > high {
            return Err("Invalid keyboard repeat range".into());
        }
    }
    let speed = values["pointerSpeed"]
        .as_f64()
        .ok_or("Invalid pointer speed")?;
    if !speed.is_finite() || !(-1.0..=1.0).contains(&speed) {
        return Err("Invalid pointer speed range".into());
    }
    for key in ["naturalScroll", "tapToClick"] {
        values[key].as_bool().ok_or("Invalid input toggle")?;
    }
    Ok(())
}
impl OrbitCompositor {
    pub fn native_system_capabilities(&self) -> Value {
        json!({"virtual_keyboard":true,"input":cfg!(feature="drm")&&self.native_system.output.is_some(),"display":self.native_system.output.is_some(),"dpms":self.native_system.output.is_some()})
    }

    pub fn native_system_control(&mut self, value: &Value) -> Value {
        let result: Result<Value, String> = (|| match value["command"].as_str().unwrap_or("") {
            "input_get" => Ok(json!({"inputs":self.native_inputs()})),
            "input_configure" => {
                if self.native_system.output.is_none() {
                    return Err("Input hardware controls require the standalone DRM backend".into());
                }
                let fields = keys(&value["keys"])?;
                validate(&value["values"])?;
                let device = value["device"].as_str().unwrap_or("");
                if device.len() > 128
                    || !device
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_.:+-".contains(&b))
                {
                    return Err("Invalid input device".into());
                }
                self.apply_native_input(&value["values"], &fields, device)?;
                if device.is_empty() {
                    self.native_system.values = value["values"].clone();
                    self.native_system.configured.extend(fields);
                    self.native_system.configured.sort();
                    self.native_system.configured.dedup();
                } else {
                    self.native_system.overrides[device] =
                        json!({"values":value["values"],"configured":fields});
                }
                Ok(json!({"ok":true}))
            }
            "output_checkpoint" => {
                if self.native_system.output.is_none() { return Err("Display hardware controls require DRM".into()); }
                if self.native_system.pending_output.is_some() { return Err("A display confirmation is already pending".into()); }
                let name = value["name"].as_str().ok_or("Missing display name")?;
                let output = self.space.outputs().find(|output| output.name() == name).ok_or("Display disconnected")?;
                let rect = self.space.output_geometry(output).ok_or("Missing output geometry")?;
                let mode = output.current_mode().ok_or("Missing current display mode")?;
                let settings = json!({"name":name,"mode":format!("{}x{}@{:.3}Hz",mode.size.w,mode.size.h,mode.refresh as f64/1000.),"scale":output.current_scale().fractional_scale(),"transform":transform_name(output.current_transform()),"x":rect.loc.x,"y":rect.loc.y});
                use std::io::Read;
                let mut bytes = [0u8; 24];
                std::fs::File::open("/dev/urandom").and_then(|mut file|file.read_exact(&mut bytes)).map_err(|e|e.to_string())?;
                let token = bytes.iter().map(|byte|format!("{byte:02x}")).collect::<String>();
                let handle = self.native_system.loop_handle.clone().ok_or("Missing display transaction event loop")?;
                let timer_token = token.clone();
                let seconds = value["seconds"].as_f64().unwrap_or(15.).clamp(1.,30.);
                use smithay::reexports::calloop::timer::{Timer, TimeoutAction};
                use std::time::Duration;
                handle.insert_source(Timer::from_duration(Duration::from_secs_f64(seconds+4.)), move |_, _, data| {
                    if !data.state.native_system.pending_output.as_ref().is_some_and(|(token,_)|token == &timer_token) { return TimeoutAction::Drop; }
                    let result = data.state.native_system_control(&json!({"command":"output_rollback","token":timer_token}));
                    if result["ok"] == true { TimeoutAction::Drop } else { TimeoutAction::ToDuration(Duration::from_millis(500)) }
                }).map_err(|e|e.to_string())?;
                self.native_system.pending_output = Some((token.clone(), settings));
                Ok(json!({"ok":true,"token":token}))
            }
            "output_commit" | "output_rollback" => {
                if value["command"] == "output_rollback" && self.native_system.completed_rollback.as_deref().is_some_and(|token| value["token"].as_str() == Some(token)) {
                    return Ok(json!({"ok":true}));
                }
                let (token, settings) = self.native_system.pending_output.as_ref().ok_or("No pending display confirmation")?;
                if value["token"].as_str() != Some(token.as_str()) { return Err("Invalid display confirmation token".into()); }
                let settings = settings.clone();
                if value["command"] == "output_rollback" && self.space.outputs().any(|output|output.name() == settings["name"].as_str().unwrap_or("")) {
                    let mut callback = self.native_system.output.take().ok_or("Display hardware controls require DRM")?;
                    let result = callback(self, &json!({"command":"output_power","on":true})).and_then(|_|callback(self, &json!({"command":"output_configure","settings":settings})));
                    self.native_system.output = Some(callback);
                    result?;
                }
                if value["command"] == "output_rollback" { self.native_system.completed_rollback = value["token"].as_str().map(str::to_string); }
                self.native_system.pending_output = None;
                Ok(json!({"ok":true}))
            }
            "output_configure" | "output_power" => {
                let mut callback = self
                    .native_system
                    .output
                    .take()
                    .ok_or("Display hardware controls require the standalone DRM backend")?;
                let result = callback(self, value);
                self.native_system.output = Some(callback);
                result
            }
            _ => Err("Unsupported native system command".into()),
        })();
        result.unwrap_or_else(|error| json!({"ok":false,"error":error}))
    }
    pub fn load_native_input(&mut self) {
        let path = std::env::var_os("ORBIT_DATA")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .parent()
                    .unwrap()
                    .join("data")
            })
            .join("input.conf");
        let Ok(metadata) = std::fs::symlink_metadata(&path) else {
            return;
        };
        if !metadata.is_file() || metadata.len() > 65536 {
            return;
        }
        let Ok(text) = std::fs::read_to_string(path) else {
            return;
        };
        let Some(line) = text
            .lines()
            .find_map(|line| line.strip_prefix("# orbit-settings: "))
        else {
            return;
        };
        let Ok(config) = serde_json::from_str::<Value>(line) else {
            return;
        };
        let Ok(fields) = keys(&config["configured"]) else {
            return;
        };
        if validate(&config["values"]).is_err() {
            return;
        }
        if self
            .apply_native_input(&config["values"], &fields, "")
            .is_ok()
        {
            self.native_system.values = config["values"].clone();
            self.native_system.configured = fields;
            self.native_system.overrides = config
                .get("overrides")
                .filter(|v| v.as_object().is_some_and(|o| o.len() <= 64))
                .cloned()
                .unwrap_or(json!({}));
        }
    }
    pub fn apply_native_input(
        &mut self,
        values: &Value,
        fields: &[String],
        selector: &str,
    ) -> Result<(), String> {
        validate(values)?;
        let keyboard = fields
            .iter()
            .any(|k| matches!(k.as_str(), "layout" | "repeatRate" | "repeatDelay"));
        if keyboard && !selector.is_empty() {
            return Err(
                "Native keyboard layouts/repeat apply to the whole seat; choose All devices".into(),
            );
        }
        // Resolve installed rules before touching pointer/touchpad settings.
        // Reuse the compiled text below rather than reparsing layout rules after
        // hardware changes. No compilation occurs for pointer-only operations.
        let keymap=if fields.iter().any(|key|key=="layout") {Some(compile_layout(values["layout"].as_str().unwrap())?)} else {None};
        #[cfg(feature = "drm")]
        {
            if !selector.is_empty()
                && !self
                    .native_system
                    .devices
                    .iter()
                    .any(|d| native_device_id(d) == selector)
            {
                return Err("Input device disconnected".into());
            }
            if !selector.is_empty() {
                let device = self
                    .native_system
                    .devices
                    .iter()
                    .find(|d| native_device_id(d) == selector)
                    .unwrap();
                if fields.iter().any(|k| k == "pointerSpeed") && !device.config_accel_is_available()
                {
                    return Err("This device does not support pointer acceleration".into());
                }
                if fields.iter().any(|k| k == "naturalScroll")
                    && !device.config_scroll_has_natural_scroll()
                {
                    return Err("This device does not support natural scrolling".into());
                }
                if fields.iter().any(|k| k == "tapToClick") && device.config_tap_finger_count() == 0
                {
                    return Err("This device does not support tap-to-click".into());
                }
            }
            // Snapshot device values so a rejected setting restores every touched device.
            let originals = self
                .native_system
                .devices
                .iter()
                .filter(|d| selector.is_empty() || native_device_id(d) == selector)
                .map(|d| {
                    (
                        d.clone(),
                        d.config_accel_speed(),
                        d.config_scroll_natural_scroll_enabled(),
                        d.config_tap_enabled(),
                    )
                })
                .collect::<Vec<_>>();
            for (mut device, _, _, _) in originals.iter().cloned() {
                let result = (|| {
                    if fields.iter().any(|k| k == "pointerSpeed")
                        && device.config_accel_is_available()
                    {
                        device
                            .config_accel_set_speed(values["pointerSpeed"].as_f64().unwrap())
                            .map_err(|e| format!("Pointer speed: {e:?}"))?;
                    }
                    if fields.iter().any(|k| k == "naturalScroll")
                        && device.config_scroll_has_natural_scroll()
                    {
                        device
                            .config_scroll_set_natural_scroll_enabled(
                                values["naturalScroll"].as_bool().unwrap(),
                            )
                            .map_err(|e| format!("Natural scrolling: {e:?}"))?;
                    }
                    if fields.iter().any(|k| k == "tapToClick")
                        && device.config_tap_finger_count() > 0
                    {
                        device
                            .config_tap_set_enabled(values["tapToClick"].as_bool().unwrap())
                            .map_err(|e| format!("Touchpad tapping: {e:?}"))?;
                    }
                    Ok::<(), String>(())
                })();
                if let Err(error) = result {
                    for (mut original, speed, scroll, tap) in originals {
                        if original.config_accel_is_available() {
                            let _ = original.config_accel_set_speed(speed);
                        }
                        if original.config_scroll_has_natural_scroll() {
                            let _ = original.config_scroll_set_natural_scroll_enabled(scroll);
                        }
                        if original.config_tap_finger_count() > 0 {
                            let _ = original.config_tap_set_enabled(tap);
                        }
                    }
                    return Err(error);
                }
            }
        }
        let keyboard_handle = self
            .seat
            .get_keyboard()
            .ok_or("Keyboard seat unavailable")?;
        if let Some(keymap)=keymap {
            keyboard_handle.set_keymap_from_string(self,keymap).map_err(|error|error.to_string())?;
        }
        if fields
            .iter()
            .any(|k| matches!(k.as_str(), "repeatRate" | "repeatDelay"))
        {
            keyboard_handle.change_repeat_info(
                values["repeatRate"].as_i64().unwrap() as i32,
                values["repeatDelay"].as_i64().unwrap() as i32,
            );
        }
        Ok(())
    }
    fn native_keyboard_layouts(&mut self) -> (String, Vec<String>) {
        self.seat.get_keyboard().map(|keyboard| {
            keyboard.with_xkb_state(self, |context| {
                let xkb=context.xkb().lock().unwrap();
                let active=xkb.layout_name(xkb.active_layout()).to_owned();
                let names=xkb.layouts().take(4).map(|layout|xkb.layout_name(layout).to_owned()).collect();
                (active,names)
            })
        }).unwrap_or_default()
    }
    pub fn native_inputs(&mut self) -> Value {
        #[cfg(feature = "drm")]
        {
            use smithay::reexports::input::DeviceCapability;
            let (active_name,layout_names)=self.native_keyboard_layouts();
            return Value::Array(self.native_system.devices.iter().map(|device|{let keyboard=device.has_capability(DeviceCapability::Keyboard);let mut row=json!({"identifier":native_device_id(device),"name":device.name(),"type":if keyboard{"keyboard"}else{"pointer"},"xkb_layout_names":layout_names,"xkb_active_layout_name":active_name,"repeat_rate":self.native_system.values["repeatRate"],"repeat_delay":self.native_system.values["repeatDelay"],"libinput":{"accel_speed":device.config_accel_speed(),"natural_scroll":if device.config_scroll_natural_scroll_enabled(){"enabled"}else{"disabled"},"tap":if device.config_tap_finger_count()>0{Some(if device.config_tap_enabled(){"enabled"}else{"disabled"})}else{None}}});if device.config_tap_finger_count()==0 {row["libinput"].as_object_mut().unwrap().remove("tap");}row}).collect());
        }
        #[cfg(not(feature = "drm"))]
        json!([])
    }
}
pub fn transform_name(transform: smithay::utils::Transform) -> &'static str {
    use smithay::utils::Transform;
    match transform {
        Transform::Normal => "normal",
        Transform::_90 => "90",
        Transform::_180 => "180",
        Transform::_270 => "270",
        Transform::Flipped => "flipped",
        Transform::Flipped90 => "flipped-90",
        Transform::Flipped180 => "flipped-180",
        Transform::Flipped270 => "flipped-270",
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn display_checkpoint_expiry_restores_authoritative_state_and_is_idempotent() {
        use smithay::{output::{Output, PhysicalProperties, Subpixel, Mode}, reexports::{calloop::EventLoop, wayland_server::Display}, utils::Transform};
        use std::{cell::RefCell, rc::Rc, time::{Duration, Instant}};
        let runtime = std::env::temp_dir().join(format!("orbit-transaction-test-{}",std::process::id()));
        std::fs::create_dir_all(&runtime).unwrap();
        let original = std::env::var_os("XDG_RUNTIME_DIR");
        std::env::set_var("XDG_RUNTIME_DIR",&runtime);
        let mut event_loop = EventLoop::try_new().unwrap();
        let display = Display::<OrbitCompositor>::new().unwrap();
        let display_handle = display.handle();
        let mut state = OrbitCompositor::new(&mut event_loop,display);
        state.native_system.loop_handle = Some(event_loop.handle());
        let output = Output::new("test-output".into(),PhysicalProperties {size:(0,0).into(),subpixel:Subpixel::Unknown,make:"test".into(),model:"test".into()});
        output.change_current_state(Some(Mode{size:(1280,720).into(),refresh:60_000}),Some(Transform::Normal),None,Some((10,20).into()));
        state.space.map_output(&output,(10,20));
        let calls = Rc::new(RefCell::new(Vec::new()));let observed = calls.clone();
        state.native_system.output = Some(Box::new(move |_,value|{observed.borrow_mut().push(value.clone());Ok(json!({"ok":true}))}));
        let checkpoint = state.native_system_control(&json!({"command":"output_checkpoint","name":"test-output","seconds":1}));
        assert_eq!(checkpoint["ok"],true);let token = checkpoint["token"].clone();
        assert_eq!(state.native_system_control(&json!({"command":"output_rollback","token":"wrong","settings":{"mode":"malicious"}}))["ok"],false);
        assert!(calls.borrow().is_empty());
        let mut data = crate::CalloopData{state,display_handle};
        let deadline = Instant::now()+Duration::from_secs(7);
        while data.state.native_system.pending_output.is_some() && Instant::now()<deadline {event_loop.dispatch(Duration::from_millis(100),&mut data).unwrap();}
        assert!(data.state.native_system.pending_output.is_none());
        let values = calls.borrow();assert_eq!(values.len(),2);assert_eq!(values[1]["settings"]["mode"],"1280x720@60.000Hz");assert_eq!(values[1]["settings"]["x"],10);drop(values);
        assert_eq!(data.state.native_system_control(&json!({"command":"output_rollback","token":token}))["ok"],true);
        assert_eq!(calls.borrow().len(),2);
        // Exercise the real seat setter/getter, not configured-code labels.
        for (layout,names) in [
            ("ca",vec!["French (Canada)"]),
            ("se",vec!["Swedish"]),
            ("jp",vec!["Japanese"]),
            ("us,ca,se,jp",vec!["English (US)","French (Canada)","Swedish","Japanese"]),
        ] {
            let mut values=NativeSystem::default().values;values["layout"]=json!(layout);
            data.state.apply_native_input(&values,&["layout".into()],"").unwrap();
            let (active,actual)=data.state.native_keyboard_layouts();
            assert_eq!(actual,names,"{layout}");assert_eq!(active,names[0]);
        }
        let before=data.state.native_keyboard_layouts();
        let mut invalid=NativeSystem::default().values;invalid["layout"]=json!("abstract_missing_xkb_layout");
        assert!(data.state.apply_native_input(&invalid,&["layout".into()],"").is_err());
        assert_eq!(data.state.native_keyboard_layouts(),before);
        data.state.apply_native_input(&NativeSystem::default().values,&["layout".into()],"").unwrap();
        assert_eq!(data.state.native_keyboard_layouts().1,vec!["English (US)"]);
        drop(data);drop(event_loop);
        if let Some(original)=original {std::env::set_var("XDG_RUNTIME_DIR",original);} else {std::env::remove_var("XDG_RUNTIME_DIR");}
        let _=std::fs::remove_dir_all(runtime);
    }
    #[test]
    fn input_validation_rejects_invalid_ranges_and_types() {
        let original = NativeSystem::default().values;
        assert!(validate(&original).is_ok());
        for (key, value) in [
            ("pointerSpeed", json!(2)),
            ("pointerSpeed", json!("0")),
            ("repeatRate", json!(-1)),
            ("repeatDelay", json!(true)),
            ("layout", json!("us;touch")),
            ("naturalScroll", json!("true")),
        ] {
            let mut changed = original.clone();
            changed[key] = value;
            assert!(validate(&changed).is_err(), "{key}");
        }
    }
    #[test]
    fn installed_canadian_swedish_japanese_and_multiple_layouts_compile() {
        for layout in ["ca","se","jp","us,ca,se,jp"] {
            let mut values=NativeSystem::default().values;values["layout"]=json!(layout);
            assert!(validate(&values).is_ok(),"{layout}");
            let text=compile_layout(layout).unwrap_or_else(|error|panic!("{layout}: {error}"));
            let context=xkb::Context::new(xkb::CONTEXT_NO_FLAGS);
            let keymap=xkb::Keymap::new_from_string(&context,text,xkb::KEYMAP_FORMAT_TEXT_V1,xkb::KEYMAP_COMPILE_NO_FLAGS).unwrap();
            assert_eq!(keymap.num_layouts() as usize,layout.split(',').count());
        }
    }
    #[test]
    fn keyboard_layout_syntax_is_bounded_and_missing_installed_rules_fail() {
        for layout in ["","us,","us,us","us,ca,se,ja,de","../us","us(altgr)","us;touch","us+ru","us\0"] {
            assert!(validate_layout_codes(layout).is_err(),"{layout:?}");
        }
        assert!(validate_layout_codes(&"x".repeat(33)).is_err());
        assert!(compile_layout("abstract_missing_xkb_layout").is_err());
        assert!(compile_layout("ja").is_err()); // Japanese is the installed XKB code jp.
    }
    #[test]
    fn fields_are_a_bounded_allowlist() {
        assert!(keys(&json!(["layout", "tapToClick"])).is_ok());
        assert!(keys(&json!(["command"])).is_err());
        assert!(keys(&json!(null)).is_err());
        assert!(keys(&json!([
            "layout", "layout", "layout", "layout", "layout", "layout", "layout"
        ]))
        .is_err());
    }
    #[test]
    fn configuration_defaults_do_not_advertise_hardware() {
        let state = NativeSystem::default();
        assert!(state.output.is_none());
        assert!(state.configured.is_empty());
    }
}
#[cfg(feature = "drm")]
pub fn native_device_id(device: &smithay::reexports::input::Device) -> String {
    // libinput returns a refcounted udev handle tied to the live device. Read only
    // stable ID_PATH; eventN numbering alone must never select another boot's mouse.
    let path = unsafe { device.udev_device() }
        .and_then(|device| {
            device
                .property_value("ID_PATH")
                .map(|s| s.to_string_lossy().into_owned())
        })
        .unwrap_or_else(|| device.sysname().to_string());
    let identity = format!(
        "{}:{}:{}:{}",
        device.id_vendor(),
        device.id_product(),
        device.name(),
        path
    );
    let hash = identity.bytes().fold(0xcbf29ce484222325u64, |hash, byte| {
        (hash ^ byte as u64).wrapping_mul(0x100000001b3)
    });
    format!(
        "native_{:04x}_{:04x}_{hash:016x}",
        device.id_vendor(),
        device.id_product()
    )
}
