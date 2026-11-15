use crate::{
    window_snap::{is_fullscreen, supports_tile, SnapZone},
    OrbitCompositor,
};
use smithay::{
    desktop::{layer_map_for_output, Window},
    output::Output,
    reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State,
    utils::{Logical, Point, Rectangle, Size},
    wayland::{compositor::with_states, seat::WaylandFocus, shell::xdg::SurfaceCachedState},
    xwayland::xwm::WmWindowType,
};

#[derive(Clone, Copy, Default)]
pub(crate) enum WindowPlacement {
    #[default]
    Off,
    Columns,
    Grid,
    Rows,
    MainStack,
    Count(usize),
}

impl WindowPlacement {
    pub(crate) fn parse(value: &str) -> Option<Self> {
        match value {
            "off" => Some(Self::Off),
            "columns" => Some(Self::Columns),
            "grid" => Some(Self::Grid),
            "rows" => Some(Self::Rows),
            "main-stack" => Some(Self::MainStack),
            _ => (2..=9)
                .find(|count| value == FORMAT_NAMES[*count])
                .map(Self::Count),
        }
    }

    pub(crate) fn name(self) -> &'static str {
        match self {
            Self::Off => "off",
            Self::Columns => "columns",
            Self::Grid => "grid",
            Self::Rows => "rows",
            Self::MainStack => "main-stack",
            Self::Count(count) => FORMAT_NAMES[count],
        }
    }

    fn zones(self) -> Vec<SnapZone> {
        match self {
            Self::Off => vec![],
            Self::Columns => vec![SnapZone::Left, SnapZone::Right],
            Self::Rows => vec![SnapZone::Top, SnapZone::Bottom],
            Self::MainStack => vec![SnapZone::Left, SnapZone::TopRight, SnapZone::BottomRight],
            Self::Grid => vec![
                SnapZone::TopLeft,
                SnapZone::TopRight,
                SnapZone::BottomLeft,
                SnapZone::BottomRight,
            ],
            Self::Count(count) => {
                let rows = if count <= 3 {
                    1
                } else if count <= 6 {
                    2
                } else {
                    3
                };
                (0..rows)
                    .flat_map(|row| {
                        let columns = count / rows + usize::from(row < count % rows);
                        (0..columns).map(move |column| SnapZone::GridCell {
                            column: column as i32,
                            columns: columns as i32,
                            row: row as i32,
                            rows: rows as i32,
                        })
                    })
                    .collect()
            }
        }
    }
    fn fallback_zones(self) -> &'static [SnapZone] {
        match self {
            Self::Grid => &[SnapZone::Left, SnapZone::Right],
            _ => &[],
        }
    }
}

const FORMAT_NAMES: [&str; 10] = [
    "", "", "grid-2", "grid-3", "grid-4", "grid-5", "grid-6", "grid-7", "grid-8", "grid-9",
];

fn fixed_size(min: Size<i32, Logical>, max: Size<i32, Logical>) -> bool {
    (max.w > 0 && min.w >= max.w) || (max.h > 0 && min.h >= max.h)
}

fn eligible(window: &Window) -> bool {
    if is_fullscreen(window) {
        return false;
    }
    if let Some(surface) = window.x11_surface() {
        return !surface.is_override_redirect()
            && !surface.is_popup()
            && surface.is_transient_for().is_none()
            && matches!(surface.window_type(), None | Some(WmWindowType::Normal))
            && !surface.is_maximized()
            && !fixed_size(
                surface.min_size().unwrap_or_default(),
                surface.max_size().unwrap_or_default(),
            );
    }
    let Some(surface) = window.toplevel() else {
        return false;
    };
    surface.parent().is_none()
        && !surface.with_pending_state(|state| state.states.contains(State::Maximized))
        && with_states(surface.wl_surface(), |states| {
            let mut cache = states.cached_state.get::<SurfaceCachedState>();
            let state = cache.current();
            !fixed_size(state.min_size, state.max_size)
        })
}

