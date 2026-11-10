/* Read-only, bounded metadata for Mellipi's lock presentation.
 * No password, input, authentication or PAM APIs. No subprocesses or threads.
 * Include in the existing locker render translation unit (POSIX2008/C11).
 */
#ifndef ABSTRACT_LOCK_STATUS_H
#define ABSTRACT_LOCK_STATUS_H
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pwd.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* Preserve valid UTF-8; omit controls and replace malformed bytes. A bounded
 * source scan and complete-codepoint copies keep Cairo input valid at any size. */
static void orbit_status_clean(char *out, size_t cap, const char *in) {
	if (!out || !cap) return;
	size_t used = 0, pos = 0;
	while (in && pos < 192 && in[pos]) {
		unsigned char c = (unsigned char)in[pos];
		size_t n = c < 0x80 ? 1 : (c >= 0xc2 && c <= 0xdf ? 2 :
			(c >= 0xe0 && c <= 0xef ? 3 : (c >= 0xf0 && c <= 0xf4 ? 4 : 0)));
		bool valid = n > 0 && pos + n <= 192;
		for (size_t i = 1; valid && i < n; ++i) {
			unsigned char next = (unsigned char)in[pos+i];
			if (!next || next < 0x80 || next > 0xbf) valid = false;
		}
		if (valid && n >= 3) {
			unsigned char second = (unsigned char)in[pos+1];
			if ((c == 0xe0 && second < 0xa0) || (c == 0xed && second > 0x9f) ||
				(c == 0xf0 && second < 0x90) || (c == 0xf4 && second > 0x8f)) valid = false;
		}
		if (!valid) {
			if (used + 1 >= cap) break;
			out[used++] = '?';++pos;continue;
		}
		if ((n == 1 && (c < 0x20 || c == 0x7f)) ||
			(n == 2 && c == 0xc2 && (unsigned char)in[pos+1] <= 0x9f)) {pos += n;continue;}
		if (used + n >= cap) break;
		memcpy(out+used,in+pos,n);used += n;pos += n;
	}
	out[used] = '\0';
}
static bool orbit_status_read(const char *root, const char *entry,
		const char *field, char *out, size_t cap) {
	if (!out || cap < 2) return false;
	out[0] = '\0';
	char path[1024];int length = snprintf(path,sizeof(path),"%s/%s/%s",root,entry,field);
	if (length < 0 || (size_t)length >= sizeof(path)) return false;
	int fd = open(path,O_RDONLY | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0) return false;
	ssize_t got = read(fd,out,cap-1);close(fd);
	if (got <= 0) return false;
	out[got] = '\0';
	/* Truncation is invalid rather than accepting a misleading valid prefix. */
	if ((size_t)got == cap-1) {out[0] = '\0';return false;}
	while (got > 0 && (out[got-1] == '\n' || out[got-1] == '\r' || out[got-1] == ' ' || out[got-1] == '\t')) out[--got] = '\0';
	return true;
}
static bool orbit_status_percent(const char *text, unsigned *value) {
	if (!text || !*text || *text == '-' || *text == '+' || *text == ' ') return false;
	char *end;errno = 0;long number = strtol(text,&end,10);
	if (errno || end == text || *end || number < 0 || number > 100) return false;
	*value = (unsigned)number;return true;
}
/* Count only system batteries. Peripheral/headset supplies report scope Device.
 * A capacity mean is used for the uncommon multiple-battery fallback; no charge
 * and energy units are mixed. Reads are capped at64 directory entries. */
static void orbit_status_read_battery(const char *root, char *out, size_t cap) {
	if (!out || !cap) return;
	out[0] = '\0';DIR *directory = opendir(root);
	if (!directory) return;
	struct dirent *entry;unsigned seen = 0, total = 0, count = 0;bool charging = false;
	while (seen++ < 64 && (entry = readdir(directory))) {
		if (entry->d_name[0] == '.') continue;
		char value[128];
		if (!orbit_status_read(root,entry->d_name,"type",value,sizeof(value)) || strcmp(value,"Battery")) continue;
		if (orbit_status_read(root,entry->d_name,"scope",value,sizeof(value)) && strcmp(value,"System")) continue;
		if (orbit_status_read(root,entry->d_name,"present",value,sizeof(value)) && strcmp(value,"1")) continue;
		unsigned percent;
		if (!orbit_status_read(root,entry->d_name,"capacity",value,sizeof(value)) || !orbit_status_percent(value,&percent)) continue;
		total += percent;++count;
		if (orbit_status_read(root,entry->d_name,"status",value,sizeof(value)) && !strcmp(value,"Charging")) charging = true;
	}
	closedir(directory);
	if (count) snprintf(out,cap,"Battery %u%% %s",(total + count/2)/count,charging ? "\xc2\xb7 Charging" : "");
	/* Avoid trailing blank when no status needs displaying. */
	size_t used = strlen(out);while (used && out[used-1] == ' ') out[--used] = '\0';
}
struct orbit_status_battery_cache {bool ready;time_t checked;char text[64];};
static void orbit_status_cached_battery(struct orbit_status_battery_cache *cache,
        const char *root, time_t now, char *out, size_t cap) {
    if (!cache->ready || now < cache->checked || now - cache->checked >= 60) {
        orbit_status_read_battery(root,cache->text,sizeof(cache->text));
        cache->checked = now;cache->ready = true;
    }
    orbit_status_clean(out,cap,cache->text);
}
/* Link carrier is deliberately not presented as Internet connectivity. No
 * interface names, addresses or wireless identifiers leave this collector. */
