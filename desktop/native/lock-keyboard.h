/* Locker-owned ASCII keyboard. Pure geometry/key mapping: no password reads,
 * external keyboard process, IPC, clipboard, shell, network or authentication. */
#ifndef MELLIPI_LOCK_KEYBOARD_H
#define MELLIPI_LOCK_KEYBOARD_H
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
#include <cairo/cairo.h>
enum mellipi_key_action { MELLIPI_KEY_NONE, MELLIPI_KEY_CHARACTER,
 MELLIPI_KEY_SHIFT, MELLIPI_KEY_SYMBOLS, MELLIPI_KEY_BACKSPACE, MELLIPI_KEY_ENTER,
 MELLIPI_KEY_TOGGLE };
struct mellipi_keyboard_key { enum mellipi_key_action action; uint32_t codepoint;
 const char *label; int row, col, span; };
/* One primary tap only. No repeat, drag activation or action after cancel. */
struct mellipi_touch_tap {bool active,moved;int32_t id;double x,y;};
static inline bool mellipi_touch_begin(struct mellipi_touch_tap *t,int32_t id,double x,double y) {
 if(t->active||!isfinite(x)||!isfinite(y))return false;
 *t=(struct mellipi_touch_tap){.active=true,.id=id,.x=x,.y=y};return true;
}
static inline void mellipi_touch_motion(struct mellipi_touch_tap *t,int32_t id,double x,double y) {
 if(t->active&&t->id==id&&(!isfinite(x)||!isfinite(y)||fabs(x-t->x)>8||fabs(y-t->y)>8))t->moved=true;
}
static inline bool mellipi_touch_end(struct mellipi_touch_tap *t,int32_t id) {
 if(!t->active||t->id!=id)return false;
 bool activate=!t->moved;t->active=false;return activate;
}
static inline void mellipi_touch_cancel(struct mellipi_touch_tap *t) {t->active=false;}
static inline int mellipi_keyboard_height(int height) {
 return height > 528 ? 224 : (height > 0 ? (int)(height * .425) : 0);
}
static inline struct mellipi_keyboard_key mellipi_keyboard_key(int row,int col,bool shift,bool symbols) {
 struct mellipi_keyboard_key k={.row=row,.col=col,.span=1};
 if(row<0||row>=5||col<0||col>=10)return k;
 const char *text=NULL;
 if(row==0) text=shift ? "!@#$%^&*()" : "1234567890";
 if(row==1) text=symbols ? (shift ? "{}|:~<>?_+" : "[]\\;`,./-=") : (shift ? "QWERTYUIOP" : "qwertyuiop");
 if(row==2 && col<9) text=shift ? "ASDFGHJKL" : "asdfghjkl";
 if(row==3 && col>=1 && col<=7) {text=shift ? "ZXCVBNM" : "zxcvbnm";k.codepoint=text[col-1];k.action=MELLIPI_KEY_CHARACTER;return k;}
 if(text && col>=0 && col<10) {k.action=MELLIPI_KEY_CHARACTER;k.codepoint=text[col];return k;}
 if(row==2 && col==9) {k.action=MELLIPI_KEY_BACKSPACE;k.label="Back";}
 if(row==3 && col==0) {k.action=MELLIPI_KEY_SHIFT;k.label=shift ? "SHIFT" : "Shift";}
 if(row==3 && col>=8) {k.action=MELLIPI_KEY_CHARACTER;k.codepoint=col==8 ? (shift?'_':'-') : (shift?'+':'=');}
 if(row==4) {
  if(col<2) {k.action=MELLIPI_KEY_SYMBOLS;k.label=symbols?"ABC":"Symbols";k.col=0;k.span=2;}
  else if(col<6) {k.action=MELLIPI_KEY_CHARACTER;k.codepoint=' ';k.label="Space";k.col=2;k.span=4;}
  else if(col<8) {k.action=MELLIPI_KEY_CHARACTER;k.codepoint=col==6?(shift?'\"':'\''):(shift?'<':',');}
  else {k.action=MELLIPI_KEY_ENTER;k.label="Unlock";k.col=8;k.span=2;}
 }
 return k;
}
static inline struct mellipi_keyboard_key mellipi_keyboard_hit(double x,double y,
 double width,double panel_height,double keyboard_height,bool shown,bool shift,bool symbols) {
 struct mellipi_keyboard_key none={0};
 if(!isfinite(x)||!isfinite(y)||!isfinite(width)||!isfinite(panel_height)||!isfinite(keyboard_height)||width<=0||x<0||x>=width||y<0) return none;
 if(x>=width-100 && x<width-12 && y>=5 && y<33) {none.action=MELLIPI_KEY_TOGGLE;return none;}
 if(!shown||keyboard_height<=0||y<panel_height+8||y>=panel_height+keyboard_height-8||x<12||x>=width-12)return none;
 double cell=(width-24)/10,row_height=(keyboard_height-16)/5;
 int row=(int)((y-panel_height-8)/row_height),col=(int)((x-12)/cell);
 if(row<0||row>=5||col<0||col>=10)return none;
 struct mellipi_keyboard_key k=mellipi_keyboard_key(row,col,shift,symbols);
 double left=12+k.col*cell,top=panel_height+8+row*row_height;
 if(x<left+2||x>=left+k.span*cell-2||y<top+2||y>=top+row_height-2)return none;
 return k;
}
static inline void mellipi_keyboard_color(cairo_t *cr,uint32_t c) {
 cairo_set_source_rgba(cr,(c>>24)/255.,((c>>16)&255)/255.,((c>>8)&255)/255.,(c&255)/255.);
}
static inline void mellipi_keyboard_label(cairo_t *cr,const char *text,double x,double y,double w,double h,uint32_t color) {
 cairo_text_extents_t e;cairo_text_extents(cr,text,&e);mellipi_keyboard_color(cr,color);
 cairo_move_to(cr,x+(w-e.width)/2-e.x_bearing,y+(h-e.height)/2-e.y_bearing);cairo_show_text(cr,text);
}
static inline void mellipi_keyboard_toggle(cairo_t *cr,double width,bool shown,uint32_t border,uint32_t text) {
 cairo_save(cr);cairo_rectangle(cr,width-100,5,88,28);mellipi_keyboard_color(cr,border);cairo_set_line_width(cr,1);cairo_stroke(cr);
 cairo_set_font_size(cr,11);mellipi_keyboard_label(cr,shown?"Hide keys":"Keyboard",width-100,5,88,28,text);cairo_restore(cr);
}
static inline void mellipi_keyboard_draw(cairo_t *cr,double width,double panel_height,double height,
 bool shift,bool symbols,uint32_t inside,uint32_t border,uint32_t text,uint32_t accent) {
 cairo_save(cr);cairo_rectangle(cr,.5,panel_height,width-1,height-.5);mellipi_keyboard_color(cr,inside);cairo_fill_preserve(cr);mellipi_keyboard_color(cr,border);cairo_set_line_width(cr,1);cairo_stroke(cr);
 double cell=(width-24)/10,rh=(height-16)/5;cairo_select_font_face(cr,"Sans",CAIRO_FONT_SLANT_NORMAL,CAIRO_FONT_WEIGHT_NORMAL);cairo_set_font_size(cr,rh<28?9:12);
 for(int row=0;row<5;row++) for(int col=0;col<10;) {
  struct mellipi_keyboard_key k=mellipi_keyboard_key(row,col,shift,symbols);double x=12+col*cell+2,y=panel_height+8+row*rh+2,w=k.span*cell-4,h=rh-4;
  cairo_rectangle(cr,x,y,w,h);mellipi_keyboard_color(cr,k.action==MELLIPI_KEY_ENTER||(k.action==MELLIPI_KEY_SHIFT&&shift)?accent:border);cairo_stroke(cr);
  char glyph[2]={(char)k.codepoint,0};mellipi_keyboard_label(cr,k.label?k.label:glyph,x,y,w,h,text);col+=k.span;
 }
 cairo_restore(cr);
}
#endif