impl OrbitCompositor {
    fn placement_output(&self, opening: &Window) -> Option<Output> {
        let output_at = |point: Point<f64, Logical>| {
            self.space.outputs().find(|output| {
                self.space
                    .output_geometry(output)
                    .is_some_and(|area| area.to_f64().contains(point))
            })
        };
        let keyboard_output = self
            .seat
            .get_keyboard()
            .and_then(|keyboard| keyboard.current_focus())
            .and_then(|focus| {
                self.space.elements().find(|window| {
                    *window != opening
                        && window.wl_surface().is_some_and(|surface| *surface == focus)
                })
            })
            .and_then(|window| self.space.element_geometry(window))
            .and_then(|rect| {
                let center = rect.loc.to_f64() + (rect.size.to_f64() / 2.0).to_point();
                output_at(center)
            });
        keyboard_output
            .or_else(|| {
                self.seat
                    .get_pointer()
                    .and_then(|pointer| output_at(pointer.current_location()))
            })
            .or_else(|| self.space.outputs().next())
            .cloned()
    }

    pub(crate) fn place_new_window(&mut self, id: u64, window: &Window) -> bool {
        let zones = self.window_placement.zones();
        if zones.is_empty() || self.protocols.is_locked() || !eligible(window) {
            return false;
        }
        let Some((target, location, false)) = self.window_location(id, window) else {
            return false;
        };
        let previous = self.snapped_windows.get(&id);
        let output = previous
            .and_then(|snap| {
                self.space
                    .outputs()
                    .find(|output| output.name() == snap.output_name)
            })
            .cloned()
            .or_else(|| self.placement_output(window));
        let Some(output) = output else {
            return false;
        };
        let Some(output_rect) = self.space.output_geometry(&output) else {
            return false;
        };
        let mut area = layer_map_for_output(&output).non_exclusive_zone();
        area.loc += output_rect.loc;
        let name = output.name();
        let occupied: Vec<_> = self
            .windows
            .iter()
            .filter_map(|(other, window)| {
                let snap = self.snapped_windows.get(other)?;
                if *other == id || snap.output_name != name {
                    return None;
                }
                let (workspace, _, minimized) = self.window_location(*other, window)?;
                (workspace == target && !minimized).then(|| snap.zone.rect(area))
            })
            .collect();
        let fallback = self.window_placement.fallback_zones();
        let preferred = previous
            .map(|snap| snap.zone)
            .filter(|zone| zones.contains(zone) || fallback.contains(zone));
        let Some((zone, rect)) = preferred
            .into_iter()
            .chain(zones.iter().chain(fallback).copied())
            .find_map(|zone| {
                let tile = zone.rect(area);
                if occupied.iter().any(|used| tile.overlaps(*used)) {
                    return None;
                }
                let client = crate::decoration::client_area(window, tile);
                supports_tile(window, client).then_some((zone, client))
            })
        else {
            return false;
        };
        let size = window
            .x11_surface()
            .map(|surface| surface.geometry().size)
            .unwrap_or_else(|| window.geometry().size);
        if size.w <= 1 || size.h <= 1 {
            return false;
        }
        let floating_area = crate::decoration::client_area(window, area);
        let x = location.x.clamp(
            floating_area.loc.x,
            floating_area.loc.x + (floating_area.size.w - size.w).max(0),
        );
        let y = location.y.clamp(
            floating_area.loc.y,
            floating_area.loc.y + (floating_area.size.h - size.h).max(0),
        );
        let restore = previous
            .map(|snap| snap.restore)
            .unwrap_or_else(|| Rectangle::new((x, y).into(), size));
        self.apply_window_snap(id, window, &output, zone, rect, restore)
    }

    pub(crate) fn place_restored_window(&mut self, id: u64, window: &Window) {
        if matches!(self.window_placement, WindowPlacement::Off)
            || !eligible(window)
            || !self.snapped_windows.contains_key(&id)
            || self.protocols.is_locked()
        {
            return;
        }
        if !self.place_new_window(id, window) {
            if let Some(restore) = self.forget_snap(id, window) {
                self.apply_snap(window, restore, None);
            }
        }
    }

