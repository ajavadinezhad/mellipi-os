use crate::{window_snap::DragSnap, OrbitCompositor};
use smithay::{
    input::pointer::{
        AxisFrame, ButtonEvent, GestureHoldBeginEvent, GestureHoldEndEvent, GesturePinchBeginEvent,
        GesturePinchEndEvent, GesturePinchUpdateEvent, GestureSwipeBeginEvent,
        GestureSwipeEndEvent, GestureSwipeUpdateEvent, GrabStartData as PointerGrabStartData,
        MotionEvent, PointerGrab, PointerInnerHandle, RelativeMotionEvent,
    },
    reexports::wayland_server::protocol::wl_surface::WlSurface,
    utils::{Logical, Point, Rectangle},
    xwayland::{xwm::ResizeEdge, X11Surface},
};

pub struct X11SurfaceGrab {
    pub start_data: PointerGrabStartData<OrbitCompositor>,
    pub window: X11Surface,
    pub initial_rect: Rectangle<i32, Logical>,
    pub resize: Option<ResizeEdge>,
    pub button: u32,
    pub drag: Option<DragSnap>,
}

impl PointerGrab<OrbitCompositor> for X11SurfaceGrab {
    fn motion(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        _focus: Option<(WlSurface, Point<f64, Logical>)>,
        event: &MotionEvent,
    ) {
        // While the grab is active, no client has pointer focus
        handle.motion(data, None, event);

        if let Some(drag) = self.drag.as_mut() {
            if let Some((_, window)) = data.x11_window(&self.window) {
                if let Some(rect) = drag.motion(data, &window, event.location) {
                    let _ = self.window.configure(rect);
                    data.position_x11(&self.window, rect);
                }
            }
            return;
        }
        let delta = event.location - self.start_data.location;
        let mut rect = self.initial_rect;
        if let Some(edge) = self.resize {
            let left = matches!(
                edge,
                ResizeEdge::Left | ResizeEdge::TopLeft | ResizeEdge::BottomLeft
            );
            let right = matches!(
                edge,
                ResizeEdge::Right | ResizeEdge::TopRight | ResizeEdge::BottomRight
            );
            let top = matches!(
                edge,
                ResizeEdge::Top | ResizeEdge::TopLeft | ResizeEdge::TopRight
            );
            let bottom = matches!(
                edge,
                ResizeEdge::Bottom | ResizeEdge::BottomLeft | ResizeEdge::BottomRight
            );
            if left {
                rect.size.w -= delta.x.round() as i32;
            }
            if right {
                rect.size.w += delta.x.round() as i32;
            }
            if top {
                rect.size.h -= delta.y.round() as i32;
            }
            if bottom {
                rect.size.h += delta.y.round() as i32;
            }
            let min = self.window.min_size().unwrap_or((1, 1).into());
            let mut max = self.window.max_size().unwrap_or((16384, 16384).into());
            if max.w <= 0 {
                max.w = 16384;
            }
            if max.h <= 0 {
                max.h = 16384;
            }
            rect.size.w = rect.size.w.clamp(min.w.max(1), max.w.max(min.w).max(1));
            rect.size.h = rect.size.h.clamp(min.h.max(1), max.h.max(min.h).max(1));
            if left {
                rect.loc.x = self.initial_rect.loc.x + self.initial_rect.size.w - rect.size.w;
            }
            if top {
                rect.loc.y = self.initial_rect.loc.y + self.initial_rect.size.h - rect.size.h;
            }
        }
        let rect = data.bounded_x11_geometry(&self.window, rect);
        let _ = self.window.configure(rect);
        data.position_x11(&self.window, rect);
    }

    fn relative_motion(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        focus: Option<(WlSurface, Point<f64, Logical>)>,
        event: &RelativeMotionEvent,
    ) {
        handle.relative_motion(data, focus, event);
    }

    fn button(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &ButtonEvent,
    ) {
        handle.button(data, event);

        // The button is a button code as defined in the
        // Linux kernel's linux/input-event-codes.h header file, e.g. BTN_LEFT.

        if !handle.current_pressed().contains(&self.button) {
            if let (Some(drag), Some((_, window))) = (&self.drag, data.x11_window(&self.window)) {
                drag.finish(data, &window, handle.current_location());
            }
            handle.unset_grab(self, data, event.serial, event.time, true);
        }
    }

    fn axis(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        details: AxisFrame,
    ) {
        handle.axis(data, details)
    }

    fn frame(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
    ) {
        handle.frame(data);
    }

    fn gesture_swipe_begin(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GestureSwipeBeginEvent,
    ) {
        handle.gesture_swipe_begin(data, event)
    }

    fn gesture_swipe_update(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GestureSwipeUpdateEvent,
    ) {
        handle.gesture_swipe_update(data, event)
    }

    fn gesture_swipe_end(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GestureSwipeEndEvent,
    ) {
        handle.gesture_swipe_end(data, event)
    }

    fn gesture_pinch_begin(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GesturePinchBeginEvent,
    ) {
        handle.gesture_pinch_begin(data, event)
    }

    fn gesture_pinch_update(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GesturePinchUpdateEvent,
    ) {
        handle.gesture_pinch_update(data, event)
    }

    fn gesture_pinch_end(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GesturePinchEndEvent,
    ) {
        handle.gesture_pinch_end(data, event)
    }

    fn gesture_hold_begin(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GestureHoldBeginEvent,
    ) {
        handle.gesture_hold_begin(data, event)
    }

    fn gesture_hold_end(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        event: &GestureHoldEndEvent,
    ) {
        handle.gesture_hold_end(data, event)
    }

    fn start_data(&self) -> &PointerGrabStartData<OrbitCompositor> {
        &self.start_data
    }

    fn unset(&mut self, data: &mut OrbitCompositor) {
        data.clear_snap_preview();
    }
}
