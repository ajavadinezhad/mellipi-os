//! Event-driven ext-idle-notify and visible-surface idle inhibition.
//! Timers exist only for client-requested notifications; no idle polling.
use crate::{CalloopData, OrbitCompositor};
use smithay::wayland::seat::WaylandFocus;
use smithay::{
    delegate_idle_inhibit,
    reexports::{
        calloop::{
            timer::{TimeoutAction, Timer},
            LoopHandle, RegistrationToken,
        },
        wayland_protocols::ext::idle_notify::v1::server::{
            ext_idle_notification_v1 as notification, ext_idle_notifier_v1 as manager,
        },
        wayland_server::{
            protocol::{wl_seat::WlSeat, wl_surface::WlSurface},
            Client, DataInit, Dispatch, DisplayHandle, GlobalDispatch, New, Resource,
        },
    },
    wayland::idle_inhibit::{IdleInhibitHandler, IdleInhibitManagerState},
};
use std::time::Duration;
#[derive(Default)]
pub struct IdleState {
    handle: Option<LoopHandle<'static, CalloopData>>,
    notifications: Vec<Watch>,
    inhibitors: Vec<WlSurface>,
}
struct Watch {
    resource: notification::ExtIdleNotificationV1,
    seat: WlSeat,
    timeout: Duration,
    ignore_inhibitor: bool,
    idled: bool,
    token: Option<RegistrationToken>,
}
pub fn register(display: &DisplayHandle) {
    display.create_global::<OrbitCompositor, manager::ExtIdleNotifierV1, _>(2, ());
    IdleInhibitManagerState::new::<OrbitCompositor>(display);
}
pub fn install(handle: LoopHandle<'static, CalloopData>, data: &mut CalloopData) {
    data.state.protocols.idle.handle = Some(handle);
}
impl OrbitCompositor {
    pub fn notify_activity(&mut self) {
        let seat = self.seat.clone();
        let resources = self
            .protocols
            .idle
            .notifications
            .iter()
            .filter(|w| seat.owns(&w.seat))
            .map(|w| w.resource.clone())
            .collect::<Vec<_>>();
        for resource in resources {
            self.arm_idle(&resource, true);
        }
    }
    fn idle_inhibited(&self) -> bool {
        if self.protocols.is_locked() {
            return false;
        }
        self.protocols.idle.inhibitors.iter().any(|surface| {
            let mapped = smithay::wayland::compositor::with_states(surface, |states| {
                states
                    .data_map
                    .get::<smithay::backend::renderer::utils::RendererSurfaceStateUserData>()
                    .is_some_and(|state| state.lock().unwrap().buffer().is_some())
            });
            if !mapped {
                return false;
            }

            self.space
                .elements()
                .any(|window| window.wl_surface().is_some_and(|s| s.as_ref() == surface))
                || self.space.outputs().any(|output| {
                    smithay::desktop::layer_map_for_output(output)
                        .layers()
                        .any(|layer| layer.wl_surface() == surface)
                })
        })
    }
    pub fn update_idle_inhibition(&mut self) {
        self.protocols.idle.inhibitors.retain(Resource::is_alive);
        let resources = self
            .protocols
            .idle
            .notifications
            .iter()
            .filter(|w| !w.ignore_inhibitor)
            .map(|w| w.resource.clone())
            .collect::<Vec<_>>();
        let inhibited = self.idle_inhibited();
        for resource in resources {
            if inhibited {
                self.arm_idle(&resource, true);
            } else if self
                .protocols
                .idle
                .notifications
                .iter()
                .find(|w| w.resource == resource)
                .is_some_and(|w| w.token.is_none() && !w.idled)
            {
                self.arm_idle(&resource, false);
            }
        }
    }
    fn arm_idle(&mut self, resource: &notification::ExtIdleNotificationV1, activity: bool) {
        let inhibited = self.idle_inhibited();
        let idle = &mut self.protocols.idle;
        let Some(handle) = idle.handle.clone() else {
            return;
        };
        let Some(watch) = idle
            .notifications
            .iter_mut()
            .find(|w| &w.resource == resource)
        else {
            return;
        };
        if let Some(token) = watch.token.take() {
            handle.remove(token);
        }
        if activity && watch.idled {
            watch.resource.resumed();
            watch.idled = false;
        }
        if inhibited && !watch.ignore_inhibitor {
            return;
        }
        let resource = resource.clone();
        if let Ok(token) =
            handle.insert_source(Timer::from_duration(watch.timeout), move |_, _, data| {
                let inhibited = data.state.idle_inhibited();
                if let Some(watch) = data
                    .state
                    .protocols
                    .idle
                    .notifications
                    .iter_mut()
                    .find(|w| w.resource == resource)
                {
                    watch.token = None;
                    if resource.is_alive() && (!inhibited || watch.ignore_inhibitor) {
                        resource.idled();
                        watch.idled = true;
                    }
                }
                let _ = data.display_handle.flush_clients();
                TimeoutAction::Drop
            })
        {
            watch.token = Some(token);
        }
    }
}
impl IdleInhibitHandler for OrbitCompositor {
    fn inhibit(&mut self, surface: WlSurface) {
        self.protocols.idle.inhibitors.push(surface);
        self.update_idle_inhibition();
    }
    fn uninhibit(&mut self, surface: WlSurface) {
        if let Some(index) = self
            .protocols
            .idle
            .inhibitors
            .iter()
            .position(|s| s == &surface)
        {
            self.protocols.idle.inhibitors.remove(index);
        }
        self.update_idle_inhibition();
    }
}
delegate_idle_inhibit!(OrbitCompositor);
impl GlobalDispatch<manager::ExtIdleNotifierV1, ()> for OrbitCompositor {
    fn bind(
        _: &mut Self,
        _: &DisplayHandle,
        _: &Client,
        resource: New<manager::ExtIdleNotifierV1>,
        _: &(),
        init: &mut DataInit<'_, Self>,
    ) {
        init.init(resource, ());
    }
}
impl Dispatch<manager::ExtIdleNotifierV1, ()> for OrbitCompositor {
    fn request(
        state: &mut Self,
        _: &Client,
        resource: &manager::ExtIdleNotifierV1,
        request: manager::Request,
        _: &(),
        _: &DisplayHandle,
        init: &mut DataInit<'_, Self>,
    ) {
        let (id, timeout, seat, ignore) = match request {
            manager::Request::GetIdleNotification { id, timeout, seat } => {
                (id, timeout, seat, false)
            }
            manager::Request::GetInputIdleNotification { id, timeout, seat } => {
                (id, timeout, seat, true)
            }
            _ => return,
        };
        let notification = init.init(id, ());
        if state.protocols.idle.notifications.len() >= 256 || !state.seat.owns(&seat) {
            resource.post_error(
                0u32,
                "Invalid idle notification seat or notification limit exceeded",
            );
            return;
        }
        state.protocols.idle.notifications.push(Watch {
            resource: notification.clone(),
            seat,
            timeout: Duration::from_millis(timeout as u64),
            ignore_inhibitor: ignore,
            idled: false,
            token: None,
        });
        state.arm_idle(&notification, false);
    }
}
impl Dispatch<notification::ExtIdleNotificationV1, ()> for OrbitCompositor {
    fn request(
        _: &mut Self,
        _: &Client,
        _: &notification::ExtIdleNotificationV1,
        _: notification::Request,
        _: &(),
        _: &DisplayHandle,
        _: &mut DataInit<'_, Self>,
    ) {
    }
    fn destroyed(
        state: &mut Self,
        _: smithay::reexports::wayland_server::backend::ClientId,
        resource: &notification::ExtIdleNotificationV1,
        _: &(),
    ) {
        if let Some(index) = state
            .protocols
            .idle
            .notifications
            .iter()
            .position(|w| &w.resource == resource)
        {
            let watch = state.protocols.idle.notifications.remove(index);
            if let (Some(handle), Some(token)) = (&state.protocols.idle.handle, watch.token) {
                handle.remove(token);
            }
        }
    }
}
