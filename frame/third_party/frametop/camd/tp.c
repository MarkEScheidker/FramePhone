/*
 * tp - read kernel tracepoints system-wide through perf_event_open.
 */

#define _GNU_SOURCE

#include "tp.h"

#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#include <linux/perf_event.h>

#ifndef TRACEFS
#define TRACEFS "/sys/kernel/tracing/events"
#endif
#define RING_DATA_PAGES 16

static void set_err(char *err, size_t n, const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(err, n, fmt, ap);
    va_end(ap);
}

bool tp_event_load(tp_event_t *ev, const char *system, const char *name, char *err, size_t errn)
{
    memset(ev, 0, sizeof(*ev));
    snprintf(ev->system, sizeof(ev->system), "%s", system);
    snprintf(ev->name, sizeof(ev->name), "%s", name);
    ev->id = -1;

    char path[256];
    snprintf(path, sizeof(path), TRACEFS "/%s/%s/format", system, name);

    FILE *f = fopen(path, "r");

    if (!f) {
        set_err(err, errn, "%s: %s", path, strerror(errno));
        return false;
    }

    char line[512];

    while (fgets(line, sizeof(line), f)) {

        int id;

        if (sscanf(line, "ID: %d", &id) == 1) {
            ev->id = id;
            continue;
        }

        char *fp = line;

        while (*fp == ' ' || *fp == '\t')
            fp++;

        if (strncmp(fp, "field:", 6) || ev->nfields >= TP_MAX_FIELDS)
            continue;

        char *semi = strchr(fp, ';');

        if (!semi)
            continue;

        /* the field name is the last identifier in the declaration */
        char decl[256];
        size_t dl = (size_t)(semi - (fp + 6));

        if (dl >= sizeof(decl))
            dl = sizeof(decl) - 1;

        memcpy(decl, fp + 6, dl);
        decl[dl] = 0;

        char *br = strchr(decl, '[');

        if (br)
            *br = 0;

        char *end = decl + strlen(decl);

        while (end > decl && (end[-1] == ' ' || end[-1] == '\t'))
            *--end = 0;

        char *start = end;

        while (start > decl && start[-1] != ' ' && start[-1] != '\t' && start[-1] != '*')
            start--;

        tp_field_t *fd = &ev->fields[ev->nfields];
        const char *o = strstr(semi, "offset:");
        const char *s = strstr(semi, "size:");
        const char *g = strstr(semi, "signed:");

        if (!o || !s)
            continue;

        snprintf(fd->name, sizeof(fd->name), "%s", start);
        fd->offset    = atoi(o + 7);
        fd->size      = atoi(s + 5);
        fd->is_signed = g ? atoi(g + 7) != 0 : false;
        ev->nfields++;
    }

    fclose(f);

    if (ev->id < 0) {
        set_err(err, errn, "%s: no ID line", path);
        return false;
    }

    return true;
}

int tp_field(const tp_event_t *ev, const char *name)
{
    for (int i = 0; i < ev->nfields; i++)
        if (!strcmp(ev->fields[i].name, name))
            return i;

    return -1;
}

int64_t tp_get(const tp_event_t *ev, int field, const uint8_t *raw, uint32_t rawlen)
{
    if (field < 0 || field >= ev->nfields)
        return 0;

    const tp_field_t *f = &ev->fields[field];

    if (f->offset < 0 || (uint32_t)(f->offset + f->size) > rawlen)
        return 0;

    const uint8_t *p = raw + f->offset;

    switch (f->size) {
    case 1: { uint8_t  v; memcpy(&v, p, 1); return f->is_signed ? (int64_t)(int8_t)v  : (int64_t)v; }
    case 2: { uint16_t v; memcpy(&v, p, 2); return f->is_signed ? (int64_t)(int16_t)v : (int64_t)v; }
    case 4: { uint32_t v; memcpy(&v, p, 4); return f->is_signed ? (int64_t)(int32_t)v : (int64_t)v; }
    case 8: { uint64_t v; memcpy(&v, p, 8); return (int64_t)v; }
    default: return 0;
    }
}

