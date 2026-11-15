use crate::OrbitCompositor;
use smithay::{
    backend::renderer::{
        element::{solid::SolidColorRenderElement, Kind},
        utils::CommitCounter,
    },
    desktop::{layer_map_for_output, Window},
    output::Output,
    reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State,
    utils::{Logical, Point, Rectangle, Size},
    wayland::{compositor::with_states, shell::xdg::SurfaceCachedState},
};

const EDGE: f64 = 12.0;
const CORNER: f64 = 32.0;
const DRAG_START: f64 = 4.0;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SnapZone {
    Left,
    Right,
    Top,
    Bottom,
    TopLeft,
    TopRight,
    BottomLeft,
    BottomRight,
    Maximize,
    GridCell {
        column: i32,
        columns: i32,
        row: i32,
        rows: i32,
    },
}

impl SnapZone {
    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Left => "left",
            Self::Right => "right",
            Self::Top => "top",
            Self::Bottom => "bottom",
            Self::TopLeft => "top-left",
            Self::TopRight => "top-right",
            Self::BottomLeft => "bottom-left",
            Self::BottomRight => "bottom-right",
            Self::Maximize => "maximize",
            Self::GridCell { .. } => "grid-cell",
        }
    }

    fn at(output: Rectangle<i32, Logical>, point: Point<f64, Logical>) -> Option<Self> {
        if !output.to_f64().contains(point) {
            return None;
        }
        let left = point.x - f64::from(output.loc.x);
        let right = f64::from(output.size.w) - left;
        let top = point.y - f64::from(output.loc.y);
        let bottom = f64::from(output.size.h) - top;
        let edge_x = EDGE.min(f64::from(output.size.w) / 4.0);
        let edge_y = EDGE.min(f64::from(output.size.h) / 4.0);
        let corner_x = CORNER.min(f64::from(output.size.w) / 4.0);
        let corner_y = CORNER.min(f64::from(output.size.h) / 4.0);
        match (
            left <= edge_x,
            right <= edge_x,
            top <= edge_y,
            bottom <= edge_y,
        ) {
            (_, _, true, _) if left <= corner_x => Some(Self::TopLeft),
            (_, _, true, _) if right <= corner_x => Some(Self::TopRight),
            (true, _, _, _) if top <= corner_y => Some(Self::TopLeft),
            (_, true, _, _) if top <= corner_y => Some(Self::TopRight),
            (_, _, _, true) if left <= corner_x => Some(Self::BottomLeft),
            (_, _, _, true) if right <= corner_x => Some(Self::BottomRight),
            (true, _, _, _) if bottom <= corner_y => Some(Self::BottomLeft),
            (_, true, _, _) if bottom <= corner_y => Some(Self::BottomRight),
            (true, _, _, _) => Some(Self::Left),
            (_, true, _, _) => Some(Self::Right),
            (_, _, true, _) => Some(Self::Maximize),
            _ => None,
        }
    }

    pub(crate) fn rect(self, mut area: Rectangle<i32, Logical>) -> Rectangle<i32, Logical> {
        if let Self::GridCell {
            column,
            columns,
            row,
            rows,
        } = self
        {
            let x = |c| area.size.w * c / columns;
            let y = |r| area.size.h * r / rows;
            return Rectangle::new(
                (area.loc.x + x(column), area.loc.y + y(row)).into(),
                (x(column + 1) - x(column), y(row + 1) - y(row)).into(),
            );
        }
        let half_width = area.size.w / 2;
        let half_height = area.size.h / 2;
        match self {
            Self::Left | Self::TopLeft | Self::BottomLeft => area.size.w = half_width,
            Self::Right | Self::TopRight | Self::BottomRight => {
                area.loc.x += half_width;
                area.size.w -= half_width;
            }
            Self::Top | Self::Bottom | Self::Maximize | Self::GridCell { .. } => {}
        }
        match self {
            Self::Top | Self::TopLeft | Self::TopRight => area.size.h = half_height,
            Self::Bottom | Self::BottomLeft | Self::BottomRight => {
                area.loc.y += half_height;
                area.size.h -= half_height;
            }
            _ => {}
        }
        area
    }
}

