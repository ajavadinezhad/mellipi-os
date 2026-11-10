//! wlroots screencopy v2 SHM export; readback exists only for explicit requests.
//! Only SHM capture is exposed; DMA-BUF client import is a separate capability.
//! Keep the capture manager at v2 until DMA-BUF capture export is implemented.
use crate::{protocols::NativeProtocols, OrbitCompositor};
use smithay::{
    backend::{
        allocator::Fourcc,
        renderer::{gles::GlesRenderer, ExportMem, RendererSuper},
    },
    output::Output,
    reexports::{
        wayland_protocols_wlr::screencopy::v1::server::{
            zwlr_screencopy_frame_v1 as frame, zwlr_screencopy_manager_v1 as manager,
        },
        wayland_server::{
            protocol::{wl_buffer::WlBuffer, wl_shm},
            Client, DataInit, Dispatch, DisplayHandle, GlobalDispatch, New, Resource,
        },
    },
    utils::{Buffer, Rectangle, Size, Transform},
    wayland::shm::with_buffer_contents_mut,
};
use std::sync::{Arc, Mutex};
const MAX_PENDING: usize = 8;
const MAX_PIXELS: u64 = 16_777_216;
#[derive(Clone)]
pub struct CaptureData {
    output: Option<Output>,
    region: Rectangle<i32, Buffer>,
    used: Arc<Mutex<bool>>,
}
pub(crate) struct PendingCapture {
    pub output: Output,
    pub frame: frame::ZwlrScreencopyFrameV1,
    region: Rectangle<i32, Buffer>,
    buffer: WlBuffer,
    damage: bool,
}
pub fn register(display: &DisplayHandle) {
    display.create_global::<OrbitCompositor, manager::ZwlrScreencopyManagerV1, _>(2, ());
}
fn prepare(
    state: &OrbitCompositor,
    output: Option<Output>,
    requested: Option<(i32, i32, i32, i32)>,
) -> CaptureData {
    let unavailable = || CaptureData {
        output: None,
        region: Rectangle::from_size((0, 0).into()),
        used: Arc::new(Mutex::new(false)),
    };
    if state.protocols.is_locked() {
        return unavailable();
    }
    let Some(output) = output else {
        return unavailable();
    };
    let Some(mode) = output.current_mode() else {
        return unavailable();
    };
    let Some(region) = capture_region(
        Size::from((mode.size.w, mode.size.h)),
        output.current_transform(),
        output.current_scale().fractional_scale(),
        requested,
    ) else {
        return unavailable();
    };
    CaptureData {
        output: Some(output),
        region,
        used: Arc::new(Mutex::new(false)),
    }
}
/// The protocol exports native-output pixels; clients (including grim) apply
/// wl_output.transform. Transform only the logical crop, never double-rotate
/// the returned pixels. Smithay's GLES projection already accounts for Y.
fn capture_region(
    size: Size<i32, Buffer>,
    transform: Transform,
    scale: f64,
    requested: Option<(i32, i32, i32, i32)>,
) -> Option<Rectangle<i32, Buffer>> {
    if size.w <= 0 || size.h <= 0 || !scale.is_finite() || scale <= 0.0 {
        return None;
    }
    if requested.is_none() {
        return if size.w as u64 * size.h as u64 <= MAX_PIXELS {
            Some(Rectangle::from_size(size))
        } else {
            None
        };
    }
    let (x, y, w, h) = requested?;
    if w <= 0 || h <= 0 {
        return None;
    }
    let logical_size = transform.transform_size(size);
    let x1 = (x as f64 * scale)
        .round()
        .max(0.0)
        .min(logical_size.w as f64) as i32;
    let y1 = (y as f64 * scale)
        .round()
        .max(0.0)
        .min(logical_size.h as f64) as i32;
    let x2 = ((x as i64 + w as i64) as f64 * scale)
        .round()
        .max(0.0)
        .min(logical_size.w as f64) as i32;
    let y2 = ((y as i64 + h as i64) as f64 * scale)
        .round()
        .max(0.0)
        .min(logical_size.h as f64) as i32;
    if x2 <= x1 || y2 <= y1 || (x2 - x1) as u64 * (y2 - y1) as u64 > MAX_PIXELS {
        return None;
    }
    // Reflections are self-inverse; only pure quarter turns swap direction.
    let inverse = match transform {
        Transform::_90 => Transform::_270,
        Transform::_270 => Transform::_90,
        other => other,
    };
    Some(inverse.transform_rect_in(
        Rectangle::new((x1, y1).into(), (x2 - x1, y2 - y1).into()),
        &logical_size,
    ))
}
impl GlobalDispatch<manager::ZwlrScreencopyManagerV1, ()> for OrbitCompositor {
    fn bind(
        _state: &mut Self,
        _display: &DisplayHandle,
        _client: &Client,
        resource: New<manager::ZwlrScreencopyManagerV1>,
        _data: &(),
        init: &mut DataInit<'_, Self>,
    ) {
        init.init(resource, ());
    }
}
impl Dispatch<manager::ZwlrScreencopyManagerV1, ()> for OrbitCompositor {
    fn request(
        state: &mut Self,
        _client: &Client,
        _manager: &manager::ZwlrScreencopyManagerV1,
        request: manager::Request,
        _data: &(),
        _display: &DisplayHandle,
        init: &mut DataInit<'_, Self>,
    ) {
        let (id, data) = match request {
            manager::Request::CaptureOutput { frame, output, .. } => {
                (frame, prepare(state, Output::from_resource(&output), None))
            }
            manager::Request::CaptureOutputRegion {
                frame,
                output,
                x,
                y,
                width,
                height,
                ..
            } => (
                frame,
                prepare(
                    state,
                    Output::from_resource(&output),
                    Some((x, y, width, height)),
                ),
            ),
            manager::Request::Destroy => return,
            _ => return,
        };
        let frame = init.init(id, data.clone());
        if data.output.is_none() {
            frame.failed();
            return;
        }
        frame.buffer(
            wl_shm::Format::Argb8888,
            data.region.size.w as u32,
            data.region.size.h as u32,
            data.region.size.w as u32 * 4,
        );
        if frame.version() >= 3 {
            frame.buffer_done();
        }
    }
}
impl Dispatch<frame::ZwlrScreencopyFrameV1, CaptureData> for OrbitCompositor {
    fn request(
        state: &mut Self,
        _client: &Client,
        resource: &frame::ZwlrScreencopyFrameV1,
        request: frame::Request,
        data: &CaptureData,
        _display: &DisplayHandle,
        _init: &mut DataInit<'_, Self>,
    ) {
        let (buffer, damage) = match request {
            frame::Request::Copy { buffer } => (buffer, false),
            frame::Request::CopyWithDamage { buffer } => (buffer, true),
            frame::Request::Destroy => return,
            _ => return,
        };
        let mut used = data.used.lock().unwrap();
        if *used {
            resource.post_error(
                frame::Error::AlreadyUsed,
                "A screencopy frame can only be copied once",
            );
            return;
        }
        *used = true;
        let Some(output) = &data.output else {
            resource.failed();
            return;
        };
        if state.protocols.is_locked() || state.protocols.captures.len() >= MAX_PENDING {
            resource.failed();
            return;
        }
        let valid = with_buffer_contents_mut(&buffer, |_, len, metadata| {
            metadata.format == wl_shm::Format::Argb8888
                && metadata.width == data.region.size.w
                && metadata.height == data.region.size.h
                && metadata.stride == metadata.width.saturating_mul(4)
                && metadata.offset >= 0
                && (metadata.offset as usize)
                    .checked_add(metadata.stride.max(0) as usize * metadata.height.max(0) as usize)
                    .map(|end| end <= len)
                    .unwrap_or(false)
        })
        .unwrap_or(false);
        if !valid {
            resource.post_error(
                frame::Error::InvalidBuffer,
                "Expected exactly the advertised ARGB8888 SHM buffer",
            );
            return;
        }
        state.protocols.captures.push(PendingCapture {
            output: output.clone(),
            frame: resource.clone(),
            region: data.region,
            buffer,
            damage,
        });
        state.request_redraw();
    }
}
impl NativeProtocols {
    pub fn capture_pending(&self, output: &Output) -> bool {
        self.captures
            .iter()
            .any(|capture| &capture.output == output)
    }
    /// Call after output rendering, before framebuffer submission/release.
    pub fn capture_output(
        &mut self,
        output: &Output,
        renderer: &mut GlesRenderer,
        framebuffer: &<GlesRenderer as RendererSuper>::Framebuffer<'_>,
    ) {
        let captures = std::mem::take(&mut self.captures);
        for capture in captures {
            if &capture.output != output {
                self.captures.push(capture);
                continue;
            }
            if self.is_locked() || !capture.frame.is_alive() || !capture.buffer.is_alive() {
                if capture.frame.is_alive() {
                    capture.frame.failed();
                }
                continue;
            }
            let Ok(mapping) = renderer.copy_framebuffer(
                framebuffer,
                {
                    let Some(mode) = output.current_mode() else {
                        capture.frame.failed();
                        continue;
                    };
                    if capture.region.loc.x < 0
                        || capture.region.loc.y < 0
                        || capture.region.loc.x + capture.region.size.w > mode.size.w
                        || capture.region.loc.y + capture.region.size.h > mode.size.h
                    {
                        capture.frame.failed();
                        continue;
                    }
                    Rectangle::new(
                        (capture.region.loc.x, capture.region.loc.y).into(),
                        capture.region.size,
                    )
                },
                Fourcc::Argb8888,
            ) else {
                capture.frame.failed();
                continue;
            };
            let Ok(bytes) = renderer.map_texture(&mapping) else {
                capture.frame.failed();
                continue;
            };
            let expected = capture.region.size.w as usize * capture.region.size.h as usize * 4;
            if bytes.len() < expected {
                capture.frame.failed();
                continue;
            }
            let copied = with_buffer_contents_mut(&capture.buffer, |ptr, len, metadata| {
                let start = metadata.offset.max(0) as usize;
                let Some(end) = start.checked_add(expected) else {
                    return false;
                };
                if end > len {
                    return false;
                }
                // The SHM helper catches client SIGBUS, and metadata was checked
                // against advertised dimensions before this bounded raw copy.
                unsafe {
                    std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr.add(start), expected);
                }
                true
            })
            .unwrap_or(false);
            if !copied {
                capture.frame.failed();
                continue;
            }
            // Smithay's GLES projection already accounts for GL's Y axis.
            // ReadPixels rows are native scanout rows, which the client then
            // transforms using wl_output.transform. TextureMapping::flipped
            // describes texture coordinates and would invert this twice.
            capture.frame.flags(frame::Flags::empty());
            if capture.damage && capture.frame.version() >= 2 {
                capture.frame.damage(
                    0,
                    0,
                    capture.region.size.w as u32,
                    capture.region.size.h as u32,
                );
            }
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default();
            let seconds = now.as_secs();
            capture
                .frame
                .ready((seconds >> 32) as u32, seconds as u32, now.subsec_nanos());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn native_crop_coordinates_for_every_rotation_and_flip() {
        let cases = [
            (Transform::Normal, (1, 1, 2, 1)),
            (Transform::_90, (1, 1, 1, 2)),
            (Transform::_180, (3, 2, 2, 1)),
            (Transform::_270, (4, 1, 1, 2)),
            (Transform::Flipped, (3, 1, 2, 1)),
            (Transform::Flipped90, (4, 1, 1, 2)),
            (Transform::Flipped180, (1, 2, 2, 1)),
            (Transform::Flipped270, (1, 1, 1, 2)),
        ];
        for (transform, (x, y, w, h)) in cases {
            let crop = capture_region((6, 4).into(), transform, 1.0, Some((1, 1, 2, 1))).unwrap();
            assert_eq!(
                crop,
                Rectangle::new((x, y).into(), (w, h).into()),
                "{transform:?}"
            );
            assert_eq!(
                capture_region((6, 4).into(), transform, 1.0, None),
                Some(Rectangle::from_size((6, 4).into()))
            );
        }
    }
    #[test]
    fn crops_clip_negative_edges_and_reject_empty_or_excessive_images() {
        assert_eq!(
            capture_region((6, 4).into(), Transform::Normal, 1., Some((-2, -1, 4, 3))),
            Some(Rectangle::new((0, 0).into(), (2, 2).into()))
        );
        assert!(capture_region((6, 4).into(), Transform::Normal, 1., Some((9, 1, 2, 2))).is_none());
        assert!(capture_region((6, 4).into(), Transform::Normal, f64::NAN, None).is_none());
        assert!(capture_region((100000, 100000).into(), Transform::Normal, 1., None).is_none());
    }
}
