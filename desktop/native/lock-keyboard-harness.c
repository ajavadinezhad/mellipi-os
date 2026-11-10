/* Pure render/hit-test regression; no Wayland display, input, password or PAM. */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "lock-keyboard.h"
int main(int argc,char **argv) {
 assert(argc==2);bool ascii[127]={0};
 struct mellipi_touch_tap tap={0};
 assert(mellipi_touch_begin(&tap,1,10,10));assert(!mellipi_touch_begin(&tap,2,20,20));
 assert(!mellipi_touch_end(&tap,2));assert(tap.active);assert(mellipi_touch_end(&tap,1));assert(!mellipi_touch_end(&tap,1));
 assert(mellipi_touch_begin(&tap,3,10,10));mellipi_touch_motion(&tap,3,19,10);assert(!mellipi_touch_end(&tap,3));
 assert(mellipi_touch_begin(&tap,4,10,10));mellipi_touch_cancel(&tap);assert(!mellipi_touch_end(&tap,4));
 assert(!mellipi_touch_begin(&tap,5,NAN,10));assert(mellipi_touch_begin(&tap,5,10,10));mellipi_touch_motion(&tap,5,NAN,10);assert(!mellipi_touch_end(&tap,5));
 for(int symbols=0;symbols<2;symbols++)for(int shift=0;shift<2;shift++)for(int row=0;row<5;row++)for(int col=0;col<10;col++){
  struct mellipi_keyboard_key k=mellipi_keyboard_key(row,col,shift,symbols);
  assert(k.action!=MELLIPI_KEY_NONE&&k.span>=1&&k.col>=0&&k.col+k.span<=10);
  double cell=(420.-24)/10,rh=(224.-16)/5,x=12+(k.col+k.span*.5)*cell,y=400+8+(row+.5)*rh;
  struct mellipi_keyboard_key hit=mellipi_keyboard_hit(x,y,420,400,224,true,shift,symbols);
  assert(hit.action==k.action&&hit.codepoint==k.codepoint);
  assert(mellipi_keyboard_hit(x,y,420,400,0,false,shift,symbols).action==MELLIPI_KEY_NONE);
  if(k.action==MELLIPI_KEY_CHARACTER){assert(k.codepoint>=32&&k.codepoint<=126);ascii[k.codepoint]=true;}
 }
 for(int c=32;c<=126;c++)assert(ascii[c]);
 assert(mellipi_keyboard_hit(NAN,20,420,400,224,true,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_hit(20,20,NAN,400,224,true,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_hit(20,20,420,NAN,224,true,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_key(-1,0,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_key(4,10,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_hit(400,INFINITY,420,400,224,true,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_hit(-1,20,420,400,224,true,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_hit(420,20,420,400,224,true,0,0).action==MELLIPI_KEY_NONE);
 assert(mellipi_keyboard_hit(360,20,420,400,0,false,0,0).action==MELLIPI_KEY_TOGGLE);
 assert(mellipi_keyboard_hit(12,410,420,400,224,true,0,0).action==MELLIPI_KEY_NONE);
 for(int h=160;h<=1080;h+=20){int kh=mellipi_keyboard_height(h);assert(kh>0&&kh<h&&kh<=224);}
 for(int mode=0;mode<4;mode++) {
  cairo_surface_t *s=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,420,624);cairo_t *cr=cairo_create(s);
  mellipi_keyboard_draw(cr,420,400,224,mode&1,mode&2,0x18251aff,0x7d9677ff,0xedf4e9ff,0xb8d893ff);
  mellipi_keyboard_toggle(cr,420,true,0x7d9677ff,0xedf4e9ff);
  assert(cairo_status(cr)==CAIRO_STATUS_SUCCESS);char path[4096];snprintf(path,sizeof(path),"%s/keyboard-%d.png",argv[1],mode);assert(cairo_surface_write_to_png(s,path)==CAIRO_STATUS_SUCCESS);cairo_destroy(cr);cairo_surface_destroy(s);
 }
 puts("Locker keyboard: full printable ASCII, bounded geometry, hidden rejection and Cairo rendering passed");return 0;
}