#[derive(Clone)]
pub(crate) struct SnappedWindow {
    pub(crate) zone: SnapZone,
    pub(crate) output_name: String,
    pub(crate) restore: Rectangle<i32, Logical>,
}

pub(crate) struct DragSnap {
    restore: Option<Rectangle<i32, Logical>>,
    origin: Point<f64, Logical>,
    initial: Rectangle<i32, Logical>,
    drag_started: bool,
}

impl DragSnap {
    pub(crate) fn new(initial: Rectangle<i32, Logical>, origin: Point<f64, Logical>) -> Self {
        Self {
            restore: None,
            origin,
            initial,
            drag_started: false,
        }
    }

    pub(crate) fn motion(
        &mut self,
        data: &mut OrbitCompositor,
        window: &Window,
        point: Point<f64, Logical>,
    ) -> Option<Rectangle<i32, Logical>> {
        if data.protocols.is_locked() || data.space.element_location(window).is_none() {
            data.clear_snap_preview();
            return None;
        }
        let delta = point - self.origin;
        if !self.drag_started {
            if delta.x.hypot(delta.y) < DRAG_START {
                return None;
            }
            self.drag_started = true;
            self.restore = data.take_drag_restore(window);
        }
        data.update_snap_preview(window, point);
        let mut rect = self.initial;
        if let Some(restore) = self.restore {
            rect.size = restore.size;
            // Keep the same horizontal fraction of the title bar under the
            // pointer when a snapped or maximized window becomes floating.
            let offset = self.origin - self.initial.loc.to_f64();
            let fraction = (offset.x / f64::from(self.initial.size.w.max(1))).clamp(0.0, 1.0);
            let anchor = Point::from((fraction * f64::from(rect.size.w), offset.y));
            rect.loc = (point - anchor).to_i32_round();
        } else {
            rect.loc += delta.to_i32_round();
        }
        Some(rect)
    }

    pub(crate) fn finish(
        &self,
        data: &mut OrbitCompositor,
        window: &Window,
        point: Point<f64, Logical>,
    ) {
        if self.drag_started {
            let restore = self.restore.unwrap_or(self.initial);
            data.snap_window_at(window, point, restore);
        }
    }
}

fn supports_size(
    size: Size<i32, Logical>,
    min: Size<i32, Logical>,
    max: Size<i32, Logical>,
) -> bool {
    size.w > 0
        && size.h > 0
        && size.w >= min.w
        && size.h >= min.h
        && (max.w <= 0 || size.w <= max.w)
        && (max.h <= 0 || size.h <= max.h)
}

pub(crate) fn supports_tile(window: &Window, rect: Rectangle<i32, Logical>) -> bool {
    if let Some(surface) = window.x11_surface() {
        return supports_size(
            rect.size,
            surface.min_size().unwrap_or_default(),
            surface.max_size().unwrap_or_default(),
        );
    }
    if let Some(surface) = window.toplevel() {
        return with_states(surface.wl_surface(), |states| {
            let mut cache = states.cached_state.get::<SurfaceCachedState>();
            let state = cache.current();
            supports_size(rect.size, state.min_size, state.max_size)
        });
    }
    false
}

