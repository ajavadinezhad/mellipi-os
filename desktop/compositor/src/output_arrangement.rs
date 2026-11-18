//! Compositor-owned transaction for logical positions, without hardware modesets.
use crate::OrbitCompositor;
use serde_json::{json, Value};
use smithay::{
    desktop::layer_map_for_output,
    output::Output,
    reexports::calloop::timer::{TimeoutAction, Timer},
    utils::{Logical, Point, Rectangle},
};
use std::{
    collections::HashSet,
    io::Read,
    time::{Duration, Instant},
};

type Rect = Rectangle<i32, Logical>;
type Position = Point<i32, Logical>;

#[derive(Clone)]
struct Move {
    output: Output,
    old: Rect,
    new: Rect,
}

pub(crate) struct Pending {
    token: String,
    deadline: Instant,
    moves: Vec<Move>,
}

fn positions(value: &Value) -> Result<Vec<(&str, Position, &Value)>, String> {
    let rows = value.as_array().ok_or("Expected display positions")?;
    if !(2..=32).contains(&rows.len()) {
        return Err("Arrange between two and 32 displays".into());
    }
    let mut names = HashSet::new();
    rows.iter()
        .map(|row| {
            let name = row["name"]
                .as_str()
                .filter(|name| {
                    !name.is_empty()
                        && name.len() <= 128
                        && name
                            .bytes()
                            .all(|ch| ch.is_ascii_alphanumeric() || b"_.-".contains(&ch))
                })
                .ok_or("Invalid display name")?;
            if !names.insert(name) {
                return Err("A display was listed twice".into());
            }
            let coordinate = |key: &str| {
                row[key]
                    .as_i64()
                    .filter(|n| (-32768..=32768).contains(n))
                    .map(|n| n as i32)
                    .ok_or("Invalid display position")
            };
            Ok((
                name,
                (coordinate("x")?, coordinate("y")?).into(),
                &row["original"],
            ))
        })
        .collect()
}

fn validate_geometry(rects: impl IntoIterator<Item = Rect>) -> Result<(), String> {
    let mut seen: Vec<Rect> = Vec::new();
    for rect in rects {
        if seen.iter().any(|other| other.overlaps(rect)) {
            return Err("Displays overlap; move their edges apart before applying".into());
        }
        seen.push(rect);
    }
    Ok(())
}

