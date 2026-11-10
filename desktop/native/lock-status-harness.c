/* Metadata-only fixture: fake power supplies; never opens Wayland, PAM or input. */
#include <assert.h>
#include <locale.h>
#include <sys/stat.h>
#include "lock-status.h"

static void supply(const char *root,const char *name) {
	char path[1024];assert(snprintf(path,sizeof(path),"%s/%s",root,name)>0);
	assert(mkdir(path,0700)==0);
}
static void field(const char *root,const char *name,const char *key,const char *text) {
	char path[1024];assert(snprintf(path,sizeof(path),"%s/%s/%s",root,name,key)>0);
	FILE *f=fopen(path,"w");assert(f);assert(fputs(text,f)>=0);assert(fclose(f)==0);
}
static void expect_battery(const char *root,const char *expected) {
	char text[96];orbit_status_read_battery(root,text,sizeof(text));assert(!strcmp(text,expected));
}
static void check_network(const char *root) {
    char directory[1024];assert(snprintf(directory,sizeof(directory),"%s/net",root)>0);assert(mkdir(directory,0700)==0);
    char text[64];orbit_status_read_network(directory,text,sizeof(text));assert(!text[0]);
    supply(directory,"lo");field(directory,"lo","carrier","1\n");
    orbit_status_read_network(directory,text,sizeof(text));assert(!text[0]);
    supply(directory,"eth-private-name");field(directory,"eth-private-name","carrier","0\n");
    orbit_status_read_network(directory,text,sizeof(text));assert(!strcmp(text,"No network link"));
    struct orbit_status_network_cache cache={0};
    orbit_status_cached_network(&cache,directory,100,text,sizeof(text));assert(!strcmp(text,"No network link"));
    field(directory,"eth-private-name","carrier","1\n");
    orbit_status_cached_network(&cache,directory,159,text,sizeof(text));assert(!strcmp(text,"No network link"));
    orbit_status_cached_network(&cache,directory,160,text,sizeof(text));assert(!strcmp(text,"Network link active"));
    field(directory,"eth-private-name","carrier","unexpected\n");
    orbit_status_read_network(directory,text,sizeof(text));assert(!text[0]);
    orbit_status_read_network("/does/not/exist",text,sizeof(text));assert(!text[0]);
    orbit_collect_lock_network(text,sizeof(text));
    assert(orbit_network_cache.ready);orbit_expire_lock_network();assert(!orbit_network_cache.ready);
    assert(!strstr(text,"eth-private-name"));
}
int main(int argc,char **argv) {
	assert(argc==2);const char *root=argv[1];check_network(root);char text[192],tiny[3];
	assert(setlocale(LC_ALL,"C"));assert(setenv("TZ","UTC0",1)==0);tzset();
	struct tm calendar={.tm_year=126,.tm_mon=10,.tm_mday=8,.tm_hour=9,.tm_min=7};
	time_t now=mktime(&calendar);char clock[48],date[128];
	orbit_status_format_clock(now,true,clock,sizeof(clock),date,sizeof(date));
	assert(!strcmp(clock,"09:07"));assert(!strcmp(date,"Sunday, November 08"));
	orbit_status_format_clock(now,false,clock,sizeof(clock),date,sizeof(date));assert(!strcmp(clock,"9:07 AM"));
	orbit_status_format_clock(now+86400,true,clock,sizeof(clock),date,sizeof(date));assert(!strcmp(date,"Monday, November 09"));
	assert(setenv("TZ","EST5EDT,M3.2.0,M11.1.0",1)==0);tzset();
	orbit_status_format_clock(now,true,clock,sizeof(clock),date,sizeof(date));assert(!strcmp(clock,"04:07"));
	orbit_status_clean(text,sizeof(text),"Al\xc3\xa9x\n\t\x7f\xc2\x85");assert(!strcmp(text,"Al\xc3\xa9x"));
	orbit_status_clean(text,sizeof(text),"\xc0\xaf\xed\xa0\x80\xf4\x90\x80\x80");assert(!strcmp(text,"?????????"));
	orbit_status_clean(tiny,sizeof(tiny),"\xe2\x98\x83");assert(tiny[0]=='\0');
	orbit_status_clean(NULL,0,"ignored");
	unsigned percent;assert(orbit_status_percent("0",&percent)&&percent==0);assert(orbit_status_percent("100",&percent)&&percent==100);
	const char *invalid[]={"", "101", "-1", "+1", "1x", "50 0", "99999999999999999999999999"};
	for(size_t i=0;i<sizeof(invalid)/sizeof(*invalid);i++)assert(!orbit_status_percent(invalid[i],&percent));
	expect_battery(root,"");expect_battery("/path/does/not/exist","");
	supply(root,"headset");field(root,"headset","type","Battery\n");field(root,"headset","scope","Device\n");field(root,"headset","capacity","99\n");expect_battery(root,"");
	supply(root,"AC");field(root,"AC","type","Mains\n");field(root,"AC","capacity","100\n");
	supply(root,"BAT0");field(root,"BAT0","type","Battery\n");field(root,"BAT0","scope","System\n");field(root,"BAT0","capacity","57\n");field(root,"BAT0","status","Charging\n");
	expect_battery(root,"Battery 57% \xc2\xb7 Charging");
	field(root,"BAT0","status","Discharging\n");expect_battery(root,"Battery 57%");
	field(root,"BAT0","present","0\n");expect_battery(root,"");field(root,"BAT0","present","1\n");
	field(root,"BAT0","capacity","invalid\n");expect_battery(root,"");field(root,"BAT0","capacity","101\n");expect_battery(root,"");
	field(root,"BAT0","capacity","0\n");expect_battery(root,"Battery 0%");field(root,"BAT0","capacity","100\n");field(root,"BAT0","status","Full\n");expect_battery(root,"Battery 100%");
	struct orbit_status_battery_cache cache={0};
	orbit_status_cached_battery(&cache,root,100,text,sizeof(text));assert(!strcmp(text,"Battery 100%"));
	field(root,"BAT0","capacity","42\n");orbit_status_cached_battery(&cache,root,159,text,sizeof(text));assert(!strcmp(text,"Battery 100%"));
	orbit_status_cached_battery(&cache,root,160,text,sizeof(text));assert(!strcmp(text,"Battery 42%"));
	field(root,"BAT0","capacity","21\n");orbit_status_cached_battery(&cache,root,99,text,sizeof(text));assert(!strcmp(text,"Battery 21%"));
	/* Caller cannot impersonate the signed-in account through USER/LOGNAME. */
	assert(setenv("USER","abstract-fixture-impostor",1)==0);assert(setenv("LOGNAME","abstract-fixture-impostor",1)==0);
	char user[192],battery[96];orbit_collect_lock_info(clock,sizeof(clock),date,sizeof(date),user,sizeof(user),battery,sizeof(battery));
	struct passwd *account=getpwuid(getuid());assert(account);orbit_status_clean(text,sizeof(text),account->pw_name);assert(!strcmp(user,text));
	assert(clock[0]&&date[0]);assert(strcmp(user,"abstract-fixture-impostor"));
	orbit_collect_lock_info(NULL,0,NULL,0,NULL,0,NULL,0);
	puts("PASS lock metadata: live/local clock and date, UID account, UTF-8 bounds, system-only batteries and60s cache");
	return 0;
}