static void orbit_status_read_network(const char *root, char *out, size_t cap) {
    if (!out || !cap) return;
    out[0] = '\0';DIR *directory = opendir(root);
    if (!directory) return;
    struct dirent *entry;unsigned seen=0;bool available=false, active=false;
    while (seen++ < 64 && (entry=readdir(directory))) {
        if (entry->d_name[0]=='.' || !strcmp(entry->d_name,"lo")) continue;
        char value[32];
        if (!orbit_status_read(root,entry->d_name,"carrier",value,sizeof(value))) continue;
        if (!strcmp(value,"1")) {available=true;active=true;break;}
        if (!strcmp(value,"0")) available=true;
    }
    closedir(directory);
    if (available) snprintf(out,cap,"%s",active ? "Network link active" : "No network link");
}
struct orbit_status_network_cache {bool ready;time_t checked;char text[64];};
static void orbit_status_cached_network(struct orbit_status_network_cache *cache,
        const char *root,time_t now,char *out,size_t cap) {
    if (!cache->ready || now < cache->checked || now-cache->checked >= 60) {
        orbit_status_read_network(root,cache->text,sizeof(cache->text));
        cache->checked=now;cache->ready=true;
    }
    orbit_status_clean(out,cap,cache->text);
}
static struct orbit_status_network_cache orbit_network_cache={0};
static void orbit_expire_lock_network(void) {orbit_network_cache.ready=false;}
static void orbit_collect_lock_network(char *out,size_t cap) {
    struct timespec now={0};
    if (clock_gettime(CLOCK_MONOTONIC,&now)) now.tv_sec=time(NULL);
    orbit_status_cached_network(&orbit_network_cache,"/sys/class/net",now.tv_sec,out,cap);
}
static void orbit_status_format_clock(time_t now, bool clock24,
		char *clock_text, size_t clock_cap, char *date_text, size_t date_cap) {
	struct tm local;char clock_buffer[64] = "", date_buffer[128] = "";
	if (localtime_r(&now,&local)) {
		strftime(clock_buffer,sizeof(clock_buffer),clock24 ? "%H:%M" : "%I:%M %p",&local);
		strftime(date_buffer,sizeof(date_buffer),"%A, %B %d",&local);
	}
	const char *clock = clock_buffer;
	if (!clock24 && clock_buffer[0] == '0') ++clock;
	orbit_status_clean(clock_text,clock_cap,clock);
	orbit_status_clean(date_text,date_cap,date_buffer);
}
static void orbit_collect_lock_info(char *time_text, size_t time_cap,
		char *date_text, size_t date_cap, char *user_text, size_t user_cap,
		char *battery_text, size_t battery_cap) {
	const char *clock_option = getenv("ORBIT_LOCK_CLOCK_24");
	orbit_status_format_clock(time(NULL),!clock_option || strcmp(clock_option,"0"),time_text,time_cap,date_text,date_cap);
	static bool user_ready = false;static char account[96] = "";
	if (!user_ready) {
		struct passwd record, *result = NULL;char storage[4096];
		if (!getpwuid_r(getuid(),&record,storage,sizeof(storage),&result) && result)
			orbit_status_clean(account,sizeof(account),result->pw_name);
		if (!account[0]) memcpy(account,"User",5);
		user_ready = true;
	}
	orbit_status_clean(user_text,user_cap,account);
	static struct orbit_status_battery_cache battery_cache = {0};
	struct timespec now = {0};
	if (clock_gettime(CLOCK_MONOTONIC,&now)) now.tv_sec = time(NULL);
	orbit_status_cached_battery(&battery_cache,"/sys/class/power_supply",now.tv_sec,battery_text,battery_cap);
}
#endif