impl OrbitCompositor {
    pub(crate) fn output_arrangement(&mut self, value: &Value) -> Result<Value, String> {
        match value["command"].as_str() {
            Some("output_arrangement_begin") => {
                if self.native_system.output.is_none() {
                    return Err("Display arrangement requires the DRM session".into());
                }
                if self.native_system.pending_output.is_some()
                    || self.native_system.arrangement.is_some()
                {
                    return Err("A display preview is already active".into());
                }
                let requested = positions(&value["positions"])?;
                if requested.len() != self.space.outputs().count() {
                    return Err("The connected displays changed; refresh the arrangement".into());
                }
                let moves: Vec<Move> = requested
                    .iter()
                    .map(|(name, location, original)| {
                        let output = self
                            .space
                            .outputs()
                            .find(|output| output.name() == *name)
                            .ok_or("A display disconnected")?
                            .clone();
                        let old = self
                            .space
                            .output_geometry(&output)
                            .ok_or("A display has no geometry")?;
                        if [
                            ("x", old.loc.x),
                            ("y", old.loc.y),
                            ("width", old.size.w),
                            ("height", old.size.h),
                        ]
                        .iter()
                        .any(|(field, expected)| {
                            original[*field].as_i64() != Some(i64::from(*expected))
                        }) {
                            return Err("Display geometry changed; refresh the arrangement");
                        }
                        let new = Rectangle::new(*location, old.size);
                        Ok::<Move, &str>(Move { output, old, new })
                    })
                    .collect::<Result<_, _>>()?;
                validate_geometry(moves.iter().map(|change| change.new))?;
                if !moves.iter().any(|change| change.old != change.new) {
                    return Err("No display position changed".into());
                }
                let mut random = [0u8; 24];
                std::fs::File::open("/dev/urandom")
                    .and_then(|mut file| file.read_exact(&mut random))
                    .map_err(|error| error.to_string())?;
                let token: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
                let check_token = token.clone();
                let handle = self
                    .native_system
                    .loop_handle
                    .clone()
                    .ok_or("Display transaction event loop is unavailable")?;
                let duration = Duration::from_secs(15);
                let deadline = Instant::now() + duration;
                handle
                    .insert_source(
                        Timer::from_duration(Duration::from_millis(200)),
                        move |_, _, data| {
                            let active = data
                                .state
                                .native_system
                                .arrangement
                                .as_ref()
                                .is_some_and(|pending| pending.token == check_token);
                            if !active {
                                return TimeoutAction::Drop;
                            }
                            if data.state.reconcile_arrangement() {
                                TimeoutAction::ToDuration(Duration::from_millis(200))
                            } else {
                                TimeoutAction::Drop
                            }
                        },
                    )
                    .map_err(|error| error.to_string())?;
                self.apply_output_positions(&moves, false);
                self.native_system.arrangement = Some(Pending {
                    token: token.clone(),
                    deadline,
                    moves,
                });
                Ok(
                    json!({"ok":true,"token":token,"seconds":deadline.saturating_duration_since(Instant::now()).as_secs_f64()}),
                )
            }
            Some("output_arrangement_keep" | "output_arrangement_revert") => {
                let token = value["token"]
                    .as_str()
                    .ok_or("Missing display preview token")?;
                if !self.reconcile_arrangement() {
                    return if value["command"] == "output_arrangement_revert" {
                        Ok(json!({"ok":true}))
                    } else {
                        Err("The arrangement expired or a display disconnected".into())
                    };
                }
                let pending = self
                    .native_system
                    .arrangement
                    .as_ref()
                    .ok_or("Display preview ended")?;
                if pending.token != token {
                    return Err("Invalid display preview token".into());
                }
                let pending = self.native_system.arrangement.take().unwrap();
                if value["command"] == "output_arrangement_keep" {
                    if let Err(error) = persist(&pending) {
                        self.apply_output_positions(&pending.moves, true);
                        return Err(error);
                    }
                } else {
                    self.apply_output_positions(&pending.moves, true);
                }
                Ok(json!({"ok":true}))
            }
            _ => Err("Unsupported display arrangement command".into()),
        }
    }

    pub(crate) fn reconcile_arrangement(&mut self) -> bool {
        let Some(pending) = self.native_system.arrangement.as_ref() else {
            return false;
        };
        let valid = Instant::now() < pending.deadline
            && !self.protocols.is_locked()
            && pending.moves.len() == self.space.outputs().count()
            && pending
                .moves
                .iter()
                .all(|change| self.space.output_geometry(&change.output) == Some(change.new));
        if !valid {
            let pending = self.native_system.arrangement.take().unwrap();
            self.apply_output_positions(&pending.moves, true);
        }
        valid
    }

    pub(crate) fn arrangement_active(&self) -> bool {
        self.native_system.arrangement.is_some()
    }

    fn apply_output_positions(&mut self, moves: &[Move], revert: bool) {
        // All positions are validated against the same original snapshot; no
        // output request, DRM frame or client roundtrip is interleaved.
        let mut positions = Vec::new();
        for change in moves {
            let Some(current) = self.space.output_geometry(&change.output) else {
                continue;
            };
            let target = if revert {
                change.old.loc
            } else {
                change.new.loc
            };
            if current.loc != target {
                positions.push((change.output.clone(), current, target));
            }
        }
        let delta = |at: Position| {
            positions
                .iter()
                .find(|(_, old, _)| old.contains(at))
                .map(|(_, old, new)| *new - old.loc)
        };
        for (output, _, target) in &positions {
            output.change_current_state(None, None, None, Some(*target));
            self.space.map_output(output, *target);
            for space in &mut self.workspaces {
                space.map_output(output, *target);
            }
        }
        for space in std::iter::once(&mut self.space).chain(self.workspaces.iter_mut()) {
            let moved: Vec<_> = space
                .elements()
                .filter_map(|window| {
                    let loc = space.element_location(window)?;
                    Some((window.clone(), loc + delta(loc)?))
                })
                .collect();
            for (window, loc) in moved {
                space.map_element(window, loc, false);
            }
        }
        for geometry in self
            .normal_geometry
            .values_mut()
            .chain(self.xwayland.restore.values_mut())
        {
            if let Some(offset) = delta(geometry.loc) {
                geometry.loc += offset;
            }
        }
        for snap in self.snapped_windows.values_mut() {
            if let Some(offset) = delta(snap.restore.loc) {
                snap.restore.loc += offset;
            }
        }
        for (output, _, _) in &positions {
            self.protocols.output_changed(output);
            layer_map_for_output(output).arrange();
            self.reconfigure_output_windows(output);
        }
        self.request_redraw();
    }
}

