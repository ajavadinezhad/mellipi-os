//! Small compositor-owned headers for legacy X11 clients only. They share the
//! live window transform and damage pass; no overlay process/tracking timer.
use smithay::{
    backend::{
        allocator::Fourcc,
        renderer::{
            element::{
                memory::{MemoryRenderBuffer, MemoryRenderBufferRenderElement},
                Kind,
            },
            gles::GlesRenderer,
        },
    },
    desktop::{layer_map_for_output, Window},
    utils::{Logical, Physical, Point, Rectangle, Transform, SERIAL_COUNTER},
    wayland::shell::wlr_layer::Layer,
};
use std::{
    cell::RefCell,
    collections::HashMap,
    ffi::{c_char, c_double, c_void, CString},
};
pub const HEIGHT: i32 = 28;
const BUDGET: usize = 4 * 1024 * 1024;
struct Cached {
    key: (String, i32, i32, bool),
    buffer: MemoryRenderBuffer,
    bytes: usize,
    age: u64,
}
struct Frames {
    mode: String,
    accent: [f64; 3],
    palette: Option<HeaderPalette>,
    outline: bool,
    cache: HashMap<u64, Cached>,
    age: u64,
}
#[derive(Clone, Copy, Debug, PartialEq)]
struct HeaderPalette {
    background: [f64; 3],
    surface: [f64; 3],
    text: [f64; 3],
    muted: [f64; 3],
    border: [f64; 3],
}
thread_local! {static FRAMES:RefCell<Frames>=RefCell::new(Frames{mode:"black".into(),accent:[0.89,0.58,0.47],palette:None,outline:true,cache:HashMap::new(),age:0});}
fn parse_color(value: &str) -> Result<[f64; 3], String> {
    if value.len() != 7 || !value.is_ascii() || !value.starts_with('#') {
        return Err("Invalid frame color".into());
    }
    let mut color = [0.; 3];
    for (i, channel) in color.iter_mut().enumerate() {
        *channel = u8::from_str_radix(&value[1+i*2..3+i*2],16)
            .map_err(|_| "Invalid frame color")? as f64 / 255.;
    }
    Ok(color)
}
fn parse_palette(value: Option<&serde_json::Value>) -> Result<Option<HeaderPalette>, String> {
    let Some(value) = value.filter(|value| !value.is_null()) else { return Ok(None); };
    let object = value.as_object().ok_or("Expected frame palette object")?;
    if object.is_empty() { return Ok(None); }
    const KEYS: [&str; 8] = ["background","surface","raised","hover","border","text","muted","faint"];
    if object.len() != KEYS.len() || object.keys().any(|key| !KEYS.contains(&key.as_str())) {
        return Err("Expected complete frame theme palette".into());
    }
    // Validate every accepted field, including those not drawn by headers.
    // A palette is one atomic update: malformed colors never partially apply.
    for key in KEYS {
        parse_color(object.get(key).and_then(|color|color.as_str()).ok_or("Invalid frame palette color")?)?;
    }
    let color = |key| parse_color(object[key].as_str().unwrap());
    Ok(Some(HeaderPalette {background:color("background")?,surface:color("surface")?,
        text:color("text")?,muted:color("muted")?,border:color("border")?}))
}
pub fn set_theme(mode: &str, accent: &str) -> Result<(), String> {
    set_theme_palette(mode,accent,None)
}
pub fn set_theme_palette(mode: &str, accent: &str, palette: Option<&serde_json::Value>) -> Result<(), String> {
    if !["black", "dark", "light"].contains(&mode) {
        return Err("Invalid frame theme".into());
    }
    let color = parse_color(accent)?;
    let palette = parse_palette(palette)?;
    FRAMES.with(|frames| {
        let mut f = frames.borrow_mut();
        f.mode = mode.into();
        f.accent = color;
        f.palette = palette;
        f.cache.clear();
    });
    Ok(())
}
pub fn outline_setting(value: Option<&serde_json::Value>) -> Result<bool,String> {
    match value {None=>Ok(true),Some(value)=>value.as_bool().ok_or_else(||"Expected outline boolean".into())}
}
pub fn set_outline(enabled: bool) {FRAMES.with(|frames|frames.borrow_mut().outline=enabled);}
pub fn needs_header(window: &Window) -> bool {
    window
        .x11_surface()
        .is_some_and(|s| !s.is_override_redirect() && !s.is_decorated() && !s.is_fullscreen())
}
pub fn client_area(window: &Window, mut area: Rectangle<i32, Logical>) -> Rectangle<i32, Logical> {
    if needs_header(window) && area.size.h > HEIGHT {
        area.loc.y += HEIGHT;
        area.size.h -= HEIGHT;
    }
    area
}
// Four unique 1px buffers per window share its lifetime. Stretching strips
// avoids any window-sized border image, extra surface, or motion tracker.
#[derive(Default)]
struct OutlinePixels {
    color: Option<[u8; 4]>,
    buffers: Vec<MemoryRenderBuffer>,
}
impl OutlinePixels {
    fn update(&mut self, color: [u8; 4]) {
        if self.color == Some(color) { return; }
        self.color = Some(color);
        self.buffers = (0..4).map(|_|MemoryRenderBuffer::from_slice(
            &color,Fourcc::Argb8888,(1,1),1,Transform::Normal,None)).collect();
    }
}
fn outline_rects(mut geometry: Rectangle<i32, Logical>, header: bool, inset: bool) -> Vec<Rectangle<i32, Logical>> {
    if geometry.size.w <= 0 || geometry.size.h <= 0 || geometry.size.w > 16384 || geometry.size.h > 16384 { return vec![]; }
    if header {geometry.loc.y=geometry.loc.y.saturating_sub(HEIGHT);geometry.size.h=geometry.size.h.saturating_add(HEIGHT);}
    let (x,y,w,h)=(geometry.loc.x,geometry.loc.y,geometry.size.w,geometry.size.h);
    if inset {
        return [
            Rectangle::new((x, y).into(), (w, 1).into()),
            Rectangle::new((x, y.saturating_add(h - 1)).into(), (w, 1).into()),
            Rectangle::new((x, y).into(), (1, h).into()),
            Rectangle::new((x.saturating_add(w - 1), y).into(), (1, h).into()),
        ].into();
    }
    [Rectangle::new((x.saturating_sub(1),y.saturating_sub(1)).into(),(w+2,1).into()),
        Rectangle::new((x.saturating_sub(1),y.saturating_add(h)).into(),(w+2,1).into()),
        Rectangle::new((x.saturating_sub(1),y).into(),(1,h).into()),
        Rectangle::new((x.saturating_add(w),y).into(),(1,h).into())]
        .into_iter().filter(|rect|rect.size.w>0 && rect.size.h>0).collect()
}
fn outline_active(window: &Window) -> Option<bool> {
    if let Some(surface)=window.x11_surface() {
        if surface.is_override_redirect() || surface.is_fullscreen() {return None;}
        return Some(surface.is_activated());
    }
    let surface=window.toplevel()?;
    let own_chrome=smithay::wayland::compositor::with_states(surface.wl_surface(),|states|{
        states.data_map.get::<smithay::wayland::shell::xdg::XdgToplevelSurfaceData>()
            .is_some_and(|data|data.lock().unwrap().app_id.as_deref()==Some("orbit-settings"))
    });
    if own_chrome {return None;}
    let state=surface.current_state();
    use smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State;
    if state.states.contains(State::Fullscreen) {return None;}
    Some(state.states.contains(State::Activated))
}
fn outline_color(active: bool) -> [u8;4] {
    FRAMES.with(|frames|{
        let f=frames.borrow();
        let rgb=if active {f.accent} else if let Some(palette)=f.palette {palette.border} else if f.mode=="light" {[0.76,0.78,0.80]} else {[0.22,0.25,0.28]};
        [(rgb[2]*255.).round() as u8,(rgb[1]*255.).round() as u8,(rgb[0]*255.).round() as u8,255]
    })
}
fn outline_elements(renderer: &mut GlesRenderer,window: &Window,body: Point<i32, Physical>,scale: f64,alpha:f32) -> Vec<MemoryRenderBufferRenderElement<GlesRenderer>> {
    if !FRAMES.with(|frames|frames.borrow().outline) {return vec![];}
    let Some(active)=outline_active(window) else {return vec![];};
    use smithay::reexports::wayland_protocols::xdg::shell::server::xdg_toplevel::State;
    let maximized = window.x11_surface().is_some_and(|surface| surface.is_maximized())
        || window.toplevel().is_some_and(|surface| surface.current_state().states.contains(State::Maximized));
    let rects=outline_rects(window.geometry(),needs_header(window),maximized);
    if rects.is_empty() {return vec![];}
    let color=outline_color(active);
    window.user_data().insert_if_missing(||RefCell::new(OutlinePixels::default()));
    let mut pixels=window.user_data().get::<RefCell<OutlinePixels>>().unwrap().borrow_mut();
    pixels.update(color);
    rects.into_iter().zip(&pixels.buffers).filter_map(|(rect,buffer)|{
        MemoryRenderBufferRenderElement::from_buffer(renderer,
            (body.x as f64+rect.loc.x as f64*scale,body.y as f64+rect.loc.y as f64*scale),buffer,Some(alpha),
            Some(Rectangle::from_size((1.,1.).into())),Some(rect.size),Kind::Unspecified).ok()
    }).collect()
}
pub fn elements(
    renderer: &mut GlesRenderer,
    window: &Window,
    body: Point<i32, Physical>,
    scale: f64,
) -> Vec<MemoryRenderBufferRenderElement<GlesRenderer>> {
    elements_with_alpha(renderer,window,body,scale,1.)
}
pub fn elements_with_alpha(renderer:&mut GlesRenderer,window:&Window,body:Point<i32,Physical>,scale:f64,alpha:f32)->Vec<MemoryRenderBufferRenderElement<GlesRenderer>> {
    let mut rendered=outline_elements(renderer,window,body,scale,alpha);
    if !needs_header(window) {
        return rendered;
    }
    let Some(surface) = window.x11_surface() else {
        return rendered;
    };
    let width = window.geometry().size.w.clamp(1, 8192);
    let raster = (scale.ceil() as i32).clamp(1, 2);
    let id = surface.window_id() as u64;
    let title = surface.title().chars().take(160).collect::<String>();
    let active = surface.is_activated();
    let buffer = FRAMES.with(|frames| {
        let mut f = frames.borrow_mut();
        f.age += 1;
        let age = f.age;
        let key = (title.clone(), width, raster, active);
        if let Some(cached) = f.cache.get_mut(&id) {
            if cached.key == key {
                cached.age = age;
                return Some(cached.buffer.clone());
            }
        }
        let bytes = (width * raster * HEIGHT * raster * 4) as usize;
        if bytes > BUDGET {
            return None;
        }
        let pixels = paint(width, raster, &title, &f.mode, f.accent, f.palette.as_ref(), active)?;
        while !f.cache.is_empty()
            && (f.cache.len() >= 32
                || f.cache.values().map(|r| r.bytes).sum::<usize>() + bytes > BUDGET)
        {
            let oldest = *f.cache.iter().min_by_key(|(_, r)| r.age).unwrap().0;
            f.cache.remove(&oldest);
        }
        let buffer = MemoryRenderBuffer::from_slice(
            &pixels,
            Fourcc::Argb8888,
            (width * raster, HEIGHT * raster),
            raster,
            Transform::Normal,
            None,
        );
        f.cache.insert(
            id,
            Cached {
                key,
                buffer: buffer.clone(),
                bytes,
                age,
            },
        );
        Some(buffer)
    });
    rendered.extend(buffer
        .and_then(|b| {
            MemoryRenderBufferRenderElement::from_buffer(
                renderer,
                (body.x as f64, body.y as f64 - HEIGHT as f64 * scale),
                &b,
                Some(alpha),
                None,
                None,
                Kind::Unspecified,
            )
            .ok()
        })
        .into_iter());
    rendered
}

