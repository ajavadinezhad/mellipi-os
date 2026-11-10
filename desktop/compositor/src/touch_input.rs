//! Route touch sequences through the seat, with an exclusive secure-lock target.
//! Lock/unlock, device removal, VT loss and output removal cancel old sequences.
use crate::OrbitCompositor;
use smithay::{
    backend::input::{AbsolutePositionEvent, Event, InputBackend, InputEvent, TouchEvent},
    input::touch::{DownEvent, MotionEvent, UpEvent},
    utils::{Logical, Point, Rectangle, SERIAL_COUNTER},
};

/// Absolute device coordinates use the first mapped output, matching the existing
/// absolute-pointer policy. Reject malformed coordinates rather than hit-testing
/// another output/application. Per-device output calibration is a later feature.
fn mapped_touch(
    position: Point<f64, Logical>,
    geometry: Rectangle<i32, Logical>,
) -> Option<Point<f64, Logical>> {
    if !position.x.is_finite()
        || !position.y.is_finite()
        || geometry.size.w <= 0
        || geometry.size.h <= 0
    {
        return None;
    }
    Some(
        Point::from((
            position.x.max(0.0).min((geometry.size.w - 1) as f64),
            position.y.max(0.0).min((geometry.size.h - 1) as f64),
        )) + geometry.loc.to_f64(),
    )
}
// Lazy selection prevents even consulting an application hit-test while locked.
fn touch_focus<T>(
    locked: bool,
    secure: impl FnOnce() -> Option<T>,
    normal: impl FnOnce() -> Option<T>,
) -> Option<T> {
    if locked {
        secure()
    } else {
        normal()
    }
}
impl OrbitCompositor {
    pub(crate) fn cancel_touch_sequence(&mut self) {
        if let Some(touch) = self.seat.get_touch() {
            touch.cancel(self);
            touch.unset_grab(self);
        }
    }
    pub(crate) fn process_touch_event<I: InputBackend>(
        &mut self,
        event: &InputEvent<I>,
        locked: bool,
    ) -> bool {
        let Some(touch) = self.seat.get_touch() else {
            return false;
        };
        // Callers must agree on the security domain. Never route a stale event
        // through an unlocked hit-test when a lock owner exists (or vice versa).
        if locked != self.protocols.is_locked() {
            self.cancel_touch_sequence();
            return true;
        }
        match event {
            InputEvent::TouchDown { event } => {
                let Some(output) = self.space.outputs().next().cloned() else {
                    self.cancel_touch_sequence();
                    return true;
                };
                let Some(geometry) = self.space.output_geometry(&output) else {
                    self.cancel_touch_sequence();
                    return true;
                };
                let Some(location) =
                    mapped_touch(event.position_transformed(geometry.size), geometry)
                else {
                    self.cancel_touch_sequence();
                    return true;
                };
                let target = touch_focus(
                    locked,
                    || {
                        let outputs = self
                            .space
                            .outputs()
                            .filter_map(|o| {
                                self.space.output_geometry(o).map(|r| (o.clone(), r.loc))
                            })
                            .collect::<Vec<_>>();
                        self.protocols.lock_surface_under(location, outputs)
                    },
                    || self.surface_under(location),
                );
                // During lock acquisition there may be no committed lock view.
                // Drop the touch then; there is deliberately no app fallback.
                if locked && target.is_none() {
                    self.cancel_touch_sequence();
                    return true;
                }
                // A normal desktop tap focuses/raises its client just like a
                // pointer press. This branch is never evaluated under a lock.
                if !locked && !self.pointer_layer_focus(location) {
                    if let Some((window, _)) = self
                        .space
                        .element_under(location)
                        .map(|(w, l)| (w.clone(), l))
                    {
                        self.space.raise_element(&window, true);
                        use smithay::wayland::seat::WaylandFocus;
                        self.seat.get_keyboard().unwrap().set_focus(
                            self,
                            window.wl_surface().map(|s| s.into_owned()),
                            SERIAL_COUNTER.next_serial(),
                        );
                        self.space.elements().for_each(|window| {
                            if let Some(xdg) = window.toplevel() {
                                xdg.send_pending_configure();
                            }
                        });
                    }
                }
                touch.down(
                    self,
                    target,
                    &DownEvent {
                        slot: event.slot(),
                        location,
                        serial: SERIAL_COUNTER.next_serial(),
                        time: event.time_msec(),
                    },
                );
            }
            InputEvent::TouchMotion { event } => {
                let Some(output) = self.space.outputs().next().cloned() else {
                    self.cancel_touch_sequence();
                    return true;
                };
                let Some(geometry) = self.space.output_geometry(&output) else {
                    self.cancel_touch_sequence();
                    return true;
                };
                let Some(location) =
                    mapped_touch(event.position_transformed(geometry.size), geometry)
                else {
                    self.cancel_touch_sequence();
                    return true;
                };
                let target = touch_focus(
                    locked,
                    || {
                        let outputs = self
                            .space
                            .outputs()
                            .filter_map(|o| {
                                self.space.output_geometry(o).map(|r| (o.clone(), r.loc))
                            })
                            .collect::<Vec<_>>();
                        self.protocols.lock_surface_under(location, outputs)
                    },
                    || self.surface_under(location),
                );
                touch.motion(
                    self,
                    target,
                    &MotionEvent {
                        slot: event.slot(),
                        location,
                        time: event.time_msec(),
                    },
                );
            }
            InputEvent::TouchUp { event } => touch.up(
                self,
                &UpEvent {
                    slot: event.slot(),
                    serial: SERIAL_COUNTER.next_serial(),
                    time: event.time_msec(),
                },
            ),
            InputEvent::TouchCancel { .. } => self.cancel_touch_sequence(),
            InputEvent::TouchFrame { .. } => touch.frame(self),
            _ => return false,
        }
        self.request_redraw();
        true
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lock_acquisition_never_falls_back_to_application_focus() {
        assert_eq!(
            touch_focus(
                true,
                || Some("locker"),
                || panic!("app hit-test while locked")
            ),
            Some("locker")
        );
        assert_eq!(
            touch_focus::<&str>(
                true,
                || None,
                || panic!("uncommitted lock must not fall back")
            ),
            None
        );
        assert_eq!(
            touch_focus(
                false,
                || panic!("unlocked path consulted lock"),
                || Some("app")
            ),
            Some("app")
        );
    }
    #[test]
    fn finite_device_coordinates_are_clamped_and_output_offset_is_applied() {
        let output = Rectangle::new((1920, 100).into(), (1280, 720).into());
        assert_eq!(
            mapped_touch((0., 0.).into(), output),
            Some((1920., 100.).into())
        );
        assert_eq!(
            mapped_touch((-5., 800.).into(), output),
            Some((1920., 819.).into())
        );
        assert_eq!(
            mapped_touch((9000., 15.).into(), output),
            Some((3199., 115.).into())
        );
    }
    #[test]
    fn malformed_input_or_missing_output_never_hit_tests_a_surface() {
        let output = Rectangle::new((0, 0).into(), (1280, 720).into());
        assert!(mapped_touch((f64::NAN, 0.).into(), output).is_none());
        assert!(mapped_touch((0., f64::INFINITY).into(), output).is_none());
        assert!(mapped_touch(
            (0., 0.).into(),
            Rectangle::new((0, 0).into(), (0, 720).into())
        )
        .is_none());
    }
}