    pub(crate) fn set_window_placement(&mut self, layout: WindowPlacement) {
        self.window_placement = layout;
        if matches!(layout, WindowPlacement::Off) || self.protocols.is_locked() {
            return;
        }
        let zones = layout.zones();
        let outputs: Vec<_> = self.space.outputs().cloned().collect();
        for output in &outputs {
            let mut windows: Vec<_> = self
                .windows
                .iter()
                .filter_map(|(id, window)| {
                    let location = self.space.element_location(window)?;
                    let size = window.geometry().size;
                    if !eligible(window) || size.w <= 1 || size.h <= 1 {
                        return None;
                    }
                    let belongs = outputs
                        .iter()
                        .filter_map(|output| {
                            self.space
                                .output_geometry(output)
                                .map(|rect| (output, rect))
                        })
                        .filter_map(|(output, rect)| {
                            rect.intersection(Rectangle::new(location, size))
                                .map(|overlap| {
                                    (output, overlap.size.w as i64 * overlap.size.h as i64)
                                })
                        })
                        .max_by_key(|(_, overlap)| *overlap)
                        .is_some_and(|(candidate, _)| candidate == output);
                    belongs.then(|| (*id, window.clone(), Rectangle::new(location, size)))
                })
                .collect();
            windows.sort_by_key(|(id, _, rect)| (rect.loc.y, rect.loc.x, *id));
            let mut candidates: Vec<_> = windows
                .iter()
                .map(|(id, window, floating)| {
                    let compatible = |zones: &[SnapZone]| -> Vec<_> {
                        zones
                            .iter()
                            .filter_map(|zone| {
                                let rect = self.snap_rect(window, output, *zone)?;
                                supports_tile(window, rect).then_some((*zone, rect))
                            })
                            .collect()
                    };
                    let mut tiles = compatible(&zones);
                    if tiles.is_empty() {
                        tiles = compatible(layout.fallback_zones());
                    }
                    (*id, window, *floating, tiles)
                })
                .collect();
            // Reserve the fewest available choices first for constrained apps.
            candidates.sort_by_key(|(_, _, _, tiles)| tiles.len());
            let Some(output_rect) = self.space.output_geometry(output) else {
                continue;
            };
            let mut workarea = layer_map_for_output(output).non_exclusive_zone();
            workarea.loc += output_rect.loc;
            let mut occupied: Vec<Rectangle<i32, Logical>> = Vec::new();
            for (id, window, floating, tiles) in candidates {
                let tile = tiles.into_iter().find(|(zone, _)| {
                    !occupied
                        .iter()
                        .any(|used| used.overlaps(zone.rect(workarea)))
                });
                if let Some((zone, rect)) = tile {
                    let restore = self
                        .snapped_windows
                        .get(&id)
                        .map_or(floating, |snap| snap.restore);
                    self.apply_window_snap(id, window, output, zone, rect, restore);
                    occupied.push(zone.rect(workarea));
                } else if let Some(restore) = self.forget_snap(id, window) {
                    self.apply_snap(window, restore, None);
                }
            }
        }
        self.request_redraw();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layouts_limit_capacity_and_use_reading_order() {
        assert!(WindowPlacement::Off.zones().is_empty());
        assert_eq!(
            WindowPlacement::Columns.zones(),
            [SnapZone::Left, SnapZone::Right]
        );
        assert_eq!(
            WindowPlacement::Grid.zones(),
            [
                SnapZone::TopLeft,
                SnapZone::TopRight,
                SnapZone::BottomLeft,
                SnapZone::BottomRight
            ]
        );
        assert!(WindowPlacement::parse("invalid").is_none());
    }

    #[test]
    fn numbered_grids_cover_the_output_without_overlapping() {
        let workarea = Rectangle::new((-121, 22).into(), (1919, 1079).into());
        for count in 2..=9 {
            let layout = WindowPlacement::parse(FORMAT_NAMES[count]).unwrap();
            assert_eq!(layout.name(), FORMAT_NAMES[count]);
            let cells: Vec<_> = layout
                .zones()
                .into_iter()
                .map(|zone| zone.rect(workarea))
                .collect();
            assert_eq!(cells.len(), count);
            assert_eq!(
                cells.iter().map(|r| r.size.w * r.size.h).sum::<i32>(),
                1919 * 1079
            );
            for (i, cell) in cells.iter().enumerate() {
                assert_eq!(cell.intersection(workarea), Some(*cell));
                assert!(!cells[..i].iter().any(|other| other.overlaps(*cell)));
            }
        }
        assert!(WindowPlacement::parse("grid-10").is_none());
    }

    #[test]
    fn equal_minimum_and_maximum_make_a_window_fixed() {
        assert!(fixed_size((320, 100).into(), (320, 500).into()));
        assert!(!fixed_size((320, 100).into(), (0, 0).into()));
        assert!(!fixed_size((320, 100).into(), (640, 500).into()));
    }
}
