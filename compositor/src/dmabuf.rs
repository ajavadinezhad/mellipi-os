//! Advertise only renderer-supported formats and validate every client import.
use crate::OrbitCompositor;
use smithay::{
    backend::{
        allocator::{dmabuf::Dmabuf, Buffer, Format},
        renderer::{gles::GlesRenderer, ImportDma, Renderer},
    },
    delegate_dmabuf,
    wayland::dmabuf::{
        DmabufFeedbackBuilder, DmabufGlobal, DmabufHandler, DmabufState, ImportNotifier,
    },
};
pub struct NativeDmabuf {
    pub state: DmabufState,
    pub global: Option<DmabufGlobal>,
    pub import: Option<Box<dyn FnMut(&Dmabuf) -> bool>>,
}
impl Default for NativeDmabuf {
    fn default() -> Self {
        Self {
            state: DmabufState::new(),
            global: None,
            import: None,
        }
    }
}
impl OrbitCompositor {
    pub fn setup_dmabuf(
        &mut self,
        formats: Vec<Format>,
        device: Option<u64>,
        import: Box<dyn FnMut(&Dmabuf) -> bool>,
    ) {
        if formats.is_empty() {
            tracing::info!("Renderer has no client DMA-BUF texture formats; SHM remains available");
            return;
        }
        let global = if let Some(device) = device {
            match DmabufFeedbackBuilder::new(device as _, formats.clone()).build() {
                Ok(feedback) => self
                    .dmabuf
                    .state
                    .create_global_with_default_feedback::<Self>(&self.display_handle, &feedback),
                Err(error) => {
                    tracing::warn!(%error,"DMA-BUF feedback unavailable");
                    self.dmabuf
                        .state
                        .create_global::<Self>(&self.display_handle, formats)
                }
            }
        } else {
            self.dmabuf
                .state
                .create_global::<Self>(&self.display_handle, formats)
        };
        self.dmabuf.import = Some(import);
        self.dmabuf.global = Some(global);
    }
}
fn bounded_dimensions(width: i32, height: i32) -> bool {
    width > 0
        && height > 0
        && width <= 16384
        && height <= 16384
        && i64::from(width) * i64::from(height) <= 32_000_000
}
pub fn validate(renderer: &mut GlesRenderer, buffer: &Dmabuf) -> bool {
    let size = buffer.size();
    if !bounded_dimensions(size.w,size.h){return false;}
    // Clients may import/destroy buffers without ever attaching them to a
    // rendered frame. Retire weak-cache entries on each import as well.
    let _=renderer.cleanup_texture_cache();
    renderer.import_dmabuf(buffer, None).is_ok()
}
#[cfg(test)]
mod tests {
    #[test]
    fn import_size_is_bounded() {
        assert!(super::bounded_dimensions(3840, 2160));
        assert!(!super::bounded_dimensions(0, 100));
        assert!(!super::bounded_dimensions(-1, 100));
        assert!(!super::bounded_dimensions(16384, 16384));
    }
}
impl DmabufHandler for OrbitCompositor {
    fn dmabuf_state(&mut self) -> &mut DmabufState {
        &mut self.dmabuf.state
    }
    fn dmabuf_imported(&mut self, _: &DmabufGlobal, buffer: Dmabuf, notifier: ImportNotifier) {
        if self
            .dmabuf
            .import
            .as_mut()
            .is_some_and(|import| import(&buffer))
        {
            let _ = notifier.successful::<Self>();
        } else {
            notifier.failed();
        }
    }
}
delegate_dmabuf!(OrbitCompositor);

/// Feedback identifies the renderer's real device, never an invented device ID.
pub fn renderer_device(renderer: &GlesRenderer) -> Option<u64> {
    #[cfg(feature = "drm")]
    {
        smithay::backend::egl::EGLDevice::device_for_display(renderer.egl_context().display())
            .ok()
            .and_then(|device| device.try_get_render_node().ok().flatten())
            .map(|node| node.dev_id() as u64)
    }
    #[cfg(not(feature = "drm"))]
    {
        let _ = renderer;
        None
    }
}

/// Tiny nonexclusive render-node acceptance probe. No seat, KMS, output, input,
/// Wayland connection or physical display ownership is acquired.
#[cfg(feature = "drm")]
pub fn hardware_probe() -> serde_json::Value {
    use smithay::backend::allocator::dmabuf::AsDmabuf;
    use smithay::{
        backend::{
            allocator::{
                dmabuf::DmabufFlags,
                gbm::{GbmAllocator, GbmBufferFlags, GbmDevice},
                Allocator, Fourcc, Modifier,
            },
            egl::{EGLContext, EGLDisplay},
        },
        utils::DeviceFd,
    };
    let run = || -> Result<serde_json::Value, String> {
        let mut nodes: Vec<_> = std::fs::read_dir("/dev/dri")
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .filter(|entry| entry.file_name().to_string_lossy().starts_with("renderD"))
            .map(|entry| entry.path())
            .collect();
        nodes.sort();
        let path = nodes.first().ok_or("No nonexclusive DRM render node")?;
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .map_err(|e| e.to_string())?;
        let gbm = GbmDevice::new(DeviceFd::from(std::os::fd::OwnedFd::from(file)))
            .map_err(|e| e.to_string())?;
        // GBM remains alive until both EGL and GLES have been dropped.
        let display = unsafe { EGLDisplay::new(gbm.clone()) }.map_err(|e| e.to_string())?;
        let context = EGLContext::new(&display).map_err(|e| e.to_string())?;
        let mut renderer = unsafe { GlesRenderer::new(context) }.map_err(|e| e.to_string())?;
        let name = renderer
            .with_context(|gl| unsafe {
                let name = gl.GetString(0x1f01);
                if name.is_null() {
                    "unknown".to_owned()
                } else {
                    std::ffi::CStr::from_ptr(name.cast())
                        .to_string_lossy()
                        .into_owned()
                }
            })
            .map_err(|e| e.to_string())?;
        let formats = renderer.dmabuf_formats().iter().count();
        let mut allocator = GbmAllocator::new(gbm, GbmBufferFlags::RENDERING);
        let buffer = allocator
            .create_buffer(
                64,
                64,
                Fourcc::Argb8888,
                &[Modifier::Linear, Modifier::Invalid],
            )
            .map_err(|e| e.to_string())?;
        let dmabuf = buffer.export().map_err(|e| e.to_string())?;
        let imported = validate(&mut renderer, &dmabuf);
        let mut invalid = Dmabuf::builder(
            (64, 64),
            Fourcc::Argb8888,
            Modifier::Linear,
            DmabufFlags::empty(),
        );
        invalid.add_plane(
            std::fs::File::open("/dev/null")
                .map_err(|e| e.to_string())?
                .into(),
            0,
            0,
            256,
        );
        let rejected = invalid
            .build()
            .is_some_and(|invalid| !validate(&mut renderer, &invalid));
        Ok(
            serde_json::json!({"ok":imported && rejected,"device":path,"renderer":name,"supported_formats":formats,"imported":imported,"ordinary_fd_rejected":rejected,"size":[64,64],"physical_session_changed":false}),
        )
    };
    run().unwrap_or_else(
        |error| serde_json::json!({"ok":false,"error":error,"physical_session_changed":false}),
    )
}