static int online_cpus(int *cpus, int max)
{
    FILE *f = fopen("/sys/devices/system/cpu/online", "r");
    int n = 0;

    if (!f)
        return 0;

    char buf[256] = {0};

    if (!fgets(buf, sizeof(buf), f))
        buf[0] = 0;

    fclose(f);

    for (char *tok = strtok(buf, ",\n"); tok && n < max; tok = strtok(NULL, ",\n")) {

        int a, b;

        if (sscanf(tok, "%d-%d", &a, &b) == 2) {
            for (int c = a; c <= b && n < max; c++)
                cpus[n++] = c;
        } else if (sscanf(tok, "%d", &a) == 1) {
            cpus[n++] = a;
        }
    }

    return n;
}

bool tp_open(tp_t *tp, tp_event_t **events, int nevents, char *err, size_t errn)
{
    memset(tp, 0, sizeof(*tp));
    tp->epfd = -1;

    if (nevents <= 0 || nevents > TP_MAX_EVENTS) {
        set_err(err, errn, "bad event count %d", nevents);
        return false;
    }

    for (int i = 0; i < nevents; i++)
        tp->events[i] = events[i];

    tp->nevents = nevents;

    int cpus[TP_MAX_CPUS];
    tp->ncpu = online_cpus(cpus, TP_MAX_CPUS);

    if (tp->ncpu <= 0) {
        set_err(err, errn, "no online CPUs found");
        return false;
    }

    long page = sysconf(_SC_PAGESIZE);
    tp->map_len = (size_t)page * (1 + RING_DATA_PAGES);

    tp->epfd = epoll_create1(EPOLL_CLOEXEC);

    if (tp->epfd < 0) {
        set_err(err, errn, "epoll_create1: %s", strerror(errno));
        return false;
    }

    for (int c = 0; c < tp->ncpu; c++) {

        tp->ring_fd[c] = -1;

        for (int e = 0; e < nevents; e++) {

            struct perf_event_attr a;
            memset(&a, 0, sizeof(a));

            a.size          = sizeof(a);
            a.type          = PERF_TYPE_TRACEPOINT;
            a.config        = (uint64_t)events[e]->id;
            a.sample_period = 1;
            a.sample_type   = PERF_SAMPLE_TID | PERF_SAMPLE_TIME | PERF_SAMPLE_CPU | PERF_SAMPLE_RAW;
            a.wakeup_events = 1;
            a.use_clockid   = 1;
            a.clockid       = CLOCK_MONOTONIC;
            a.disabled      = 1;

            int fd = (int)syscall(SYS_perf_event_open, &a, -1, cpus[c], -1, PERF_FLAG_FD_CLOEXEC);

            if (fd < 0) {
                set_err(err, errn, "perf_event_open(%s:%s, cpu %d): %s",
                        events[e]->system, events[e]->name, cpus[c], strerror(errno));
                tp_close(tp);
                return false;
            }

            tp->fds[tp->nfds++] = fd;

            if (tp->ring_fd[c] < 0) {

                void *m = mmap(NULL, tp->map_len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);

                if (m == MAP_FAILED) {
                    set_err(err, errn, "mmap perf ring (cpu %d): %s", cpus[c], strerror(errno));
                    tp_close(tp);
                    return false;
                }

                tp->ring[c]    = m;
                tp->ring_fd[c] = fd;

                struct epoll_event ee = { .events = EPOLLIN, .data.u32 = (uint32_t)c };
                epoll_ctl(tp->epfd, EPOLL_CTL_ADD, fd, &ee);

            } else if (ioctl(fd, PERF_EVENT_IOC_SET_OUTPUT, tp->ring_fd[c]) < 0) {
                set_err(err, errn, "PERF_EVENT_IOC_SET_OUTPUT: %s", strerror(errno));
                tp_close(tp);
                return false;
            }
        }
    }

    for (int i = 0; i < tp->nfds; i++)
        ioctl(tp->fds[i], PERF_EVENT_IOC_ENABLE, 0);

    return true;
}

static void ring_copy(uint8_t *dst, const uint8_t *base, uint64_t size, uint64_t pos, size_t len)
{
    uint64_t off   = pos % size;
    size_t   first = (size_t)(size - off);

    if (first >= len) {
        memcpy(dst, base + off, len);
    } else {
        memcpy(dst, base + off, first);
        memcpy(dst + first, base, len - first);
    }
}