fn set_tile_state(
    surface: &smithay::wayland::shell::xdg::ToplevelSurface,
    zone: Option<SnapZone>,
    size: Size<i32, Logical>,
) {
    surface.with_pending_state(|state| {
        state.size = Some(size);
        // Only outward edges touch the output boundary. Interior edges
        // stay available to resize and decorate as free edges.
        for (edge, tiled) in [
            (
                State::TiledLeft,
                matches!(
                    zone,
                    Some(
                        SnapZone::Left
                            | SnapZone::Top
                            | SnapZone::Bottom
                            | SnapZone::TopLeft
                            | SnapZone::BottomLeft
                    )
                ) || matches!(zone, Some(SnapZone::GridCell { column: 0, .. })),
            ),
            (
                State::TiledRight,
                matches!(
                    zone,
                    Some(
                        SnapZone::Right
                            | SnapZone::Top
                            | SnapZone::Bottom
                            | SnapZone::TopRight
                            | SnapZone::BottomRight
                    )
                ) || matches!(zone, Some(SnapZone::GridCell { column, columns, .. }) if column + 1 == columns),
            ),
            (
                State::TiledTop,
                matches!(
                    zone,
                    Some(
                        SnapZone::Left
                            | SnapZone::Right
                            | SnapZone::Top
                            | SnapZone::TopLeft
                            | SnapZone::TopRight
                    )
                ) || matches!(zone, Some(SnapZone::GridCell { row: 0, .. })),
            ),
            (
                State::TiledBottom,
                matches!(
                    zone,
                    Some(
                        SnapZone::Left
                            | SnapZone::Right
                            | SnapZone::Bottom
                            | SnapZone::BottomLeft
                            | SnapZone::BottomRight
                    )
                ) || matches!(zone, Some(SnapZone::GridCell { row, rows, .. }) if row + 1 == rows),
            ),
        ] {
            if tiled {
                state.states.set(edge);
            } else {
                state.states.unset(edge);
            }
        }
        if zone == Some(SnapZone::Maximize) {
            state.states.set(State::Maximized);
        } else {
            state.states.unset(State::Maximized);
        }
    });
    surface.send_pending_configure();
}

impl OrbitCompositor {
    pub(crate) fn take_drag_restore(&mut self, window: &Window) -> Option<Rectangle<i32, Logical>> {
        let id = self.windows.iter().find(|(_, entry)| entry == window)?.0;
        self.window_motions.active.remove(&id);
        let snapped = self.snapped_windows.remove(&id);
        let restore = if let Some(surface) = window.x11_surface() {
            if surface.is_fullscreen() {
                return None;
            }
            let restore = if surface.is_maximized() {
                let _ = surface.set_maximized(false);
                self.xwayland.restore.remove(&id)
            } else {
                None
            };
            snapped.map(|snap| snap.restore).or(restore)
        } else if let Some(surface) = window.toplevel() {
            let maximized =
                surface.with_pending_state(|state| state.states.contains(State::Maximized));
            let restore = snapped.map(|snap| snap.restore).or_else(|| {
                if maximized {
                    self.normal_geometry.remove(&id)
                } else {
                    None
                }
            })?;
            self.normal_geometry.remove(&id);
            set_tile_state(surface, None, restore.size);
            Some(restore)
        } else {
            None
        };
        restore
    }

    fn snap_target(
        &self,
        window: &Window,
        point: Point<f64, Logical>,
    ) -> Option<(Output, SnapZone, Rectangle<i32, Logical>)> {
        if !self.window_snap_enabled
            || self.protocols.is_locked()
            || is_fullscreen(window)
            || self.space.element_location(window).is_none()
        {
            return None;
        }
        let (output, zone) = self.space.outputs().find_map(|output| {
            let rect = self.space.output_geometry(output)?;
            SnapZone::at(rect, point).map(|zone| (output.clone(), zone))
        })?;
        let rect = self.snap_rect(window, &output, zone)?;
        supports_tile(window, rect).then_some((output, zone, rect))
    }

    fn update_snap_preview(&mut self, window: &Window, point: Point<f64, Logical>) {
        let preview = self
            .snap_target(window, point)
            .and_then(|(output, zone, _)| {
                let output_rect = self.space.output_geometry(&output)?;
                let mut area = layer_map_for_output(&output).non_exclusive_zone();
                area.loc += output_rect.loc;
                let id = self.windows.iter().find(|(_, entry)| entry == window)?.0;
                Some((id, zone.rect(area)))
            });
        if self.snap_preview != preview {
            self.snap_preview = preview;
            self.request_redraw();
        }
    }

    pub(crate) fn clear_snap_preview(&mut self) {
        if self.snap_preview.take().is_some() {
            self.request_redraw();
        }
    }

