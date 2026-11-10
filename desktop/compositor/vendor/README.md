Smithay 0.7.0, copied from the pinned Cargo registry source. License: MIT;
see smithay/LICENSE.txt. The only source change is the non-text MIME atom
resolution branch in src/xwayland/xwm/mod.rs::X11Wm::send_selection, documented
in ../../docs/clipboard-and-ui-cleanup.md. All runtime behavior outside that
branch remains upstream. Vendoring affects source/build only.
