//! Compositor-owned PNG selections. No helper process or idle worker.
use smithay::reexports::rustix;
use std::{
    io::Read,
    os::fd::OwnedFd,
    os::unix::fs::{MetadataExt, OpenOptionsExt},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
#[derive(Clone, Default)]
pub enum SelectionData {
    #[default]
    X11,
    Png(Arc<Vec<u8>>),
    Text(Arc<Vec<u8>>),
    MimeData(Arc<std::collections::BTreeMap<String, Arc<Vec<u8>>>>),
}
const MAX_BYTES: u64 = 100_000_000;
pub fn read_png(path: &str) -> Result<Arc<Vec<u8>>, String> {
    if !std::path::Path::new(path).is_absolute() {
        return Err("Expected an absolute PNG path".into());
    }
    let file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(path)
        .map_err(|e| e.to_string())?;
    let meta = file.metadata().map_err(|e| e.to_string())?;
    if !meta.is_file() || meta.uid() != rustix::process::getuid().as_raw() || meta.len() > MAX_BYTES
    {
        return Err("Expected a bounded PNG owned by this user".into());
    }
    let mut data = Vec::new();
    file.take(MAX_BYTES + 1)
        .read_to_end(&mut data)
        .map_err(|e| e.to_string())?;
    validate(&data)?;
    Ok(Arc::new(data))
}
fn validate(data: &[u8]) -> Result<(), String> {
    if data.len() < 24
        || data.len() > MAX_BYTES as usize
        || data.get(..8) != Some(b"\x89PNG\r\n\x1a\n")
        || data.get(12..16) != Some(b"IHDR")
    {
        return Err("Invalid clipboard PNG".into());
    }
    let w = u32::from_be_bytes(data[16..20].try_into().unwrap()) as u64;
    let h = u32::from_be_bytes(data[20..24].try_into().unwrap()) as u64;
    if w == 0 || h == 0 || w * h > 16_000_000 {
        return Err("PNG exceeds screenshot dimensions".into());
    }
    Ok(())
}
static TRANSFERS: AtomicUsize = AtomicUsize::new(0);
pub fn send_png(bytes: Arc<Vec<u8>>, fd: OwnedFd) {
    if TRANSFERS.fetch_add(1, Ordering::SeqCst) >= 2 {
        TRANSFERS.fetch_sub(1, Ordering::SeqCst);
        return;
    }
    let spawn = std::thread::Builder::new()
        .name("orbit-clipboard-send".into())
        .spawn(move || {
            struct Done;
            impl Drop for Done {
                fn drop(&mut self) {
                    TRANSFERS.fetch_sub(1, Ordering::SeqCst);
                }
            }
            let _done = Done;
            if rustix::fs::fcntl_setfl(
                &fd,
                rustix::fs::OFlags::WRONLY | rustix::fs::OFlags::NONBLOCK,
            )
            .is_err()
            {
                return;
            }
            let end = Instant::now() + Duration::from_secs(5);
            let mut offset = 0;
            while offset < bytes.len() {
                match rustix::io::write(&fd, &bytes[offset..]) {
                    Ok(0) => break,
                    Ok(n) => offset += n,
                    Err(rustix::io::Errno::INTR) => continue,
                    Err(rustix::io::Errno::AGAIN) => {
                        let remaining = end.saturating_duration_since(Instant::now());
                        if remaining.is_zero() {
                            break;
                        }
                        let timeout = rustix::event::Timespec {
                            tv_sec: remaining.as_secs() as _,
                            tv_nsec: remaining.subsec_nanos() as _,
                        };
                        let mut fds = [rustix::event::PollFd::new(
                            &fd,
                            rustix::event::PollFlags::OUT,
                        )];
                        if !matches!(rustix::event::poll(&mut fds,Some(&timeout)),Ok(n) if n>0) {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        });
    if spawn.is_err() {
        TRANSFERS.fetch_sub(1, Ordering::SeqCst);
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn rejects_invalid_and_oversized_images() {
        assert!(super::validate(b"not png").is_err());
        let mut data = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR".to_vec();
        data.extend(1920u32.to_be_bytes());
        data.extend(1080u32.to_be_bytes());
        assert!(super::validate(&data).is_ok());
        data[16..20].copy_from_slice(&u32::MAX.to_be_bytes());
        assert!(super::validate(&data).is_err());
    }
}

impl SelectionData {
    pub fn mimes(&self) -> Vec<String> {
        match self {
            Self::Text(_) => vec![
                "text/plain;charset=utf-8".into(),
                "text/plain".into(),
                "UTF8_STRING".into(),
            ],
            Self::MimeData(data) => data.keys().cloned().collect(),
            Self::Png(_) => vec!["image/png".into()],
            Self::X11 => vec![],
        }
    }
    pub fn bytes_for(&self, mime: &str) -> Option<Arc<Vec<u8>>> {
        match self {
            Self::Text(bytes) if text_mime(mime) => Some(bytes.clone()),
            Self::MimeData(data) => data.get(mime).cloned(),
            Self::Png(bytes) if mime == "image/png" => Some(bytes.clone()),
            _ => None,
        }
    }
}
fn uri_paths(uri: &str) -> Option<Vec<u8>> {
    let mut paths = Vec::new();
    for line in uri
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
    {
        let mut path = line.strip_prefix("file://")?;
        if path.starts_with("localhost/") {
            path = &path["localhost".len()..];
        } else if !path.starts_with('/') {
            return None;
        }
        let raw = path.as_bytes();
        let mut out = Vec::new();
        let mut i = 0;
        while i < raw.len() {
            if raw[i] == b'%' {
                if i + 2 >= raw.len() {
                    return None;
                }
                let hex = std::str::from_utf8(&raw[i + 1..i + 3]).ok()?;
                out.push(u8::from_str_radix(hex, 16).ok()?);
                i += 3;
            } else {
                out.push(raw[i]);
                i += 1;
            }
        }
        if out.contains(&0) || std::str::from_utf8(&out).is_err() {
            return None;
        }
        if !paths.is_empty() {
            paths.push(b'\n');
        }
        paths.extend(out);
    }
    Some(paths)
}
fn sensitive_mime(mime: &str) -> bool {
    [
        "x-kde-passwordManagerHint",
        "application/x-kde-passwordmanager",
        "application/x-keepassxc",
        "application/x-secret",
    ]
    .iter()
    .any(|hint| mime.eq_ignore_ascii_case(hint))
}
fn retained_data(mime: &str, bytes: Vec<u8>) -> Option<SelectionData> {
    std::str::from_utf8(&bytes).ok()?;
    if text_mime(mime) {
        return Some(SelectionData::Text(Arc::new(bytes)));
    }
    // Four derived forms are capped together by reducing the file-list limit.
    if bytes.len() > MAX_TEXT / 4 {
        return None;
    }
    let mut map = std::collections::BTreeMap::<String, Arc<Vec<u8>>>::new();
    let text = std::str::from_utf8(&bytes).ok()?;
    let uri = if mime == "x-special/gnome-copied-files" {
        let (mode, uri) = text.split_once('\n')?;
        if !matches!(mode, "copy" | "cut") {
            return None;
        }
        uri.to_owned()
    } else if mime == "text/uri-list" {
        text.to_owned()
    } else {
        return None;
    };
    let uri_bytes = Arc::new(uri.as_bytes().to_vec());
    map.insert("text/uri-list".into(), uri_bytes.clone());
    let file_only = uri
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with('#'))
        .all(|line| line.starts_with("file://"));
    if mime == "x-special/gnome-copied-files" {
        map.insert(mime.into(), Arc::new(bytes));
    } else if file_only {
        map.insert(
            "x-special/gnome-copied-files".into(),
            Arc::new(format!("copy\n{uri}").into_bytes()),
        );
    }
    let plain = uri_paths(&uri).map(Arc::new).unwrap_or(uri_bytes);
    map.insert("text/plain;charset=utf-8".into(), plain.clone());
    map.insert("text/plain".into(), plain);
    Some(SelectionData::MimeData(Arc::new(map)))
}
/// Only UTF-8 plain text is retained; no history, HTML scraping, images or disk.
pub fn text_mime(mime: &str) -> bool {
    matches!(
        mime,
        "text/plain;charset=utf-8" | "text/plain;charset=UTF-8" | "UTF8_STRING" | "text/plain"
    )
}
const MAX_TEXT: usize = 1024 * 1024;
use smithay::{
    reexports::calloop::{
        generic::Generic,
        timer::{TimeoutAction, Timer},
        Interest, Mode, PostAction, RegistrationToken,
    },
    utils::IsAlive,
    wayland::selection::{
        data_device::set_data_device_selection, SelectionSource, SelectionTarget,
    },
};
#[derive(Default)]
pub struct Retention {
    generation: u64,
    source: Option<SelectionSource>,
    bytes: Option<SelectionData>,
    read: Option<RegistrationToken>,
    timeout: Option<RegistrationToken>,
    x11: bool,
    x11_orphan: bool,
}
impl crate::OrbitCompositor {
    pub fn retain_selection(&mut self, target: SelectionTarget, source: Option<SelectionSource>) {
        if target != SelectionTarget::Clipboard {
            return;
        }
        let handle = self.clipboard_loop.clone();
        if let Some(token) = self.clipboard_retention.read.take() {
            handle.remove(token);
        }
        if let Some(token) = self.clipboard_retention.timeout.take() {
            handle.remove(token);
        }
        let cache = &mut self.clipboard_retention;
        cache.generation = cache.generation.wrapping_add(1);
        cache.bytes = None;
        cache.source = source.clone();
        cache.x11 = false;
        cache.x11_orphan = false;
        let generation = cache.generation;
        let Some(source) = source else {
            return;
        };
        // Password-manager custom/sensitive selections are deliberately skipped.
        let mimes = source.mime_types();
        if mimes.iter().any(|mime| sensitive_mime(mime)) {
            return;
        }
        let Some(mime) = [
            "x-special/gnome-copied-files",
            "text/uri-list",
            "text/plain;charset=utf-8",
            "text/plain;charset=UTF-8",
            "UTF8_STRING",
            "text/plain",
        ]
        .into_iter()
        .find(|mime| mimes.iter().any(|m| m == mime)) else {
            return;
        };
        self.begin_clipboard_read(generation, Some(source), mime.to_owned());
    }
    pub fn retain_x11_selection(&mut self, mimes: &[String]) {
        self.retain_selection(SelectionTarget::Clipboard, None);
        self.clipboard_retention.x11 = true;
        if mimes.iter().any(|mime| sensitive_mime(mime)) {
            return;
        }
        if let Some(mime) = [
            "x-special/gnome-copied-files",
            "text/uri-list",
            "text/plain;charset=utf-8",
            "text/plain;charset=UTF-8",
            "UTF8_STRING",
            "text/plain",
        ]
        .into_iter()
        .find(|mime| mimes.iter().any(|m| m == mime))
        {
            self.begin_clipboard_read(self.clipboard_retention.generation, None, mime.to_owned());
        }
    }
    pub fn orphan_x11_clipboard(&mut self) {
        if self.clipboard_retention.x11 {
            self.clipboard_retention.x11_orphan = true;
            self.promote_orphan_clipboard();
        }
    }
    fn begin_clipboard_read(
        &mut self,
        generation: u64,
        source: Option<SelectionSource>,
        mime: String,
    ) {
        let handle = self.clipboard_loop.clone();
        let Ok((read, write)) = rustix::pipe::pipe_with(
            rustix::pipe::PipeFlags::CLOEXEC | rustix::pipe::PipeFlags::NONBLOCK,
        ) else {
            return;
        };
        // Only the reader is nonblocking; clients own the write endpoint and may
        // use normal blocking writes. The main compositor never waits on them.
        let _ = rustix::fs::fcntl_setfl(&write, rustix::fs::OFlags::WRONLY);
        let captured_mime = mime.clone();
        if let Some(source) = source {
            if !source.request_data(mime, write) {
                return;
            }
        } else {
            self.send_x11_selection(SelectionTarget::Clipboard, mime, write);
        }
        let mut bytes = Vec::new();
        let token = handle.insert_source(
            Generic::new(read, Interest::READ, Mode::Level),
            move |_, fd, data| {
                if data.state.clipboard_retention.generation != generation {
                    return Ok(PostAction::Remove);
                }
                let mut chunk = [0u8; 16384];
                let mut budget: usize = 65536;
                loop {
                    match rustix::io::read(&*fd, &mut chunk) {
                        Ok(0) => {
                            if !bytes.is_empty() && std::str::from_utf8(&bytes).is_ok() {
                                data.state.clipboard_retention.bytes =
                                    retained_data(&captured_mime, std::mem::take(&mut bytes));
                            }
                            data.state.finish_clipboard_capture(generation);
                            data.state.promote_orphan_clipboard();
                            return Ok(PostAction::Remove);
                        }
                        Ok(n) => {
                            if bytes.len() + n > MAX_TEXT {
                                data.state.finish_clipboard_capture(generation);
                                return Ok(PostAction::Remove);
                            }
                            bytes.extend_from_slice(&chunk[..n]);
                            budget = budget.saturating_sub(n);
                            if budget < chunk.len() {
                                return Ok(PostAction::Continue);
                            }
                        }
                        Err(rustix::io::Errno::INTR) => continue,
                        Err(rustix::io::Errno::AGAIN) => return Ok(PostAction::Continue),
                        Err(_) => {
                            data.state.finish_clipboard_capture(generation);
                            return Ok(PostAction::Remove);
                        }
                    }
                }
            },
        );
        let Ok(token) = token else {
            return;
        };
        self.clipboard_retention.read = Some(token);
        if let Ok(timer) = handle.insert_source(
            Timer::from_duration(Duration::from_secs(3)),
            move |_, _, data| {
                if data.state.clipboard_retention.generation == generation {
                    if let Some(token) = data.state.clipboard_retention.read.take() {
                        data.state.clipboard_loop.remove(token);
                    }
                    data.state.clipboard_retention.timeout = None;
                }
                TimeoutAction::Drop
            },
        ) {
            self.clipboard_retention.timeout = Some(timer);
        } else if let Some(read) = self.clipboard_retention.read.take() {
            handle.remove(read);
        }
    }
    fn finish_clipboard_capture(&mut self, generation: u64) {
        if self.clipboard_retention.generation != generation {
            return;
        }
        self.clipboard_retention.read = None;
        if let Some(timer) = self.clipboard_retention.timeout.take() {
            self.clipboard_loop.remove(timer);
        }
    }
    pub fn promote_orphan_clipboard(&mut self) {
        if self.protocols.is_locked() {
            return;
        }
        let orphan = self.clipboard_retention.x11_orphan
            || self
                .clipboard_retention
                .source
                .as_ref()
                .is_some_and(|source| !source.alive());
        if !orphan {
            return;
        }
        let Some(bytes) = self.clipboard_retention.bytes.clone() else {
            return;
        };
        self.clipboard_retention.source = None;
        self.clipboard_retention.x11 = false;
        self.clipboard_retention.x11_orphan = false;
        let mimes = bytes.mimes();
        set_data_device_selection(&self.display_handle, &self.seat, mimes.clone(), bytes);
        if let Some(xwm) = &mut self.xwayland.xwm {
            let _ = xwm.new_selection(SelectionTarget::Clipboard, Some(mimes));
        }
    }
}
#[cfg(test)]
mod text_tests {
    #[test]
    fn password_manager_hints_are_opted_out() {
        assert!(super::sensitive_mime("x-kde-passwordManagerHint"));
        assert!(super::sensitive_mime("application/x-kde-passwordmanager"));
        assert!(!super::sensitive_mime("text/plain"));
    }
    #[test]
    fn cut_file_bundle_retains_all_semantics() {
        let raw = b"cut\nfile:///tmp/hello%20world.txt".to_vec();
        let data = super::retained_data("x-special/gnome-copied-files", raw.clone()).unwrap();
        assert_eq!(
            &*data.bytes_for("x-special/gnome-copied-files").unwrap(),
            &raw
        );
        assert_eq!(
            &**data.bytes_for("text/uri-list").unwrap(),
            b"file:///tmp/hello%20world.txt"
        );
        assert_eq!(
            &**data.bytes_for("text/plain").unwrap(),
            b"/tmp/hello world.txt"
        );
    }
    #[test]
    fn file_cache_rejects_invalid_and_oversized_metadata() {
        assert!(super::retained_data(
            "x-special/gnome-copied-files",
            b"execute\nfile:///tmp/a".to_vec()
        )
        .is_none());
        assert!(
            super::retained_data("text/uri-list", vec![b'a'; super::MAX_TEXT / 4 + 1]).is_none()
        );
        assert!(super::retained_data("text/plain", vec![0xff]).is_none());
    }
    #[test]
    fn only_plain_utf8_mimes_are_accepted() {
        for mime in ["text/plain", "text/plain;charset=utf-8", "UTF8_STRING"] {
            assert!(super::text_mime(mime));
        }
        for mime in ["text/html", "image/png", "application/octet-stream"] {
            assert!(!super::text_mime(mime));
        }
    }
}