fn persist(pending: &Pending) -> Result<(), String> {
    use std::{
        fs::{self, OpenOptions},
        io::Write,
        os::unix::fs::{MetadataExt, OpenOptionsExt},
    };
    let data = std::env::var_os("ORBIT_DATA")
        .map(std::path::PathBuf::from)
        .ok_or("No display preferences directory")?;
    let parent = fs::symlink_metadata(&data).map_err(|error| error.to_string())?;
    let owner = smithay::reexports::rustix::process::getuid().as_raw();
    if !parent.is_dir() || parent.uid() != owner || parent.mode() & 0o022 != 0 {
        return Err("Unsafe display preferences directory".into());
    }
    let path = data.join("outputs-native.json");
    let mut rows = match OpenOptions::new()
        .read(true)
        .custom_flags(
            (smithay::reexports::rustix::fs::OFlags::NOFOLLOW
                | smithay::reexports::rustix::fs::OFlags::NONBLOCK)
                .bits() as i32,
        )
        .open(&path)
    {
        Ok(file) => {
            let info = file.metadata().map_err(|error| error.to_string())?;
            if !info.is_file()
                || info.uid() != owner
                || info.len() > 65536
                || info.mode() & 0o022 != 0
            {
                return Err("Unsafe display preferences file".into());
            }
            let mut raw = Vec::new();
            file.take(65537)
                .read_to_end(&mut raw)
                .map_err(|error| error.to_string())?;
            if raw.len() > 65536 {
                return Err("Display preferences are too large".into());
            }
            serde_json::from_slice::<serde_json::Map<String, Value>>(&raw)
                .map_err(|error| error.to_string())?
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Default::default(),
        Err(error) => return Err(error.to_string()),
    };
    for change in &pending.moves {
        if change.old == change.new {
            continue;
        }
        let output = &change.output;
        let name = output.name();
        let mode = output
            .current_mode()
            .ok_or("A display has no current mode")?;
        rows.insert(name.clone(),json!({
            "name":name, "mode":format!("{}x{}@{:.3}Hz",mode.size.w,mode.size.h,mode.refresh as f64/1000.),
            "scale":output.current_scale().fractional_scale(),
            "transform":crate::native_system::transform_name(output.current_transform()),
            "x":change.new.loc.x,"y":change.new.loc.y
        }));
    }
    let mut bytes = serde_json::to_vec(&rows).map_err(|error| error.to_string())?;
    bytes.push(b'\n');
    if rows.len() > 32 || bytes.len() > 65536 {
        return Err("Display preferences are too large".into());
    }
    let temporary = data.join(format!(".output-arrangement-{}", pending.token));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&temporary)
        .map_err(|error| error.to_string())?;
    let result = file
        .write_all(&bytes)
        .and_then(|_| file.sync_all())
        .and_then(|_| fs::rename(&temporary, &path));
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn verifies_complete_typed_positions() {
        assert!(positions(
            &json!([{"name":"DP-1","x":-1080,"y":0},{"name":"HDMI-A-1","x":0,"y":8}])
        )
        .is_ok());
        assert!(
            positions(&json!([{"name":"DP-1","x":-1080,"y":0},{"name":"DP-1","x":0,"y":8}]))
                .is_err()
        );
        assert!(
            positions(&json!([{"name":"DP-1","x":0.5,"y":0},{"name":"DP-2","x":0,"y":8}])).is_err()
        );
    }
    #[test]
    fn accepts_adjacent_mixed_size_rectangles_but_not_overlap() {
        let portrait = Rect::new((-960, -180).into(), (960, 1280).into());
        let landscape = Rect::new((0, 0).into(), (1600, 900).into());
        assert!(validate_geometry([portrait, landscape]).is_ok());
        assert!(
            validate_geometry([Rect::new((-959, -180).into(), portrait.size), landscape]).is_err()
        );
    }
}
