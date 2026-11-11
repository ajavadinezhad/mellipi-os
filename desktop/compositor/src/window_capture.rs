//! On-demand readback of only the selected window's root surface and subsurfaces.
use smithay::{
    backend::{
        allocator::Fourcc,
        renderer::{
            element::{
                surface::{render_elements_from_surface_tree, WaylandSurfaceRenderElement},
                Kind,
            },
            gles::{GlesRenderbuffer, GlesRenderer},
            utils::draw_render_elements,
            Bind, Color32F, ExportMem, Frame, Offscreen, Renderer,
        },
    },
    desktop::Window,
    utils::{Buffer, Logical, Physical, Point, Rectangle, Size, Transform},
    wayland::seat::WaylandFocus,
};

pub struct WindowCapture {
    pub width: i32,
    pub height: i32,
    pub pixels: Vec<u8>,
}

pub fn capture(
    renderer: &mut GlesRenderer,
    window: &Window,
    scale: f64,
) -> Result<WindowCapture, String> {
    let geometry = window.geometry();
    let size: Size<i32, Physical> = geometry.size.to_physical_precise_round(scale);
    if size.w <= 0
        || size.h <= 0
        || size.w > 8192
        || size.h > 8192
        || i64::from(size.w) * i64::from(size.h) > 16_000_000
    {
        return Err("Window screenshot exceeds the supported size".into());
    }
    let surface = window
        .wl_surface()
        .ok_or("The selected window has no surface")?;
    let location = Point::<i32, Logical>::from((
        geometry.loc.x.saturating_neg(),
        geometry.loc.y.saturating_neg(),
    ))
    .to_physical_precise_round(scale);
    let elements: Vec<WaylandSurfaceRenderElement<GlesRenderer>> =
        render_elements_from_surface_tree(
            renderer,
            &surface,
            location,
            scale,
            1.,
            Kind::Unspecified,
        );
    if elements.is_empty() {
        return Err("The selected window has no image yet".into());
    }
    let fail = |error| format!("Could not capture the selected window: {error}");
    let buffer_size = Size::<i32, Buffer>::from((size.w, size.h));
    let mut buffer: GlesRenderbuffer = renderer
        .create_buffer(Fourcc::Argb8888, buffer_size)
        .map_err(fail)?;
    let mut target = renderer.bind(&mut buffer).map_err(fail)?;
    let damage = [Rectangle::from_size(size)];
    let mut frame = renderer
        .render(&mut target, size, Transform::Normal)
        .map_err(fail)?;
    frame.clear(Color32F::TRANSPARENT, &damage).map_err(fail)?;
    draw_render_elements(&mut frame, scale, &elements, &damage).map_err(fail)?;
    let sync = frame.finish().map_err(fail)?;
    renderer.wait(&sync).map_err(fail)?;
    let mapping = renderer
        .copy_framebuffer(&target, Rectangle::from_size(buffer_size), Fourcc::Argb8888)
        .map_err(fail)?;
    let pixels = renderer.map_texture(&mapping).map_err(fail)?;
    let bytes = (size.w as usize) * (size.h as usize) * 4;
    let pixels = pixels
        .get(..bytes)
        .ok_or("Incomplete window screenshot")?
        .to_vec();
    Ok(WindowCapture {
        width: size.w,
        height: size.h,
        pixels,
    })
}
