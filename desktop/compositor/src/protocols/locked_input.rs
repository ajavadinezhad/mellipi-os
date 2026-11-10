//! Dedicated lock input route. Global/workspace shortcuts are not evaluated.
use crate::OrbitCompositor;
use smithay::{
    backend::input::{
        AbsolutePositionEvent, Axis, AxisSource, ButtonState, Event, InputBackend, InputEvent,
        KeyboardKeyEvent, PointerAxisEvent, PointerButtonEvent, PointerMotionEvent,
    },
    input::{
        keyboard::FilterResult,
        pointer::{AxisFrame, ButtonEvent, MotionEvent},
    },
    utils::SERIAL_COUNTER,
};
impl OrbitCompositor {
    pub fn process_locked_input<I: InputBackend>(&mut self, event: InputEvent<I>) {
        if !self.protocols.is_locked() {
            return;
        }
        match event {
            InputEvent::Keyboard { event, .. } => {
                // A previously trusted IME must not intercept password input.
                self.seat.get_keyboard().unwrap().unset_grab(self);
                self.seat.get_keyboard().unwrap().input::<(), _>(
                    self,
                    event.key_code(),
                    event.state(),
                    SERIAL_COUNTER.next_serial(),
                    event.time_msec(),
                    |_, _, _| FilterResult::Forward,
                );
            }
            InputEvent::PointerMotion { event, .. } => {
                let pointer = self.seat.get_pointer().unwrap();
                let candidate = pointer.current_location() + event.delta();
                let outputs = self
                    .space
                    .outputs()
                    .filter_map(|output| {
                        self.space
                            .output_geometry(output)
                            .map(|rect| (output.clone(), rect.loc))
                    })
                    .collect::<Vec<_>>();
                let location = self
                    .space
                    .outputs()
                    .filter_map(|output| self.space.output_geometry(output))
                    .find(|rect| rect.to_f64().contains(candidate))
                    .map(|_| candidate)
                    .unwrap_or(pointer.current_location());
                let target = self.protocols.lock_surface_under(location, outputs);
                pointer.motion(
                    self,
                    target,
                    &MotionEvent {
                        location,
                        serial: SERIAL_COUNTER.next_serial(),
                        time: event.time_msec(),
                    },
                );
                pointer.frame(self);
            }
            InputEvent::PointerMotionAbsolute { event, .. } => {
                let Some(output) = self.space.outputs().next().cloned() else {
                    return;
                };
                let Some(geometry) = self.space.output_geometry(&output) else {
                    return;
                };
                let location = event.position_transformed(geometry.size) + geometry.loc.to_f64();
                let outputs = self
                    .space
                    .outputs()
                    .filter_map(|output| {
                        self.space
                            .output_geometry(output)
                            .map(|rect| (output.clone(), rect.loc))
                    })
                    .collect::<Vec<_>>();
                let target = self.protocols.lock_surface_under(location, outputs);
                let pointer = self.seat.get_pointer().unwrap();
                pointer.motion(
                    self,
                    target,
                    &MotionEvent {
                        location,
                        serial: SERIAL_COUNTER.next_serial(),
                        time: event.time_msec(),
                    },
                );
                pointer.frame(self);
            }
            InputEvent::PointerButton { event, .. } => {
                let pointer = self.seat.get_pointer().unwrap();
                let serial = SERIAL_COUNTER.next_serial();
                if event.state() == ButtonState::Pressed {
                    let outputs = self
                        .space
                        .outputs()
                        .filter_map(|output| {
                            self.space
                                .output_geometry(output)
                                .map(|rect| (output.clone(), rect.loc))
                        })
                        .collect::<Vec<_>>();
                    let focus = self
                        .protocols
                        .lock_surface_under(pointer.current_location(), outputs)
                        .map(|(surface, _)| surface);
                    self.seat
                        .get_keyboard()
                        .unwrap()
                        .set_focus(self, focus, serial);
                }
                pointer.button(
                    self,
                    &ButtonEvent {
                        button: event.button_code(),
                        state: event.state(),
                        serial,
                        time: event.time_msec(),
                    },
                );
                pointer.frame(self);
            }
            InputEvent::PointerAxis { event, .. } => {
                let mut frame = AxisFrame::new(event.time_msec()).source(event.source());
                for axis in [Axis::Horizontal, Axis::Vertical] {
                    let amount = event
                        .amount(axis)
                        .unwrap_or_else(|| event.amount_v120(axis).unwrap_or(0.0) * 15.0 / 120.0);
                    if amount != 0.0 {
                        frame = frame.value(axis, amount);
                    }
                    if let Some(amount) = event.amount_v120(axis) {
                        frame = frame.v120(axis, amount as i32);
                    } else if event.source() == AxisSource::Finger {
                        frame = frame.stop(axis);
                    }
                }
                let pointer = self.seat.get_pointer().unwrap();
                pointer.axis(self, frame);
                pointer.frame(self);
            }
            _ => {}
        }
    }
}