    pub(crate) fn snap_preview_element(
        &self,
        output: &Output,
        scale: f64,
    ) -> Option<SolidColorRenderElement> {
        let (id, preview) = self.snap_preview?;
        if !self
            .windows
            .iter()
            .any(|(other, window)| *other == id && self.space.element_location(window).is_some())
        {
            return None;
        }
        let output_rect = self.space.output_geometry(output)?;
        let mut rect = preview.intersection(output_rect)?;
        rect.loc -= output_rect.loc;
        Some(SolidColorRenderElement::new(
            self.snap_preview_id.clone(),
            rect.to_physical_precise_round(scale),
            CommitCounter::default(),
            [0.055, 0.112, 0.184, 0.26],
            Kind::Unspecified,
        ))
    }

    fn snap_window_at(
        &mut self,
        window: &Window,
        point: Point<f64, Logical>,
        restore: Rectangle<i32, Logical>,
    ) {
        let Some((output, zone, rect)) = self.snap_target(window, point) else {
            return;
        };
        let Some(id) = self
            .windows
            .iter()
            .find(|(_, entry)| entry == window)
            .map(|(id, _)| *id)
        else {
            return;
        };
        self.apply_window_snap(id, window, &output, zone, rect, restore);
    }

    pub(crate) fn apply_window_snap(
        &mut self,
        id: u64,
        window: &Window,
        output: &Output,
        zone: SnapZone,
        rect: Rectangle<i32, Logical>,
        restore: Rectangle<i32, Logical>,
    ) -> bool {
        let from = self.window_rect(id);
        let workspace = self
            .window_location(id, window)
            .map(|(workspace, _, _)| workspace);
        if !self.apply_snap(window, rect, Some(zone)) {
            return false;
        }
        self.normal_geometry.remove(&id);
        self.xwayland.restore.remove(&id);
        if zone == SnapZone::Maximize {
            if window.x11_surface().is_some() {
                self.xwayland.restore.insert(id, restore);
            } else {
                self.normal_geometry.insert(id, restore);
            }
        }
        self.snapped_windows.insert(
            id,
            SnappedWindow {
                zone,
                output_name: output.name(),
                restore,
            },
        );
        if let Some(workspace) = workspace {
            self.reconcile_window_workspace(window, workspace, rect.loc);
        }
        if let Some(from) = from {
            self.start_window_resize(id, from, rect);
        }
        self.request_redraw();
        true
    }

    pub(crate) fn snap_rect(
        &self,
        window: &Window,
        output: &Output,
        zone: SnapZone,
    ) -> Option<Rectangle<i32, Logical>> {
        let output_rect = self.space.output_geometry(output)?;
        let mut area = layer_map_for_output(output).non_exclusive_zone();
        area.loc += output_rect.loc;
        Some(crate::decoration::client_area(window, zone.rect(area)))
    }

    pub(crate) fn apply_snap(
        &mut self,
        window: &Window,
        rect: Rectangle<i32, Logical>,
        zone: Option<SnapZone>,
    ) -> bool {
        if let Some(surface) = window.x11_surface() {
            if surface.configure(rect).is_err() {
                return false;
            }
            let _ = surface.set_maximized(zone == Some(SnapZone::Maximize));
            self.position_x11(surface, rect);
        } else if let Some(surface) = window.toplevel() {
            set_tile_state(surface, zone, rect.size);
            if self.space.element_location(window).is_some() {
                self.space.map_element(window.clone(), rect.loc, false);
            } else if let Some(space) = self
                .workspaces
                .iter_mut()
                .find(|space| space.element_location(window).is_some())
            {
                space.map_element(window.clone(), rect.loc, false);
            }
        } else {
            return false;
        }
        true
    }

