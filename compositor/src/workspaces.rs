//! Live surface workspace transitions. No screenshot capture or copied textures.
use crate::OrbitCompositor;
use smithay::{utils::SERIAL_COUNTER, wayland::seat::WaylandFocus};
use std::time::{Duration, Instant};
#[derive(Clone, Copy)]
pub struct Transition {
    pub from: usize,
    pub direction: f64,
    pub started: Instant,
}
impl OrbitCompositor {
    pub fn request_redraw(&mut self) {
        self.update_idle_inhibition();
        self.publish_snapshot();
        if !self.redraw_pending {
            self.redraw_pending = true;
            if let Some(redraw) = &self.redraw {
                redraw();
            }
        }
    }
    pub fn switch_workspace(&mut self, target: usize, direction: i32) {
        if self
            .seat
            .get_pointer()
            .map(|pointer| pointer.is_grabbed())
            .unwrap_or(false)
        {
            return;
        }
        if target >= self.workspaces.len() {
            return;
        }
        if self.transition.is_some() {
            self.pending_workspace = Some((target, direction));
            return;
        }
        if target == self.current_workspace {
            return;
        }
        self.clear_window_motions();
        let from = self.current_workspace;
        let incoming = std::mem::take(&mut self.workspaces[target]);
        let outgoing = std::mem::replace(&mut self.space, incoming);
        self.workspaces[from] = outgoing;
        self.current_workspace = target;
        self.transition = if self.reduced_motion {
            None
        } else {
            Some(Transition {
                from,
                direction: if direction < 0 { -1.0 } else { 1.0 },
                started: Instant::now(),
            })
        };
        let top = self.space.elements().last().cloned();
        if let Some(top) = &top {
            self.space.raise_element(top, true);
        }
        let focus = top.and_then(|window| window.wl_surface().map(|surface| surface.into_owned()));
        self.seat
            .get_keyboard()
            .unwrap()
            .set_focus(self, focus, SERIAL_COUNTER.next_serial());
        self.send_window_activation_configures();
        self.request_redraw();
    }
    pub fn step_workspace(&mut self, direction: i32) {
        let base = self
            .pending_workspace
            .map(|(target, _)| target)
            .unwrap_or(self.current_workspace);
        let target = (base as i32 + direction).rem_euclid(self.workspaces.len() as i32) as usize;
        self.switch_workspace(target, direction);
    }
    pub fn animation_progress(&mut self) -> f64 {
        let Some(transition) = self.transition else {
            return 1.0;
        };
        let duration = Duration::from_millis(if self.economy { 180 } else { 240 });
        let progress =
            (transition.started.elapsed().as_secs_f64() / duration.as_secs_f64()).min(1.0);
        if progress >= 1.0 {
            self.transition = None;
            if let Some((target, direction)) = self.pending_workspace.take() {
                self.switch_workspace(target, direction);
                return 0.0;
            }
        }
        progress
    }
    pub fn move_window_to_workspace(&mut self, id: u64, target: usize) -> bool {
        if target >= self.workspaces.len() {
            return false;
        }
        let Some((_, window)) = self.windows.iter().find(|(ident, _)| *ident == id).cloned() else {
            return false;
        };
        if let Some((workspace, _)) = self.ipc.minimized.get_mut(&id) {
            *workspace = target;
            self.request_redraw();
            return true;
        }
        if let Some((workspace, _)) = self.xwayland.minimized.get_mut(&id) {
            *workspace = target;
            self.request_redraw();
            return true;
        }
        self.window_motions.active.remove(&id);
        self.window_motions.pending_open.remove(&id);
        let location = self
            .space
            .element_location(&window)
            .or_else(|| {
                self.workspaces
                    .iter()
                    .find_map(|space| space.element_location(&window))
            })
            .unwrap_or((80, 80).into());
        self.space.unmap_elem(&window);
        for space in &mut self.workspaces {
            space.unmap_elem(&window);
        }
        let space = if target == self.current_workspace {
            &mut self.space
        } else {
            &mut self.workspaces[target]
        };
        space.map_element(window.clone(), location, true);
        if target != self.current_workspace {
            self.refocus_after_unmap(&window);
        }
        self.request_redraw();
        true
    }
}