#[link(name = "cairo")]
unsafe extern "C" {
    fn cairo_image_surface_create_for_data(
        data: *mut u8,
        format: i32,
        width: i32,
        height: i32,
        stride: i32,
    ) -> *mut c_void;
    fn cairo_surface_status(surface: *mut c_void) -> i32;
    fn cairo_surface_destroy(surface: *mut c_void);
    fn cairo_surface_flush(surface: *mut c_void);
    fn cairo_create(surface: *mut c_void) -> *mut c_void;
    fn cairo_destroy(context: *mut c_void);
    fn cairo_scale(c: *mut c_void, x: c_double, y: c_double);
    fn cairo_set_source_rgb(c: *mut c_void, r: c_double, g: c_double, b: c_double);
    fn cairo_paint(c: *mut c_void);
    fn cairo_set_line_width(c: *mut c_void, width: c_double);
    fn cairo_move_to(c: *mut c_void, x: c_double, y: c_double);
    fn cairo_line_to(c: *mut c_void, x: c_double, y: c_double);
    fn cairo_stroke(c: *mut c_void);
    fn cairo_rectangle(c: *mut c_void, x: c_double, y: c_double, w: c_double, h: c_double);
    fn cairo_clip(c: *mut c_void);
    fn cairo_save(c: *mut c_void);
    fn cairo_restore(c: *mut c_void);
    fn cairo_select_font_face(c: *mut c_void, family: *const c_char, slant: i32, weight: i32);
    fn cairo_set_font_size(c: *mut c_void, size: c_double);
    fn cairo_show_text(c: *mut c_void, text: *const c_char);
}
fn paint(
    width: i32,
    raster: i32,
    title: &str,
    mode: &str,
    accent: [f64; 3],
    palette: Option<&HeaderPalette>,
    active: bool,
) -> Option<Vec<u8>> {
    let mut bytes = vec![0; (width * raster * HEIGHT * raster * 4) as usize];
    unsafe {
        let surface = cairo_image_surface_create_for_data(
            bytes.as_mut_ptr(),
            0,
            width * raster,
            HEIGHT * raster,
            width * raster * 4,
        );
        if surface.is_null() {
            return None;
        }
        if cairo_surface_status(surface) != 0 {
            cairo_surface_destroy(surface);
            return None;
        }
        let c = cairo_create(surface);
        cairo_scale(c, raster as f64, raster as f64);
        let light = mode == "light";
        let bg = if let Some(palette) = palette {
            if active {palette.surface} else {palette.background}
        } else if light {
            [0.95, 0.96, 0.97]
        } else if mode == "black" {
            [0.035, 0.043, 0.055]
        } else {
            [0.10, 0.12, 0.14]
        };
        cairo_set_source_rgb(c, bg[0], bg[1], bg[2]);
        cairo_paint(c);
        let fg = if let Some(palette) = palette {
            if active {palette.text} else {palette.muted}
        } else if light {
            [0.13, 0.16, 0.19]
        } else {
            [0.88, 0.91, 0.94]
        };
        cairo_set_source_rgb(c, fg[0], fg[1], fg[2]);
        cairo_save(c);
        cairo_rectangle(c, 10., 2., (width - 116).max(0) as f64, 24.);
        cairo_clip(c);
        let font = CString::new("sans").unwrap();
        cairo_select_font_face(c, font.as_ptr(), 0, 0);
        cairo_set_font_size(c, 12.);
        cairo_move_to(c, 10., 18.);
        let clean = title.replace('\0', "");
        let text = CString::new(clean).ok()?;
        cairo_show_text(c, text.as_ptr());
        cairo_restore(c);
        cairo_set_line_width(c, 1.3);
        let w = width as f64;
        // Minimize, maximize and close have equally sized 32px targets.
        cairo_move_to(c, w - 86., 19.);
        cairo_line_to(c, w - 76., 19.);
        cairo_stroke(c);
        cairo_rectangle(c, w - 54., 9., 9., 9.);
        cairo_stroke(c);
        cairo_move_to(c, w - 22., 9.);
        cairo_line_to(c, w - 13., 18.);
        cairo_move_to(c, w - 13., 9.);
        cairo_line_to(c, w - 22., 18.);
        cairo_stroke(c);
        let line = if active {
            accent
        } else if let Some(palette) = palette {
            palette.border
        } else if light {
            [0.76, 0.78, 0.80]
        } else {
            [0.22, 0.25, 0.28]
        };
        cairo_set_source_rgb(c, line[0], line[1], line[2]);
        cairo_set_line_width(c, 1.);
        cairo_move_to(c, 0., 27.5);
        cairo_line_to(c, w, 27.5);
        cairo_stroke(c);
        cairo_destroy(c);
        cairo_surface_flush(surface);
        cairo_surface_destroy(surface);
    }
    Some(bytes)
}
impl crate::OrbitCompositor {
    pub fn header_at(&self, pos: Point<f64, Logical>) -> Option<(u64, Window, i32)> {
        if self.protocols.is_locked() || self.transition.is_some() {
            return None;
        }
        for output in self.space.outputs() {
            let map = layer_map_for_output(output);
            let origin = self.space.output_geometry(output)?.loc;
            let local = pos - origin.to_f64();
            for level in [Layer::Overlay, Layer::Top] {
                if let Some(layer) = map.layer_under(level, local) {
                    if let Some(geo) = map.layer_geometry(layer) {
                        if layer
                            .surface_under(
                                local - geo.loc.to_f64(),
                                smithay::desktop::WindowSurfaceType::ALL,
                            )
                            .is_some()
                        {
                            return None;
                        }
                    }
                }
            }
        }
        for window in self.space.elements().rev() {
            let Some(loc) = self.space.element_location(window) else {
                continue;
            };
            let rect = Rectangle::new(
                (loc.x, loc.y - HEIGHT).into(),
                (window.geometry().size.w, HEIGHT).into(),
            );
            if needs_header(window) && rect.to_f64().contains(pos) {
                let id = self.windows.iter().find(|(_, w)| w == window)?.0;
                return Some((id, window.clone(), (pos.x - loc.x as f64) as i32));
            }
            if window
                .surface_under(pos - loc.to_f64(), smithay::desktop::WindowSurfaceType::ALL)
                .is_some()
            {
                return None;
            }
        }
        None
    }
    pub fn header_pressed(&mut self, id: u64, window: Window, x: i32) {
        let Some(surface) = window.x11_surface().cloned() else {
            return;
        };
        let width = window.geometry().size.w;
        self.space.raise_element(&window, true);
        if let Some(focus) = surface.wl_surface() {
            self.seat.get_keyboard().unwrap().set_focus(
                self,
                Some(focus),
                SERIAL_COUNTER.next_serial(),
            );
        }
        if !surface.is_maximized() && x < 4 {
            self.begin_x11_grab(
                surface,
                1,
                Some(smithay::xwayland::xwm::ResizeEdge::TopLeft),
            );
        } else if !surface.is_maximized() && x >= width - 4 {
            self.begin_x11_grab(
                surface,
                1,
                Some(smithay::xwayland::xwm::ResizeEdge::TopRight),
            );
        } else if x >= width - 32 {
            let _ = surface.close();
        } else if x >= width - 64 {
            self.maximize_x11(&surface, !surface.is_maximized(), false);
        } else if x >= width - 96 {
            self.minimize_window(id);
        } else {
            self.begin_x11_grab(surface, 1, None);
        }
        self.request_redraw();
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn header_budget_theme_and_pixels() {
        assert!(set_theme("black", "#aabbcc").is_ok());
        assert!(set_theme("x", "#aabbcc").is_err());
        for mode in ["black", "dark", "light"] {
            let image = paint(400, 2, "A UTF-8 title — Orbit", mode, [1., 0., 0.], None, true).unwrap();
            assert_eq!(image.len(), 400 * 2 * HEIGHT as usize * 2 * 4);
            assert!(image.chunks_exact(4).all(|p| p[3] == 255));
        }
    }
    fn pixel(bytes: &[u8], width: usize, x: usize, y: usize) -> [u8; 4] {
        let i = (y*width+x)*4;
        [bytes[i+2],bytes[i+1],bytes[i],bytes[i+3]]
    }
    #[test]
    fn five_palettes_render_exact_header_surfaces_and_borders() {
        for source in [include_str!("../../themes/midnight.json"),include_str!("../../themes/dune.json"),
            include_str!("../../themes/forest.json"),include_str!("../../themes/glacier.json"),include_str!("../../themes/ember.json")] {
            let theme: serde_json::Value = serde_json::from_str(source).unwrap();
            let palette = parse_palette(Some(&theme["palette"])).unwrap().unwrap();
            let accent = parse_color(theme["accent"].as_str().unwrap()).unwrap();
            let mode = theme["mode"].as_str().unwrap();
            for active in [false,true] {
                let bytes = paint(400,1,"Orbit",mode,accent,Some(&palette),active).unwrap();
                let expected = if active {palette.surface} else {palette.background};
                let rgb = expected.map(|v|(v*255.).round() as u8);
                assert_eq!(pixel(&bytes,400,1,1),[rgb[0],rgb[1],rgb[2],255]);
                let expected = if active {accent} else {palette.border};
                let rgb = expected.map(|v|(v*255.).round() as u8);
                assert_eq!(pixel(&bytes,400,1,27),[rgb[0],rgb[1],rgb[2],255]);
                assert!(bytes.chunks_exact(4).all(|p|p[3]==255));
            }
        }
    }
    #[test]
    fn palette_updates_validate_atomically_and_legacy_requests_reset() {
        let theme: serde_json::Value = serde_json::from_str(include_str!("../../themes/forest.json")).unwrap();
        set_theme_palette("dark","#b8d893",Some(&theme["palette"])).unwrap();
        let expected = FRAMES.with(|frames|frames.borrow().palette);
        for invalid in [serde_json::json!({"surface":"#ffffff"}),serde_json::json!([]),serde_json::json!(true)] {
            assert!(set_theme_palette("light","#ffffff",Some(&invalid)).is_err());
            assert_eq!(FRAMES.with(|frames|frames.borrow().palette),expected);
            assert_eq!(FRAMES.with(|frames|frames.borrow().mode.clone()),"dark");
        }
        for field in ["background","surface","raised","hover","border","text","muted","faint"] {
            let mut invalid=theme["palette"].clone();invalid[field]=serde_json::json!("#nonhex");
            assert!(set_theme_palette("dark","#ffffff",Some(&invalid)).is_err());
        }
        assert!(set_theme_palette("dark","#ééé",Some(&theme["palette"])).is_err());
        set_theme("black","#aabbcc").unwrap();
        assert_eq!(FRAMES.with(|frames|frames.borrow().palette),None);
        for empty in [serde_json::Value::Null,serde_json::json!({})] {
            assert!(set_theme_palette("black","#aabbcc",Some(&empty)).is_ok());
        }
    }
    #[test]
    fn effective_high_contrast_palette_is_authoritative() {
        let palette = serde_json::json!({"background":"#000000","surface":"#000000","raised":"#161616",
            "hover":"#202020","border":"#ffffff","text":"#ffffff","muted":"#eeeeee","faint":"#dddddd"});
        let palette = parse_palette(Some(&palette)).unwrap().unwrap();
        let bytes = paint(400,1,"Contrast","light",[1.,1.,1.],Some(&palette),true).unwrap();
        assert_eq!(pixel(&bytes,400,1,1),[0,0,0,255]);
        assert_eq!(pixel(&bytes,400,1,27),[255,255,255,255]);
    }

    #[test]
    fn outline_is_four_thin_strips_without_covering_client_pixels() {
        let geometry=Rectangle::new((10,20).into(),(400,300).into());
        let strips=outline_rects(geometry,false,false);
        assert_eq!(strips.len(),4);
        assert!(strips.iter().all(|r|r.size.w==1 || r.size.h==1));
        assert!(strips.iter().all(|r|geometry.intersection(*r).is_none()));
        assert_eq!(strips.iter().map(|r|r.size.w*r.size.h).sum::<i32>(),2*(400+300)+4);
        let legacy=outline_rects(geometry,true,false);
        assert_eq!(legacy[0].loc.y,20-HEIGHT-1);
        assert_eq!(legacy[1].loc.y,320);
        assert!(outline_rects(Rectangle::new((0,0).into(),(0,10).into()),false,false).is_empty());
        assert!(outline_rects(Rectangle::new((0,0).into(),(20000,10).into()),false,false).is_empty());
        assert!(outline_rects(Rectangle::new((0,0).into(),(1,1).into()),false,false).iter().all(|r|r.size.w>0 && r.size.h>0));
    }
    #[test]
    fn maximized_outline_stays_inside_the_window_bounds() {
        let geometry = Rectangle::new((80, 0).into(), (1920, 1080).into());
        let strips = outline_rects(geometry, false, true);
        assert_eq!(strips.len(), 4);
        assert!(strips.iter().all(|strip| geometry.intersection(*strip) == Some(*strip)));
    }

    #[test]
    fn outline_cache_has_only_four_pixels_and_reuses_unchanged_colors() {
        let theme:serde_json::Value=serde_json::from_str(include_str!("../../themes/forest.json")).unwrap();
        set_theme_palette("dark","#b8d893",Some(&theme["palette"])).unwrap();
        assert_eq!(outline_color(true),[0x93,0xd8,0xb8,255]);
        assert_eq!(outline_color(false),[0x64,0x7c,0x63,255]);
        let mut pixels=OutlinePixels::default();pixels.update(outline_color(true));
        let address=pixels.buffers.as_ptr();pixels.update(outline_color(true));
        assert_eq!(pixels.buffers.as_ptr(),address);
        assert_eq!(pixels.buffers.len(),4);
        for buffer in &mut pixels.buffers {
            buffer.render().draw::<_,()>(|bytes|{assert_eq!(bytes,&[0x93,0xd8,0xb8,255]);Ok(vec![])}).unwrap();
        }
        pixels.update(outline_color(false));
        for buffer in &mut pixels.buffers {
            buffer.render().draw::<_,()>(|bytes|{assert_eq!(bytes,&[0x64,0x7c,0x63,255]);Ok(vec![])}).unwrap();
        }
    }

    #[test]
    fn outline_preference_is_optional_and_strictly_boolean() {
        assert_eq!(outline_setting(None).unwrap(),true);
        assert_eq!(outline_setting(Some(&serde_json::json!(false))).unwrap(),false);
        assert_eq!(outline_setting(Some(&serde_json::json!(true))).unwrap(),true);
        for value in [serde_json::Value::Null,serde_json::json!(1),serde_json::json!("true")] {
            assert!(outline_setting(Some(&value)).is_err());
        }
        set_outline(false);assert!(!FRAMES.with(|frames|frames.borrow().outline));
        set_outline(true);assert!(FRAMES.with(|frames|frames.borrow().outline));
    }

}