    pub(crate) fn reflow_snap(&mut self, id: u64, window: &Window, output: &Output) -> bool {
        let Some(snap) = self.snapped_windows.get(&id) else {
            return false;
        };
        if is_fullscreen(window) {
            return false;
        }
        let output_name = output.name();
        if snap.output_name != output_name {
            let previous_connected = self
                .space
                .outputs()
                .any(|previous| previous.name() == snap.output_name);
            let first_output = self
                .space
                .outputs()
                .next()
                .is_some_and(|first| first == output);
            if previous_connected || !first_output {
                return false;
            }
        }
        let zone = snap.zone;
        let mut restore = snap.restore;
        if let Some(rect) = self
            .snap_rect(window, output, zone)
            .filter(|rect| supports_tile(window, *rect))
        {
            if self.apply_snap(window, rect, Some(zone)) {
                if let Some(snap) = self.snapped_windows.get_mut(&id) {
                    snap.output_name = output_name;
                }
                return true;
            }
        }
        // A smaller workarea may no longer accommodate the tile. Restore the
        // client's previous size and keep its title bar on the current output.
        self.snapped_windows.remove(&id);
        self.normal_geometry.remove(&id);
        self.xwayland.restore.remove(&id);
        if let Some(area) = self.snap_rect(window, output, SnapZone::Maximize) {
            restore.loc.x = restore.loc.x.clamp(
                area.loc.x,
                area.loc.x + (area.size.w - restore.size.w).max(0),
            );
            restore.loc.y = restore.loc.y.clamp(
                area.loc.y,
                area.loc.y + (area.size.h - restore.size.h).max(0),
            );
        }
        self.apply_snap(window, restore, None)
    }

    #[cfg(feature = "drm")]
    pub(crate) fn shift_snap_restore(
        &mut self,
        old: Rectangle<i32, Logical>,
        delta: Point<i32, Logical>,
    ) {
        for snap in self.snapped_windows.values_mut() {
            if old.contains(snap.restore.loc) {
                snap.restore.loc += delta;
            }
        }
    }

    pub(crate) fn forget_snap(
        &mut self,
        id: u64,
        window: &Window,
    ) -> Option<Rectangle<i32, Logical>> {
        let snap = self.snapped_windows.remove(&id)?;
        if let Some(surface) = window.toplevel() {
            surface.with_pending_state(|state| {
                for edge in [
                    State::TiledLeft,
                    State::TiledRight,
                    State::TiledTop,
                    State::TiledBottom,
                ] {
                    state.states.unset(edge);
                }
            });
        }
        Some(snap.restore)
    }
}

pub(crate) fn is_fullscreen(window: &Window) -> bool {
    window
        .x11_surface()
        .is_some_and(|surface| surface.is_fullscreen())
        || window.toplevel().is_some_and(|surface| {
            surface.with_pending_state(|state| state.states.contains(State::Fullscreen))
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn edges_and_corners_use_pointer_output_geometry() {
        let output = Rectangle::new((-1200, 40).into(), (1200, 800).into());
        assert_eq!(
            SnapZone::at(output, (-1199., 400.).into()),
            Some(SnapZone::Left)
        );
        assert_eq!(
            SnapZone::at(output, (-1., 400.).into()),
            Some(SnapZone::Right)
        );
        assert_eq!(
            SnapZone::at(output, (-1178., 41.).into()),
            Some(SnapZone::TopLeft)
        );
        assert_eq!(
            SnapZone::at(output, (-2., 60.).into()),
            Some(SnapZone::TopRight)
        );
        assert_eq!(
            SnapZone::at(output, (-1199., 830.).into()),
            Some(SnapZone::BottomLeft)
        );
        assert_eq!(
            SnapZone::at(output, (-24., 839.).into()),
            Some(SnapZone::BottomRight)
        );
        assert_eq!(
            SnapZone::at(output, (-600., 40.).into()),
            Some(SnapZone::Maximize)
        );
        assert_eq!(SnapZone::at(output, (-600., 839.).into()), None);
        assert_eq!(SnapZone::at(output, (0., 400.).into()), None);
    }

    #[test]
    fn odd_workareas_split_without_gaps() {
        let area = Rectangle::new((44, 20).into(), (1001, 701).into());
        assert_eq!(
            SnapZone::TopLeft.rect(area),
            Rectangle::new((44, 20).into(), (500, 350).into())
        );
        assert_eq!(
            SnapZone::BottomRight.rect(area),
            Rectangle::new((544, 370).into(), (501, 351).into())
        );
        assert_eq!(
            SnapZone::Right.rect(area),
            Rectangle::new((544, 20).into(), (501, 701).into())
        );
        assert_eq!(SnapZone::Maximize.rect(area), area);
    }
}
