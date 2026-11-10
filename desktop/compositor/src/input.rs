use smithay::{
    backend::input::{
        AbsolutePositionEvent, Axis, AxisSource, ButtonState, Event, InputBackend, InputEvent,
        KeyState, KeyboardKeyEvent, PointerAxisEvent, PointerButtonEvent,
    },
    input::{
        keyboard::FilterResult,
        pointer::{AxisFrame, ButtonEvent, MotionEvent},
    },
    reexports::wayland_server::protocol::wl_surface::WlSurface,
    utils::SERIAL_COUNTER,
    wayland::seat::WaylandFocus,
};

use crate::state::OrbitCompositor;

impl OrbitCompositor {
    #[allow(non_upper_case_globals)] // upstream xkbcommon keysym names
    pub fn process_input_event<I: InputBackend>(&mut self, event: InputEvent<I>) {
        self.notify_activity();
        self.sync_layer_focus();
        if self.protocols.is_locked() {
            self.process_locked_input(event);
            return;
        }
        match event {
            InputEvent::Keyboard { event, .. } => {
                let serial = SERIAL_COUNTER.next_serial();
                let time = Event::time_msec(&event);

                let pressed = event.state() == KeyState::Pressed;
                let action = self.seat.get_keyboard().unwrap().input::<String, _>(
                    self,
                    event.key_code(),
                    event.state(),
                    serial,
                    time,
                    |state, modifiers, key| {
                        let sym = key.modified_sym().raw();
                        use smithay::input::keyboard::keysyms::*;
                        if sym == KEY_Super_L || sym == KEY_Super_R {
                            if pressed {
                                state.protocols.super_pending = true;
                                return FilterResult::Intercept(String::new());
                            }
                            let activate = std::mem::take(&mut state.protocols.super_pending);
                            return FilterResult::Intercept(if activate {
                                "launcher".into()
                            } else {
                                String::new()
                            });
                        }
                        if pressed {
                            state.protocols.super_pending = false;
                        }
                        if !pressed
                            && (sym == KEY_Alt_L || sym == KEY_Alt_R)
                            && std::mem::take(&mut state.protocols.alt_switching)
                        {
                            return FilterResult::Intercept("switch-accept".into());
                        }
                        if modifiers.alt && (sym == KEY_Tab || sym == KEY_ISO_Left_Tab) {
                            if pressed {
                                state.protocols.alt_switching = true;
                            }
                            return FilterResult::Intercept(if !pressed {
                                String::new()
                            } else if modifiers.shift {
                                "switch-back".into()
                            } else {
                                "switch-next".into()
                            });
                        }
                        if pressed {
                            let base = key
                                .raw_latin_sym_or_raw_current_sym()
                                .map(|sym| sym.raw())
                                .unwrap_or(sym);
                            if modifiers.ctrl && modifiers.alt && !modifiers.logo && base == KEY_q {
                                return FilterResult::Intercept("logout".into());
                            }
                            if modifiers.logo && !modifiers.ctrl && !modifiers.alt {
                                if (KEY_1..=KEY_4).contains(&base) {
                                    let number = base - KEY_1 + 1;
                                    return FilterResult::Intercept(if modifiers.shift {
                                        format!("move-space-{number}")
                                    } else {
                                        format!("__workspace-{number}")
                                    });
                                }
                                if !modifiers.shift {
                                    match base {
                                        KEY_q => {
                                            return FilterResult::Intercept("close-window".into())
                                        }
                                        KEY_f => {
                                            return FilterResult::Intercept(
                                                "fullscreen-window".into(),
                                            )
                                        }
                                        KEY_space => {
                                            return FilterResult::Intercept("launcher".into())
                                        }
                                        _ => {}
                                    }
                                }
                            }
                        }
                        if pressed {
                            if let Some(binding) = state
                                .ipc
                                .shortcuts
                                .iter()
                                .find(|binding| binding.matches(modifiers, sym))
                            {
                                return FilterResult::Intercept(binding.action.clone());
                            }
                        }
                        if pressed && modifiers.ctrl && modifiers.alt {
                            if sym == KEY_Up || sym == KEY_Left || sym == KEY_Page_Up {
                                return FilterResult::Intercept("__previous_workspace".into());
                            }
                            if sym == KEY_Down || sym == KEY_Right || sym == KEY_Page_Down {
                                return FilterResult::Intercept("__next_workspace".into());
                            }
                        }
                        let action = match sym {
                            KEY_XF86AudioRaiseVolume => Some("volume-up"),
                            KEY_XF86AudioLowerVolume => Some("volume-down"),
                            KEY_XF86AudioMute => Some("volume-mute"),
                            KEY_XF86AudioMicMute => Some("microphone-mute"),
                            KEY_XF86AudioPlay => Some("media-play-pause"),
                            KEY_XF86AudioPause => Some("media-pause"),
                            KEY_XF86AudioStop => Some("media-stop"),
                            KEY_XF86AudioNext => Some("media-next"),
                            KEY_XF86AudioPrev => Some("media-previous"),
                            KEY_XF86MonBrightnessUp => Some("brightness-up"),
                            KEY_XF86MonBrightnessDown => Some("brightness-down"),
                            KEY_Print => Some("screenshot"),
                            _ => None,
                        };
                        if let Some(action) = action {
                            return FilterResult::Intercept(if pressed {
                                action.into()
                            } else {
                                String::new()
                            });
                        }
                        FilterResult::Forward
                    },
                );
                if action.is_none() {
                    if let Some(focus) = self.seat.get_keyboard().unwrap().current_focus() {
                        if self.recent_key_serials.len() >= 8 { self.recent_key_serials.remove(0); }
                        self.recent_key_serials.push((serial, focus));
                    }
                }
                if let Some(action) = action {
                    match action.as_str() {
                        "__previous_workspace" => self.step_workspace(-1),
                        "__next_workspace" => self.step_workspace(1),
                        "" => {}
                        _ if action.starts_with("__workspace-") => {
                            if let Ok(number) = action[12..].parse::<usize>() {
                                self.switch_workspace(
                                    number - 1,
                                    if number > self.current_workspace + 1 {
                                        1
                                    } else {
                                        -1
                                    },
                                );
                            }
                        }
                        _ => self.publish_action(&action),
                    }
                }
            }
            InputEvent::PointerMotion { .. } => {}
            InputEvent::PointerMotionAbsolute { event, .. } => {
                // Hotplug can temporarily leave the session without an output.
                let Some(output) = self.space.outputs().next() else { return; };
                let Some(output_geo) = self.space.output_geometry(output) else { return; };

                let pos = event.position_transformed(output_geo.size) + output_geo.loc.to_f64();

                let serial = SERIAL_COUNTER.next_serial();

                let pointer = self.seat.get_pointer().unwrap();

                let under = self.surface_under(pos);

                pointer.motion(
                    self,
                    under,
                    &MotionEvent {
                        location: pos,
                        serial,
                        time: event.time_msec(),
                    },
                );
                pointer.frame(self);
            }
            InputEvent::PointerButton { event, .. } => {
                if self.transition.is_some() {
                    return;
                }
                let pointer = self.seat.get_pointer().unwrap();
                let keyboard = self.seat.get_keyboard().unwrap();

                let serial = SERIAL_COUNTER.next_serial();

                let button = event.button_code();

                let button_state = event.state();
                // Settle visual interpolation before hit-testing. Re-enter the
                // final surface even when the pointer itself has not moved.
                if button_state==ButtonState::Pressed && !self.window_motions.active.is_empty() {
                    self.clear_window_motions();self.request_redraw();
                    if !pointer.is_grabbed() {
                        let location=pointer.current_location();let under=self.surface_under(location);
                        pointer.motion(self,under,&MotionEvent {location,serial,time:event.time_msec()});
                    }
                }


                if ButtonState::Pressed == button_state && button == 0x110 && !pointer.is_grabbed()
                {
                    if let Some((id, window, x)) = self.header_at(pointer.current_location()) {
                        pointer.motion(
                            self,
                            None,
                            &MotionEvent {
                                location: pointer.current_location(),
                                serial,
                                time: event.time_msec(),
                            },
                        );
                        pointer.button(
                            self,
                            &ButtonEvent {
                                button,
                                state: button_state,
                                serial,
                                time: event.time_msec(),
                            },
                        );
                        self.header_pressed(id, window, x);
                        pointer.frame(self);
                        return;
                    }
                }
                if ButtonState::Pressed == button_state
                    && !pointer.is_grabbed()
                    && !self.pointer_layer_focus(pointer.current_location())
                {
                    if let Some((window, _loc)) = self
                        .space
                        .element_under(pointer.current_location())
                        .map(|(w, l)| (w.clone(), l))
                    {
                        self.space.raise_element(&window, true);
                        keyboard.set_focus(
                            self,
                            window.wl_surface().map(|s| s.into_owned()),
                            serial,
                        );
                        self.space.elements().for_each(|window| {
                            if let Some(xdg) = window.toplevel() {
                                xdg.send_pending_configure();
                            }
                        });
                    } else {
                        self.space.elements().for_each(|window| {
                            window.set_activated(false);
                            if let Some(xdg) = window.toplevel() {
                                xdg.send_pending_configure();
                            }
                        });
                        keyboard.set_focus(self, Option::<WlSurface>::None, serial);
                    }
                };

                pointer.button(
                    self,
                    &ButtonEvent {
                        button,
                        state: button_state,
                        serial,
                        time: event.time_msec(),
                    },
                );
                pointer.frame(self);
            }
            InputEvent::PointerAxis { event, .. } => {
                let source = event.source();

                let horizontal_amount = event.amount(Axis::Horizontal).unwrap_or_else(|| {
                    event.amount_v120(Axis::Horizontal).unwrap_or(0.0) * 15.0 / 120.
                });
                let vertical_amount = event.amount(Axis::Vertical).unwrap_or_else(|| {
                    event.amount_v120(Axis::Vertical).unwrap_or(0.0) * 15.0 / 120.
                });
                let horizontal_amount_discrete = event.amount_v120(Axis::Horizontal);
                let vertical_amount_discrete = event.amount_v120(Axis::Vertical);

                let mut frame = AxisFrame::new(event.time_msec()).source(source);
                if horizontal_amount != 0.0 {
                    frame = frame.value(Axis::Horizontal, horizontal_amount);
                    if let Some(discrete) = horizontal_amount_discrete {
                        frame = frame.v120(Axis::Horizontal, discrete as i32);
                    }
                }
                if vertical_amount != 0.0 {
                    frame = frame.value(Axis::Vertical, vertical_amount);
                    if let Some(discrete) = vertical_amount_discrete {
                        frame = frame.v120(Axis::Vertical, discrete as i32);
                    }
                }

                if source == AxisSource::Finger {
                    if event.amount(Axis::Horizontal) == Some(0.0) {
                        frame = frame.stop(Axis::Horizontal);
                    }
                    if event.amount(Axis::Vertical) == Some(0.0) {
                        frame = frame.stop(Axis::Vertical);
                    }
                }

                let pointer = self.seat.get_pointer().unwrap();
                pointer.axis(self, frame);
                pointer.frame(self);
            }
            _ => {}
        }
        self.request_redraw();
    }
}
