use crate::{CalloopData, OrbitCompositor};
use ::winit::platform::wayland::WindowAttributesExtWayland;
use smithay::{
    backend::{
        renderer::{
            damage::OutputDamageTracker,
            element::{
                memory::MemoryRenderBufferRenderElement, surface::WaylandSurfaceRenderElement,
                AsRenderElements,
            },
            gles::GlesRenderer,
            ImportAll, ImportMem, ImportDma, Renderer, Frame,
        },
        winit::{self, WinitEvent},
    },
    desktop::layer_map_for_output,
    output::{Mode, Output, PhysicalProperties, Subpixel},
    reexports::calloop::{
        timer::{TimeoutAction, Timer},
        EventLoop,
    },
    utils::Transform,
    wayland::shell::wlr_layer::Layer,
};
use std::{cell::RefCell, rc::Rc, time::Duration};
smithay::backend::renderer::element::render_elements! {
 pub SceneRenderElement<R> where R: ImportAll + ImportMem;
 Surface=WaylandSurfaceRenderElement<R>,
 Window=crate::window_motion::WindowRenderElement<R>,
 Memory=MemoryRenderBufferRenderElement<R>,
}
pub fn init_winit(
    event_loop: &mut EventLoop<CalloopData>,
    data: &mut CalloopData,
) -> Result<(), Box<dyn std::error::Error>> {
    let attributes = ::winit::window::Window::default_attributes()
        .with_title("Orbit Native — isolated development desktop")
        .with_inner_size(::winit::dpi::LogicalSize::new(860.0, 640.0))
        .with_name("orbit-native", "Orbit Native");
    let (backend, winit) = winit::init_from_attributes::<GlesRenderer>(attributes)?;
    backend
        .window()
        .set_title("Orbit Native — isolated development desktop");
    let mode = Mode {
        size: backend.window_size(),
        refresh: 60_000,
    };
    let output = Output::new(
        "orbit-nested".into(),
        PhysicalProperties {
            size: (0, 0).into(),
            subpixel: Subpixel::Unknown,
            make: "Orbit".into(),
            model: "Nested".into(),
        },
    );
    let _global = output.create_global::<OrbitCompositor>(&data.display_handle);
    let transform = if std::env::var("ORBIT_NESTED").as_deref() == Ok("1") {
        match std::env::var("ORBIT_NATIVE_QA_TRANSFORM")
            .unwrap_or_default()
            .as_str()
        {
            "normal" => Transform::Normal,
            "90" => Transform::_90,
            "180" => Transform::_180,
            "270" => Transform::_270,
            "flipped" => Transform::Flipped,
            "flipped-90" => Transform::Flipped90,
            "flipped-270" => Transform::Flipped270,
            _ => Transform::Flipped180,
        }
    } else {
        Transform::Flipped180
    };
    output.change_current_state(Some(mode), Some(transform), None, Some((0, 0).into()));
    output.set_preferred(mode);
    data.state.protocols.output_changed(&output);
    data.state.space.map_output(&output, (0, 0));
    for space in &mut data.state.workspaces {
        space.map_output(&output, (0, 0));
    }
    let backend = Rc::new(RefCell::new(backend));
    let (formats,device)={let mut backend=backend.borrow_mut();let renderer=backend.renderer();(renderer.dmabuf_formats().iter().copied().collect(),crate::dmabuf::renderer_device(renderer))};
    let importer=backend.clone();
    data.state.setup_dmabuf(formats,device,Box::new(move|buffer|importer.try_borrow_mut().is_ok_and(|mut backend|crate::dmabuf::validate(backend.renderer(),buffer))));
    let redraw = backend.clone();
    data.state.redraw = Some(Box::new(move || redraw.borrow().window().request_redraw()));
    let mut damage_tracker = OutputDamageTracker::from_output(&output);
    std::env::set_var("WAYLAND_DISPLAY", &data.state.socket_name);
    let handle = event_loop.handle();
    let timer_handle = handle.clone();
    handle.insert_source(winit, move |event, _, data| {
        let state = &mut data.state;
        match event {
            WinitEvent::Resized { size, .. } => {
                output.change_current_state(
                    Some(Mode {
                        size,
                        refresh: 60_000,
                    }),
                    None,
                    None,
                    None,
                );
                state.protocols.output_changed(&output);
                state.request_redraw();
            }
            WinitEvent::Input(event) => {
                state.process_input_event(event);
                let _ = data.display_handle.flush_clients();
                state.request_redraw();
            }
            WinitEvent::Redraw => {
                state.redraw_pending = false;
                state.rendered_frames += 1;
                state.advance_window_motions();
                let progress = state.animation_progress();

                let transition = state.transition;
                if transition.is_some() {
                    state.animation_frames += 1;
                }
                let mut backend = backend.borrow_mut();
                let size = backend.window_size();
                let height = size.h as f64;
                let age = if state.rendered_frames == 1
                    || (state.protocols.is_locked() && !state.protocols.lock_ready())
                {
                    0
                } else {
                    backend.buffer_age().unwrap_or(0)
                };
                let damage;
                let mut elements: Vec<SceneRenderElement<GlesRenderer>> = Vec::new();
                {
                    let (renderer, mut framebuffer) = backend.bind().unwrap();
                    let map = layer_map_for_output(&output);
                    let scale = output.current_scale().fractional_scale();
                    if state.protocols.is_locked() {
                        elements.extend(
                            state
                                .protocols
                                .lock_render_elements(&output, renderer)
                                .into_iter()
                                .map(Into::into),
                        );
                    } else {
                        for layer in map
                            .layers()
                            .rev()
                            .filter(|l| matches!(l.layer(), Layer::Overlay | Layer::Top))
                        {
                            if let Some(geometry) = map.layer_geometry(layer) {
                                elements.extend(
                                    layer.render_elements::<SceneRenderElement<GlesRenderer>>(
                                        renderer,
                                        geometry.loc.to_physical_precise_round(scale),
                                        scale.into(),
                                        1.0,
                                    ),
                                );
                            }
                        }
                        let (outgoing, incoming) = transition
                            .map(|t| crate::motion::offsets(progress, t.direction, height))
                            .unwrap_or((0.0, 0.0));
                for (window,loc) in state.minimizing_windows() {
                    let pos=(loc-window.geometry().loc-smithay::utils::Point::from((0,0))).to_physical_precise_round(scale);
                    elements.extend(crate::window_motion::elements(renderer,&window,pos,scale,state.window_visual(&window),loc).into_iter().map(Into::into));
                }
                        for window in state.space.elements().rev() {
                            if let Some(loc) = state.space.element_location(window) {
                                let mut pos =
                                    (loc - window.geometry().loc).to_physical_precise_round(scale);
                                pos.y += incoming.round() as i32;
                                elements.extend(crate::window_motion::elements(renderer,window,pos,scale,state.window_visual(window),loc).into_iter().map(Into::into));
                            }
                        }
                        if let Some(t) = transition {
                            let space = &state.workspaces[t.from];
                            for window in space.elements().rev() {
                                if let Some(loc) = space.element_location(window) {
                                    let mut pos = (loc - window.geometry().loc)
                                        .to_physical_precise_round(scale);
                                    pos.y += outgoing.round() as i32;
                                    elements.extend(crate::window_motion::elements(renderer,window,pos,scale,state.window_visual(window),loc).into_iter().map(Into::into));
                                }
                            }
                        }
                        for layer in map
                            .layers()
                            .rev()
                            .filter(|l| matches!(l.layer(), Layer::Bottom | Layer::Background))
                        {
                            if let Some(geometry) = map.layer_geometry(layer) {
                                elements.extend(
                                    layer.render_elements::<SceneRenderElement<GlesRenderer>>(
                                        renderer,
                                        geometry.loc.to_physical_precise_round(scale),
                                        scale.into(),
                                        1.0,
                                    ),
                                );
                            }
                        }
                    }
                    damage = damage_tracker
                        .render_output(
                            renderer,
                            &mut framebuffer,
                            age,
                            &elements,
                            if state.protocols.is_locked() {
                                [0.0, 0.0, 0.0, 1.0]
                            } else {
                                [0.027, 0.035, 0.047, 1.0]
                            },
                        )
                        .unwrap()
                        .damage
                        .cloned();
                    state
                        .protocols
                        .capture_output(&output, renderer, &framebuffer);
                    // SHM readback temporarily makes a surfaceless EGL context current.
                    // Restore this framebuffer's window surface before eglSwapBuffers.
                    // An empty frame changes no pixels and performs no extra scene draw.
                    if damage.is_some() {
                        renderer
                            .render(&mut framebuffer, output.current_mode().unwrap().size, Transform::Normal)
                            .unwrap()
                            .finish()
                            .unwrap();
                    }
                }
                if let Some(damage) = damage {
                    backend.submit(Some(&damage)).unwrap();
                    if state.protocols.is_locked() && crate::protocols::test_lock_presentation() {
                        // Explicit private-QA synthetic presentation only.
                        state.protocols.output_presented(&output);
                    }
                }
                drop(backend);
                if state.protocols.is_locked() {
                    state
                        .protocols
                        .lock_send_frames(&output, state.start_time.elapsed());
                }
                if !state.protocols.is_locked() {
                    for window in state.space.elements() {
                        window.send_frame(
                            &output,
                            state.start_time.elapsed(),
                            Some(Duration::ZERO),
                            |_, _| Some(output.clone()),
                        );
                    }
                    if let Some(t) = transition {
                        for window in state.workspaces[t.from].elements() {
                            window.send_frame(
                                &output,
                                state.start_time.elapsed(),
                                Some(Duration::ZERO),
                                |_, _| Some(output.clone()),
                            );
                        }
                    }
                    {
                        let map = layer_map_for_output(&output);
                        for layer in map.layers() {
                            layer.send_frame(
                                &output,
                                state.start_time.elapsed(),
                                Some(Duration::ZERO),
                                |_, _| Some(output.clone()),
                            );
                        }
                    }
                }
                state.space.refresh();
                for space in &mut state.workspaces {
                    space.refresh();
                }
                state.popups.cleanup();
                let _ = data.display_handle.flush_clients();
                if state.has_animations() && !state.animation_timer_pending {
                    state.animation_timer_pending = true;
                    let delay = Duration::from_millis(if state.economy { 33 } else { 16 });
                    timer_handle
                        .insert_source(Timer::from_duration(delay), |_, _, data| {
                            data.state.animation_timer_pending = false;
                            data.state.request_redraw();
                            TimeoutAction::Drop
                        })
                        .unwrap();
                }
            }
            WinitEvent::CloseRequested => state.loop_signal.stop(),
            _ => {}
        }
    })?;
    data.state.request_redraw();
    Ok(())
}
