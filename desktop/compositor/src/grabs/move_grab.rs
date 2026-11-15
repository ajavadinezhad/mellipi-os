use crate::{window_snap::DragSnap, OrbitCompositor};
use smithay::{
    desktop::Window,
    input::pointer::{
        AxisFrame, ButtonEvent, GestureHoldBeginEvent, GestureHoldEndEvent, GesturePinchBeginEvent,
        GesturePinchEndEvent, GesturePinchUpdateEvent, GestureSwipeBeginEvent,
        GestureSwipeEndEvent, GestureSwipeUpdateEvent, GrabStartData as PointerGrabStartData,
        MotionEvent, PointerGrab, PointerInnerHandle, RelativeMotionEvent,
    },
    reexports::wayland_server::protocol::wl_surface::WlSurface,
    utils::{Logical, Point},
};

pub struct MoveSurfaceGrab {
    pub start_data: PointerGrabStartData<OrbitCompositor>,
    pub window: Window,
    pub drag: DragSnap,
}

impl PointerGrab<OrbitCompositor> for MoveSurfaceGrab {
    fn motion(
        &mut self,
        data: &mut OrbitCompositor,
        handle: &mut PointerInnerHandle<'_, OrbitCompositor>,
        _focus: Option<(WlSurface, Point<f64, Logical>)>,
        event: &MotionEvent,
    ) {
        // While the grab is active, no client has pointer focus
        handle.motion(data, None, event);

        if let Some(rect) = self.drag.motion(data, &self.window, event.location) {
            data.space.map_element(self.window.clone(), rect.loc, true);
            data.request_redraw();
        }
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

        if !handle.current_pressed().contains(&self.start_data.button) {
            self.drag
                .finish(data, &self.window, handle.current_location());
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
