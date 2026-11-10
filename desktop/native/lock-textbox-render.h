/* Orbit's optional presentation-only swaylock renderer.
 * No password bytes, input events, authentication, or PAM APIs are accessed.
 * The existing locker owns the password; this view receives only its length.
 */
#ifndef ORBIT_LOCK_TEXTBOX_RENDER_H
#define ORBIT_LOCK_TEXTBOX_RENDER_H
#include <cairo/cairo.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define ORBIT_LOCK_PANEL_HEIGHT 400

struct orbit_lock_info_visual {
	const char *time_text, *date_text, *user_text, *battery_text;
	const char *layout_text, *network_text;
	uint32_t inside, border, text, muted, accent;
};

struct orbit_lock_textbox_visual {
	size_t password_bytes;
	bool validating, invalid, caps_lock;
	const char *font;
	double font_size;
	uint32_t inside, border, text, checking, wrong;
};
static void orbit_textbox_color(cairo_t *cr, uint32_t color) {
	cairo_set_source_rgba(cr, ((color >> 24) & 255) / 255.0,
		((color >> 16) & 255) / 255.0, ((color >> 8) & 255) / 255.0,
		(color & 255) / 255.0);
}
static void orbit_textbox_status(cairo_t *cr, const char *text,
		double width, double y, uint32_t color) {
	cairo_text_extents_t ext;
	cairo_text_extents(cr, text, &ext);
	orbit_textbox_color(cr, color);
	cairo_move_to(cr, (width - ext.width) / 2 - ext.x_bearing, y);
	cairo_show_text(cr, text);
}
static void orbit_draw_lock_textbox(cairo_t *cr, double width,
		const struct orbit_lock_textbox_visual *view) {
	const double box_height = 48.0;
	const double font_size = view->font_size < 12 ? 12 :
		(view->font_size > 24 ? 24 : view->font_size);
	uint32_t border = view->invalid ? view->wrong :
		(view->validating ? view->checking : view->border);
	cairo_save(cr);
	cairo_rectangle(cr, 1, 1, width - 2, box_height - 2);
	orbit_textbox_color(cr, view->inside);
	cairo_fill_preserve(cr);
	orbit_textbox_color(cr, border);
	cairo_set_line_width(cr, 1.5);
	cairo_stroke(cr);
	cairo_select_font_face(cr, view->font ? view->font : "Sans",
		CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
	cairo_set_font_size(cr, font_size);
	orbit_textbox_color(cr, view->text);
	if (!view->password_bytes) {
		cairo_text_extents_t ext;
		cairo_text_extents(cr, "Password", &ext);
		cairo_move_to(cr, 20, box_height / 2 - ext.y_bearing - ext.height / 2);
		cairo_show_text(cr, "Password");
	} else {
		/* Fixed, bounded glyph geometry; never inspect or copy password data.
		 * Long or multibyte input cannot increase drawing work beyond 20 dots. */
		size_t count = view->password_bytes > 20 ? 20 : view->password_bytes;
		size_t fit = width > 40 ? (size_t)((width - 40) / 14) : 0;
		if (count > fit) count = fit;
		for (size_t i = 0; i < count; ++i) {
			cairo_arc(cr, 22 + i * 14, box_height / 2, 2.5, 0, 6.283185307179586);
			cairo_fill(cr);
		}
	}
	/* A static caret shows focus without introducing a blink timer. */
	if (!view->validating) {
		size_t count = view->password_bytes > 20 ? 20 : view->password_bytes;
		size_t fit = width > 40 ? (size_t)((width - 40) / 14) : 0;
		if (count > fit) count = fit;
		double x = count ? 31 + (count - 1) * 14 : 14;
		orbit_textbox_color(cr, border);
		cairo_set_line_width(cr, 1);
		cairo_move_to(cr, x, 15);cairo_line_to(cr, x, 33);cairo_stroke(cr);
	}
	cairo_set_font_size(cr, font_size > 16 ? 14 : 13);
	if (view->validating) {
		orbit_textbox_status(cr, view->caps_lock ? "Checking… · Caps Lock" : "Checking…", width, 73, view->checking);
	} else if (view->invalid) {
		orbit_textbox_status(cr, view->caps_lock ? "Try again · Caps Lock" : "Try again", width, 73, view->wrong);
	} else if (view->caps_lock) {
		orbit_textbox_status(cr, "Caps Lock", width, 73, view->text);
	}
	cairo_restore(cr);
}
/* Metadata is supplied by the locker. This renderer neither reads the clock nor
 * opens files; every redraw remains a small bounded Cairo operation. */
static void orbit_panel_line(cairo_t *cr, const char *text, double width,
        double baseline, double font_size, uint32_t color) {
    if (!text || !*text) return;
    char bounded[164];size_t length = 0;
    while (text[length] && length < 156) {bounded[length] = text[length];length++;}
    /* Never split a UTF-8 sequence if an unexpectedly long label is supplied. */
    if (text[length]) {
        while (length && (((unsigned char)text[length] & 0xc0) == 0x80)) length--;
        memcpy(bounded + length, "…", 3);length += 3;
    }
    bounded[length] = '\0';
    cairo_set_font_size(cr, font_size);
    cairo_text_extents_t ext;cairo_text_extents(cr, bounded, &ext);
    if (ext.width > width - 48) {
        /* Prefer a normal reading size; shorten only exceptional long labels. */
        double fit = font_size * (width - 48) / ext.width;
        if (fit >= 11) cairo_set_font_size(cr, fit);
        else {
            cairo_set_font_size(cr, 11);
            while (length > 0) {
                do {length--;} while (length && (((unsigned char)bounded[length] & 0xc0) == 0x80));
                memcpy(bounded + length, "…", 3);bounded[length + 3] = '\0';
                cairo_text_extents(cr, bounded, &ext);
                if (ext.width <= width - 48) break;
            }
        }
    }
    orbit_textbox_status(cr, bounded, width, baseline, color);
}
/* Fit presentation to logical output height without scaling the password field. */
static int orbit_lock_panel_height(int output_height) {
    if (output_height > ORBIT_LOCK_PANEL_HEIGHT + 32) return ORBIT_LOCK_PANEL_HEIGHT;
    return output_height > 200 ? output_height - 32 : (output_height > 0 ? output_height : 1);
}
static void orbit_draw_lock_panel_fit(cairo_t *cr, double width, double height,
        const struct orbit_lock_textbox_visual *textbox,
        const struct orbit_lock_info_visual *info) {
    cairo_save(cr);
    cairo_rectangle(cr, .5, .5, width - 1, height - 1);
    orbit_textbox_color(cr, info->inside);cairo_fill_preserve(cr);
    orbit_textbox_color(cr, info->border);cairo_set_line_width(cr, 1);cairo_stroke(cr);
    orbit_textbox_color(cr, info->accent);cairo_rectangle(cr, 24, 0, 48, 3);cairo_fill(cr);
    cairo_select_font_face(cr, textbox->font ? textbox->font : "Sans",
        CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
    double scale = textbox->font_size / 16;
    if (scale < .85) scale = .85;
    if (scale > 1.5) scale = 1.5;
    double field_y;
    if (height >= 360) {
        orbit_panel_line(cr, "Mellipi", width, height*.075, 13*scale, info->muted);
        orbit_panel_line(cr, info->time_text, width, height*.25, 54*scale, info->text);
        orbit_panel_line(cr, info->date_text, width, height*.33, 14*scale, info->muted);
        orbit_panel_line(cr, info->user_text, width, height*.43, 17*scale, info->text);
        orbit_panel_line(cr, info->layout_text, width, height*.49, 11*scale, info->muted);
        field_y = height*.53;
    } else if (height >= 280) {
        orbit_panel_line(cr, info->time_text, width, height*.17, 42*scale, info->text);
        orbit_panel_line(cr, info->date_text, width, height*.25, 12*scale, info->muted);
        orbit_panel_line(cr, info->user_text, width, height*.35, 15*scale, info->text);
        orbit_panel_line(cr, info->layout_text, width, height*.43, 11*scale, info->muted);
        field_y = height*.47;
    } else if (height >= 200) {
        orbit_panel_line(cr, info->time_text, width, 34, 30, info->text);
        orbit_panel_line(cr, info->user_text, width, 60, 14, info->text);
        orbit_panel_line(cr, info->layout_text, width, 80, 11, info->muted);
        field_y = 92;
    } else {
        orbit_panel_line(cr, info->layout_text, width, 19, 11, info->muted);
        field_y = 30;
    }
    cairo_save(cr);cairo_translate(cr, 24, field_y);
    orbit_draw_lock_textbox(cr, width - 48, textbox);
    cairo_restore(cr);
    if (height >= 360) {
        orbit_panel_line(cr, "Enter to unlock", width, height*.80, 12*scale, info->muted);
        orbit_panel_line(cr, info->battery_text, width, height*.875, 12*scale, info->muted);
        orbit_panel_line(cr, info->network_text, width, height*.95, 11*scale, info->muted);
    } else if (height >= 280) {
        orbit_panel_line(cr, "Enter to unlock", width, height-62, 11, info->muted);
        orbit_panel_line(cr, info->battery_text, width, height-40, 11, info->muted);
        orbit_panel_line(cr, info->network_text, width, height-18, 11, info->muted);
    } else if (height >= 140) {
        orbit_panel_line(cr, "Enter to unlock", width, height-15, 11, info->muted);
    }
    cairo_restore(cr);
}
static inline void orbit_draw_lock_panel(cairo_t *cr, double width,
        const struct orbit_lock_textbox_visual *textbox,
        const struct orbit_lock_info_visual *info) {
    orbit_draw_lock_panel_fit(cr,width,ORBIT_LOCK_PANEL_HEIGHT,textbox,info);
}
#endif
