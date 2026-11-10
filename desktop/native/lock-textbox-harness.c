/* Cairo-only fixture. No Wayland connection, input, passwords, or PAM. */
#include <assert.h>
#include <cairo/cairo.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lock-textbox-render.h"

static unsigned char *draw(const char *directory, const char *name,
		size_t count, bool checking, bool wrong, bool caps) {
	cairo_surface_t *image = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 360, 96);
	cairo_t *cr = cairo_create(image);
	struct orbit_lock_textbox_visual view = {
		.password_bytes = count, .validating = checking, .invalid = wrong,
		.caps_lock = caps, .font = "Sans", .font_size = 16,
		.inside = 0xfffaf2ff, .border = 0xa44825ff, .text = 0x302920ff,
		.checking = 0x625442ff, .wrong = 0xb52b2bff,
	};
	orbit_draw_lock_textbox(cr, 360, &view);
	cairo_surface_flush(image);
	assert(cairo_status(cr) == CAIRO_STATUS_SUCCESS);
	assert(cairo_surface_status(image) == CAIRO_STATUS_SUCCESS);
	int stride = cairo_image_surface_get_stride(image);
	unsigned char *bytes = malloc(stride * 96);
	assert(bytes);memcpy(bytes, cairo_image_surface_get_data(image), stride * 96);
	char path[4096];int length = snprintf(path, sizeof(path), "%s/%s.png", directory, name);
	assert(length > 0 && length < (int)sizeof(path));
	assert(cairo_surface_write_to_png(image, path) == CAIRO_STATUS_SUCCESS);
	cairo_destroy(cr);cairo_surface_destroy(image);return bytes;
}
static unsigned char *draw_panel(const char *directory, const char *name,
        int width, uint32_t inside, uint32_t border, uint32_t text,
        uint32_t muted, uint32_t accent, const char *clock, const char *date,
        const char *user, const char *battery, double font_size) {
    cairo_surface_t *image = cairo_image_surface_create(CAIRO_FORMAT_ARGB32,
        width, ORBIT_LOCK_PANEL_HEIGHT);
    cairo_t *cr = cairo_create(image);
    struct orbit_lock_textbox_visual textbox = {
        .font = "Sans", .font_size = font_size, .inside = inside,
        .border = accent, .text = text, .checking = muted, .wrong = 0xb52b2bff,
    };
    struct orbit_lock_info_visual info = {
        .time_text = clock, .date_text = date, .user_text = user,
        .battery_text = battery, .inside = inside, .border = border,
        .text = text, .muted = muted, .accent = accent,
    };
    orbit_draw_lock_panel(cr, width, &textbox, &info);
    cairo_surface_flush(image);
    assert(cairo_status(cr) == CAIRO_STATUS_SUCCESS);
    assert(cairo_surface_status(image) == CAIRO_STATUS_SUCCESS);
    int stride = cairo_image_surface_get_stride(image);
    unsigned char *bytes = malloc(stride * ORBIT_LOCK_PANEL_HEIGHT);
    assert(bytes);memcpy(bytes, cairo_image_surface_get_data(image), stride * ORBIT_LOCK_PANEL_HEIGHT);
    char path[4096];int length = snprintf(path, sizeof(path), "%s/%s.png", directory, name);
    assert(length > 0 && length < (int)sizeof(path));
    assert(cairo_surface_write_to_png(image, path) == CAIRO_STATUS_SUCCESS);
    cairo_destroy(cr);cairo_surface_destroy(image);return bytes;
}
static void check_panel(const char *directory) {
    const uint32_t light[] = {0xfdfcffff,0x9295a9ff,0x25283bff,0x4c5067ff,0x304e8aff};
    const uint32_t dark[] = {0x171718ff,0x656568ff,0xf2f2f3ff,0xceced1ff,0xc8cbd0ff};
    const uint32_t lavender[] = {0x211a2dff,0x78668dff,0xf3edf9ff,0xd3c6e2ff,0xc7b3f2ff};
    const char *clock = "12:34", *date = "Sunday, November 8", *user = "Alex";
    unsigned char *base = draw_panel(directory,"panel-porcelain",420,
        light[0],light[1],light[2],light[3],light[4],clock,date,user,"Battery 78%",16);
    unsigned char *changed_clock = draw_panel(directory,"panel-clock-next-minute",420,
        light[0],light[1],light[2],light[3],light[4],"12:35",date,user,"Battery 78%",16);
    unsigned char *changed_date = draw_panel(directory,"panel-date-next-day",420,
        light[0],light[1],light[2],light[3],light[4],clock,"Monday, November 9",user,"Battery 78%",16);
    unsigned char *changed_user = draw_panel(directory,"panel-second-user",420,
        light[0],light[1],light[2],light[3],light[4],clock,date,"Morgan","Battery 78%",16);
    unsigned char *changed_battery = draw_panel(directory,"panel-battery-updated",420,
        light[0],light[1],light[2],light[3],light[4],clock,date,user,"Charging 79%",16);
    unsigned char *no_battery = draw_panel(directory,"panel-no-battery",420,
        light[0],light[1],light[2],light[3],light[4],clock,date,user,"",16);
    const size_t size = 420 * ORBIT_LOCK_PANEL_HEIGHT * 4;
    assert(memcmp(base,changed_clock,size) != 0);
    assert(memcmp(base,changed_date,size) != 0);
    assert(memcmp(base,changed_user,size) != 0);
    assert(memcmp(base,changed_battery,size) != 0);
    assert(memcmp(base,no_battery,size) != 0);
    free(base);free(changed_clock);free(changed_date);free(changed_user);free(changed_battery);free(no_battery);
    unsigned char *night = draw_panel(directory,"panel-graphite",420,
        dark[0],dark[1],dark[2],dark[3],dark[4],clock,date,user,"Battery 78%",16);
    unsigned char *violet = draw_panel(directory,"panel-lavender",420,
        lavender[0],lavender[1],lavender[2],lavender[3],lavender[4],clock,date,user,"Battery 78%",16);
    unsigned char *compact = draw_panel(directory,"panel-small-high-scale",288,
        dark[0],dark[1],dark[2],dark[3],dark[4],"12:34 PM","Sunday, November 8, 2026",
        "Long user name with UTF-8: Renée — international", "Charging 100%",24);
    unsigned char *contrast = draw_panel(directory,"panel-high-contrast",288,
        0x000000ff,0xffffffff,0xffffffff,0xeeeeeeff,0xffffffff,clock,date,user,NULL,16);
    free(night);free(violet);free(compact);free(contrast);
    puts("PASS Cairo lock panel: clock, date, user, battery, theme colors and small high-scale layout");
}
static void check_fitted_panel(const char *directory) {
    const int outputs[] = {1080,720,480,392,360,312,240,160};
    assert(orbit_lock_panel_height(1080)==400);
    assert(orbit_lock_panel_height(240)==208);
    for (size_t i=0;i<sizeof(outputs)/sizeof(*outputs);++i) {
        int height=orbit_lock_panel_height(outputs[i]);assert(height<=outputs[i]);
        cairo_surface_t *image=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,288,height);
        cairo_t *cr=cairo_create(image);
        struct orbit_lock_textbox_visual textbox={.font="Sans",.font_size=24,.inside=0x171718ff,.border=0xc8cbd0ff,.text=0xf2f2f3ff,.wrong=0xffaaaaFF};
        struct orbit_lock_info_visual info={.time_text="12:34 PM",.date_text="Wednesday, September 30",.user_text="Renée",.battery_text="Battery 100%",.layout_text="Keyboard: English (US)",.network_text="Network link active",.inside=0x171718ff,.border=0x656568ff,.text=0xf2f2f3ff,.muted=0xceced1ff,.accent=0xc8cbd0ff};
        orbit_draw_lock_panel_fit(cr,288,height,&textbox,&info);
        assert(cairo_status(cr)==CAIRO_STATUS_SUCCESS);
        if (height >= 360) {
            cairo_surface_flush(image);int stride=cairo_image_surface_get_stride(image);
            size_t bytes=(size_t)stride*height;unsigned char *before=malloc(bytes);assert(before);
            memcpy(before,cairo_image_surface_get_data(image),bytes);
            info.layout_text="Keyboard: German";
            orbit_draw_lock_panel_fit(cr,288,height,&textbox,&info);cairo_surface_flush(image);
            assert(memcmp(before,cairo_image_surface_get_data(image),bytes));
            memcpy(before,cairo_image_surface_get_data(image),bytes);
            info.network_text="No network link";
            orbit_draw_lock_panel_fit(cr,288,height,&textbox,&info);cairo_surface_flush(image);
            assert(memcmp(before,cairo_image_surface_get_data(image),bytes));free(before);
        }
        char path[1024];snprintf(path,sizeof(path),"%s/fit-output-%d.png",directory,outputs[i]);
        assert(cairo_surface_write_to_png(image,path)==CAIRO_STATUS_SUCCESS);
        cairo_destroy(cr);cairo_surface_destroy(image);
    }
    puts("PASS fitted lock card: logical heights160–1080, layout and honest network link status");
}
int main(int argc, char **argv) {
	assert(argc == 2);
	unsigned char *idle = draw(argv[1], "idle", 0, false, false, false);
	unsigned char *typed = draw(argv[1], "typed", 6, false, false, false);
	unsigned char *twenty = draw(argv[1], "twenty", 20, false, false, false);
	unsigned char *long_input = draw(argv[1], "bounded", SIZE_MAX, false, false, false);
	unsigned char *checking = draw(argv[1], "checking", 0, true, false, false);
	unsigned char *wrong = draw(argv[1], "wrong", 0, false, true, false);
	unsigned char *caps = draw(argv[1], "caps", 0, false, false, true);
	const size_t size = 360 * 96 * 4;
	assert(memcmp(idle, typed, size) != 0);
	assert(memcmp(twenty, long_input, size) == 0);
	assert(memcmp(idle, checking, size) != 0);
	assert(memcmp(idle, wrong, size) != 0);
	assert(memcmp(idle, caps, size) != 0);
	/* The rectangular field has an opaque horizontal edge across its center,
	 * while the unused status region remains transparent when idle. */
	assert(idle[(1 * 360 + 180) * 4 + 3] > 0);
	assert(idle[(80 * 360 + 180) * 4 + 3] == 0);
	free(idle);free(typed);free(twenty);free(long_input);free(checking);free(wrong);free(caps);
	check_panel(argv[1]);check_fitted_panel(argv[1]);
	puts("PASS Cairo textbox: idle, masked typing, bounded length, checking, wrong and Caps Lock");
	return 0;
}
