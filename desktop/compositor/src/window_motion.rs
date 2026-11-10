//! Bounded, live-buffer window effects. Window state changes immediately; only
//! rendering interpolates. No screenshots, copied textures or idle frame loop.
use crate::OrbitCompositor;
use smithay::{
    backend::renderer::{
        element::{
            memory::MemoryRenderBufferRenderElement,
            surface::WaylandSurfaceRenderElement,
            utils::{Relocate, RelocateRenderElement, RescaleRenderElement},
            AsRenderElements,
        },
        gles::GlesRenderer,
        ImportAll, ImportMem,
    },
    desktop::{utils::bbox_from_surface_tree, Window},
    utils::{Logical, Physical, Point, Rectangle, Scale},
    wayland::seat::WaylandFocus,
};
use std::{
    collections::{HashMap, HashSet},
    time::{Duration, Instant},
};
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Kind {
    Open,
    Minimize,
    Resize,
}
#[derive(Clone, Copy)]
pub struct Motion {
    pub kind: Kind,
    pub workspace: usize,
    pub from: Rectangle<f64, Logical>,
    pub to: Rectangle<f64, Logical>,
    pub started: Instant,
    pub requested: Instant,
    pub waiting: bool,
    pub duration: Duration,
}
#[derive(Default)]
pub struct WindowMotions {
    pub active: HashMap<u64, Motion>,
    pub pending_open: HashSet<u64>,
}
#[derive(Clone, Copy)]
pub struct Visual {
    pub rect: Rectangle<f64, Logical>,
    pub alpha: f32,
}
// X11 configure geometry precedes its buffer commit. Never use that requested
// size as proof that pixels arrived, or old buffers briefly collapse on maximize.
fn committed_geometry(window: &Window) -> Option<Rectangle<i32, Logical>> {
    let surface = window.wl_surface()?;
    let bbox = bbox_from_surface_tree(surface.as_ref(), (0, 0));
    if bbox.size.w <= 1 || bbox.size.h <= 1 {
        return None;
    }
    Some(if window.x11_surface().is_some() {
        bbox
    } else {
        window.geometry()
    })
}
fn eased(p: f64) -> f64 {
    1.0 - (1.0 - p.clamp(0., 1.)).powi(3)
}
fn mix(a: f64, b: f64, p: f64) -> f64 {
    a + (b - a) * p
}
fn interpolate(
    a: Rectangle<f64, Logical>,
    b: Rectangle<f64, Logical>,
    p: f64,
) -> Rectangle<f64, Logical> {
    Rectangle::new(
        (mix(a.loc.x, b.loc.x, p), mix(a.loc.y, b.loc.y, p)).into(),
        (mix(a.size.w, b.size.w, p), mix(a.size.h, b.size.h, p)).into(),
    )
}
impl Motion {
    fn visual(&self, now: Instant) -> Visual {
        let p = if self.waiting {
            0.
        } else {
            eased(
                now.saturating_duration_since(self.started).as_secs_f64()
                    / self.duration.as_secs_f64(),
            )
        };
        Visual {
            rect: interpolate(self.from, self.to, p),
            alpha: match self.kind {
                Kind::Open => p as f32,
                Kind::Minimize => (1. - p) as f32,
                Kind::Resize => 1.,
            },
        }
    }
}
impl OrbitCompositor {
    pub fn has_animations(&self) -> bool {
        self.transition.is_some() || !self.window_motions.active.is_empty()
    }
    pub fn clear_window_motions(&mut self) {
        self.window_motions.active.clear();
        self.window_motions.pending_open.clear();
    }
    pub fn window_rect(&self, id: u64) -> Option<Rectangle<f64, Logical>> {
        let (_, window) = self.windows.iter().find(|(i, _)| *i == id)?;
        let loc = self.space.element_location(window)?;
        Some(Rectangle::new(
            loc.to_f64(),
            committed_geometry(window)?.size.to_f64(),
        ))
    }
    fn insert_window_motion(
        &mut self,
        id: u64,
        kind: Kind,
        from: Rectangle<f64, Logical>,
        to: Rectangle<f64, Logical>,
        waiting: bool,
    ) {
        self.window_motions.pending_open.remove(&id);
        if !self.window_motion_enabled
            || self.protocols.is_locked()
            || self.transition.is_some()
            || from.size.w <= 1.
            || from.size.h <= 1.
        {
            self.window_motions.active.remove(&id);
            return;
        }
        if self.window_motions.active.len() >= 16 && !self.window_motions.active.contains_key(&id) {
            return;
        }
        let now = Instant::now();
        self.window_motions.active.insert(
            id,
            Motion {
                kind,
                workspace: self.current_workspace,
                from,
                to,
                started: now,
                requested: now,
                waiting,
                duration: Duration::from_millis(if self.economy { 140 } else { 200 }),
            },
        );
        self.request_redraw();
    }
    pub fn queue_window_open(&mut self, id: u64) {
        if self.window_motion_enabled && self.window_motions.pending_open.len() < 64 {
            self.window_motions.pending_open.insert(id);
        }
    }
    pub fn start_window_open(&mut self, id: u64) {
        let Some(to) = self.window_rect(id) else {
            return;
        };
        let from = Rectangle::new(
            (to.loc.x + to.size.w * 0.015, to.loc.y + 8.).into(),
            (to.size.w * 0.97, to.size.h * 0.97).into(),
        );
        self.insert_window_motion(id, Kind::Open, from, to, false);
    }
    pub fn start_window_minimize(&mut self, id: u64) {
        let Some(base) = self.window_rect(id) else {
            return;
        };
        let from = self
            .window_motions
            .active
            .get(&id)
            .map(|m| m.visual(Instant::now()).rect)
            .unwrap_or(base);
        let to = Rectangle::new(
            (from.loc.x + from.size.w * 0.04, from.loc.y + 18.).into(),
            (from.size.w * 0.92, from.size.h * 0.92).into(),
        );
        self.insert_window_motion(id, Kind::Minimize, from, to, false);
    }
    pub fn start_window_resize(
        &mut self,
        id: u64,
        from: Rectangle<f64, Logical>,
        to: Rectangle<i32, Logical>,
    ) {
        let from = self
            .window_motions
            .active
            .get(&id)
            .map(|m| m.visual(Instant::now()).rect)
            .unwrap_or(from);
        self.insert_window_motion(id, Kind::Resize, from, to.to_f64(), true);
    }
    pub fn advance_window_motions(&mut self) {
        if self.window_motions.active.is_empty() && self.window_motions.pending_open.is_empty() {
            return;
        }
        if !self.window_motion_enabled || self.protocols.is_locked() {
            self.clear_window_motions();
            return;
        }
        let ready: Vec<_> = self
            .window_motions
            .pending_open
            .iter()
            .copied()
            .filter(|id| {
                self.window_rect(*id)
                    .is_some_and(|r| r.size.w > 1. && r.size.h > 1.)
            })
            .collect();
        for id in ready {
            self.start_window_open(id);
        }
        let now = Instant::now();
        let windows = &self.windows;
        self.window_motions.active.retain(|id, m| {
            let Some((_, window)) = windows.iter().find(|(i, _)| i == id) else {
                return false;
            };
            if m.workspace != self.current_workspace {
                return false;
            }
            if m.kind == Kind::Open {
                if let Some(loc) = self.space.element_location(window) {
                    let Some(committed) = committed_geometry(window) else {
                        return false;
                    };
                    m.to = Rectangle::new(loc.to_f64(), committed.size.to_f64());
                    m.from = Rectangle::new(
                        (m.to.loc.x + m.to.size.w * 0.015, m.to.loc.y + 8.).into(),
                        (m.to.size.w * 0.97, m.to.size.h * 0.97).into(),
                    );
                } else {
                    return false;
                }
            }
            if m.waiting {
                let size = committed_geometry(window)
                    .map(|rect| rect.size)
                    .unwrap_or((0, 0).into());
                if (size.w as f64 - m.to.size.w).abs() <= 1.
                    && (size.h as f64 - m.to.size.h).abs() <= 1.
                {
                    m.waiting = false;
                    m.started = now;
                } else if now.saturating_duration_since(m.requested) > Duration::from_millis(250) {
                    return false;
                }
            }
            m.waiting || now.saturating_duration_since(m.started) < m.duration
        });
    }
    pub fn window_visual(&self, window: &Window) -> Option<Visual> {
        if self.window_motions.active.is_empty() {
            return None;
        }
        let (id, _) = self.windows.iter().find(|(_, w)| w == window)?;
        self.window_motions
            .active
            .get(id)
            .map(|m| m.visual(Instant::now()))
    }
    pub fn minimizing_windows(&self) -> Vec<(Window, Point<i32, Logical>)> {
        self.window_motions
            .active
            .iter()
            .filter(|(_, m)| m.kind == Kind::Minimize && m.workspace == self.current_workspace)
            .filter_map(|(id, m)| {
                self.windows
                    .iter()
                    .find(|(i, _)| i == id)
                    .map(|(_, w)| (w.clone(), m.from.loc.to_i32_round()))
            })
            .collect()
    }
}
smithay::backend::renderer::element::render_elements! {
 pub WindowRenderElement<R> where R: ImportAll + ImportMem;
 PlainSurface=WaylandSurfaceRenderElement<R>,
 PlainFrame=MemoryRenderBufferRenderElement<R>,
 Surface=RelocateRenderElement<RescaleRenderElement<WaylandSurfaceRenderElement<R>>>,
 Frame=RelocateRenderElement<RescaleRenderElement<MemoryRenderBufferRenderElement<R>>>,
}
pub fn elements(
    renderer: &mut GlesRenderer,
    window: &Window,
    pos: Point<i32, Physical>,
    scale: f64,
    visual: Option<Visual>,
    logical_location: Point<i32, Logical>,
) -> Vec<WindowRenderElement<GlesRenderer>> {
    if visual.is_none() {
        let mut elements: Vec<WindowRenderElement<GlesRenderer>> =
            crate::decoration::elements(renderer, window, pos, scale)
                .into_iter()
                .map(Into::into)
                .collect();
        let surfaces: Vec<WaylandSurfaceRenderElement<GlesRenderer>> =
            window.render_elements(renderer, pos, scale.into(), 1.);
        elements.extend(surfaces.into_iter().map(Into::into));
        return elements;
    }
    let mut factor = Scale::from(1.0);
    let mut surface_factor = Scale::from(1.0);
    let mut offset = Point::<i32, Physical>::from((0, 0));
    let mut alpha = 1.;
    if let Some(v) = visual {
        let size = window.geometry().size;
        if size.w > 0 && size.h > 0 {
            factor = Scale::from((v.rect.size.w / size.w as f64, v.rect.size.h / size.h as f64));
            let buffer_size = committed_geometry(window)
                .map(|rect| rect.size)
                .unwrap_or(size);
            surface_factor = Scale::from((
                v.rect.size.w / buffer_size.w.max(1) as f64,
                v.rect.size.h / buffer_size.h.max(1) as f64,
            ));
            offset = (v.rect.loc - logical_location.to_f64()).to_physical_precise_round(scale);
            alpha = v.alpha;
        }
    }
    let frames = crate::decoration::elements_with_alpha(renderer, window, pos, scale, alpha);
    let surfaces: Vec<WaylandSurfaceRenderElement<GlesRenderer>> =
        window.render_elements(renderer, pos, scale.into(), alpha);
    let origin = pos + window.geometry().loc.to_physical_precise_round(scale);
    let mut result: Vec<WindowRenderElement<GlesRenderer>> = frames
        .into_iter()
        .map(|e| {
            RelocateRenderElement::from_element(
                RescaleRenderElement::from_element(e, origin, factor),
                offset,
                Relocate::Relative,
            )
            .into()
        })
        .collect();
    result.extend(surfaces.into_iter().map(|e| {
        RelocateRenderElement::from_element(
            RescaleRenderElement::from_element(e, origin, surface_factor),
            offset,
            Relocate::Relative,
        )
        .into()
    }));
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn endpoints_and_monotonic_geometry() {
        let now = Instant::now();
        let a = Rectangle::new((10., 20.).into(), (400., 300.).into());
        let b = Rectangle::new((0., 0.).into(), (1920., 1080.).into());
        let m = Motion {
            kind: Kind::Resize,
            workspace: 0,
            from: a,
            to: b,
            started: now,
            requested: now,
            waiting: false,
            duration: Duration::from_millis(200),
        };
        assert_eq!(m.visual(now).rect, a);
        assert_eq!(m.visual(now + Duration::from_millis(200)).rect, b);
        let mut width = 400.;
        for t in 0..=200 {
            let v = m.visual(now + Duration::from_millis(t));
            assert!(v.rect.size.w >= width);
            width = v.rect.size.w;
            assert_eq!(v.alpha, 1.);
        }
    }
    #[test]
    fn waiting_does_not_advance_until_client_resize() {
        let now = Instant::now();
        let r = Rectangle::new((0., 0.).into(), (500., 400.).into());
        let m = Motion {
            kind: Kind::Resize,
            workspace: 0,
            from: r,
            to: r,
            started: now,
            requested: now,
            waiting: true,
            duration: Duration::from_millis(140),
        };
        assert_eq!(m.visual(now + Duration::from_secs(1)).rect, r);
    }
    #[test]
    fn opacity_endpoints() {
        let now = Instant::now();
        let r = Rectangle::new((0., 0.).into(), (500., 400.).into());
        for kind in [Kind::Open, Kind::Minimize] {
            let m = Motion {
                kind,
                workspace: 0,
                from: r,
                to: r,
                started: now,
                requested: now,
                waiting: false,
                duration: Duration::from_millis(140),
            };
            assert_eq!(
                m.visual(now).alpha,
                if kind == Kind::Open { 0. } else { 1. }
            );
            assert_eq!(
                m.visual(now + Duration::from_millis(140)).alpha,
                if kind == Kind::Open { 1. } else { 0. }
            );
        }
    }
}