static int cmp_sample(const void *a, const void *b)
{
    const tp_sample_t *x = a, *y = b;

    return (x->time > y->time) - (x->time < y->time);
}

static void dispatch(tp_t *tp, tp_cb cb, void *ctx)
{
    qsort(tp->pend, tp->npend, sizeof(tp->pend[0]), cmp_sample);

    for (int i = 0; i < tp->npend; i++)
        cb(ctx, &tp->pend[i]);

    tp->npend = 0;
}

static int drain_ring(tp_t *tp, int c, tp_cb cb, void *ctx)
{
    struct perf_event_mmap_page *pg = tp->ring[c];
    long     page = sysconf(_SC_PAGESIZE);
    uint64_t off  = pg->data_offset ? pg->data_offset : (uint64_t)page;
    uint64_t size = pg->data_size ? pg->data_size : (uint64_t)page * RING_DATA_PAGES;
    const uint8_t *base = (const uint8_t *)pg + off;

    uint64_t head = __atomic_load_n(&pg->data_head, __ATOMIC_ACQUIRE);
    uint64_t tail = pg->data_tail;
    int n = 0;

    while (tail < head) {

        struct perf_event_header hdr;
        ring_copy((uint8_t *)&hdr, base, size, tail, sizeof(hdr));

        if (hdr.size < sizeof(hdr))
            break;

        ring_copy(tp->scratch, base, size, tail, hdr.size);

        const uint8_t *p   = tp->scratch + sizeof(hdr);
        const uint8_t *end = tp->scratch + hdr.size;

        if (hdr.type == PERF_RECORD_LOST && end - p >= 16) {

            uint64_t lost;
            memcpy(&lost, p + 8, 8);
            tp->lost += lost;

        } else if (hdr.type == PERF_RECORD_SAMPLE && end - p >= 28) {

            tp_sample_t s;
            uint32_t v32[2];

            memcpy(v32, p, 8);      p += 8;
            s.pid = v32[0];
            s.tid = v32[1];
            memcpy(&s.time, p, 8);  p += 8;
            memcpy(v32, p, 8);      p += 8;
            s.cpu = v32[0];
            memcpy(&s.rawlen, p, 4); p += 4;
            s.raw = p;

            if (s.rawlen >= 2 && p + s.rawlen <= end) {

                uint16_t type;
                memcpy(&type, s.raw, 2);
                s.ev = NULL;

                for (int e = 0; e < tp->nevents; e++)
                    if (tp->events[e]->id == type)
                        s.ev = tp->events[e];

                if (s.ev && s.rawlen <= TP_MAX_RAW) {

                    if (tp->npend == TP_MAX_PENDING)
                        dispatch(tp, cb, ctx);

                    memcpy(tp->pend_raw[tp->npend], s.raw, s.rawlen);
                    s.raw = tp->pend_raw[tp->npend];
                    tp->pend[tp->npend++] = s;
                    n++;
                }
            }
        }

        tail += hdr.size;
    }

    __atomic_store_n(&pg->data_tail, tail, __ATOMIC_RELEASE);

    return n;
}

int tp_poll(tp_t *tp, int timeout_ms, tp_cb cb, void *ctx)
{
    struct epoll_event ev[TP_MAX_CPUS];

    if (epoll_wait(tp->epfd, ev, TP_MAX_CPUS, timeout_ms) < 0 && errno != EINTR)
        return -1;

    /*
     * Drain every ring, not just the ones that woke us: samples from several
     * CPUs need to be handled together to keep per-camera order sane.
     */
    int n = 0;

    for (int c = 0; c < tp->ncpu; c++)
        if (tp->ring[c])
            n += drain_ring(tp, c, cb, ctx);

    dispatch(tp, cb, ctx);

    return n;
}

void tp_close(tp_t *tp)
{
    for (int i = 0; i < tp->nfds; i++) {
        ioctl(tp->fds[i], PERF_EVENT_IOC_DISABLE, 0);
    }

    for (int c = 0; c < tp->ncpu; c++)
        if (tp->ring[c])
            munmap(tp->ring[c], tp->map_len);

    for (int i = 0; i < tp->nfds; i++)
        close(tp->fds[i]);

    if (tp->epfd >= 0)
        close(tp->epfd);

    tp->nfds  = 0;
    tp->epfd  = -1;
}
