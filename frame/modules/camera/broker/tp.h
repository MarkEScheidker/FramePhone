/*
 * tp - read kernel tracepoints system-wide through perf_event_open.
 *
 * One perf ring per CPU; every event on that CPU writes into it. Field
 * offsets come from the tracefs format files, so kernel layout changes don't
 * silently break parsing. Needs root (or CAP_PERFMON plus tracefs access).
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TP_MAX_FIELDS 40
#define TP_MAX_EVENTS  8
#define TP_MAX_CPUS   64
#define TP_MAX_PENDING 2048
#define TP_MAX_RAW    256

typedef struct {
    char name[48];
    int  offset;
    int  size;
    bool is_signed;
} tp_field_t;

typedef struct {
    char       system[32];
    char       name[48];
    int        id;
    tp_field_t fields[TP_MAX_FIELDS];
    int        nfields;
} tp_event_t;

typedef struct {
    const tp_event_t *ev;
    const uint8_t    *raw;
    uint32_t          rawlen;
    uint64_t          time;     /* CLOCK_MONOTONIC ns */
    uint32_t          cpu;
    uint32_t          pid;
    uint32_t          tid;
} tp_sample_t;

typedef void (*tp_cb)(void *ctx, const tp_sample_t *s);

typedef struct {
    int         ncpu;
    int         ring_fd[TP_MAX_CPUS];
    void       *ring[TP_MAX_CPUS];
    size_t      map_len;
    int         fds[TP_MAX_CPUS * TP_MAX_EVENTS];
    int         nfds;
    int         epfd;
    tp_event_t *events[TP_MAX_EVENTS];
    int         nevents;
    uint64_t    lost;
    uint8_t     scratch[65536];
    /* samples drained from all rings, sorted by time before dispatch */
    tp_sample_t pend[TP_MAX_PENDING];
    uint8_t     pend_raw[TP_MAX_PENDING][TP_MAX_RAW];
    int         npend;
} tp_t;

bool    tp_event_load(tp_event_t *ev, const char *system, const char *name, char *err, size_t errn);
int     tp_field(const tp_event_t *ev, const char *name);
int64_t tp_get(const tp_event_t *ev, int field, const uint8_t *raw, uint32_t rawlen);

bool tp_open(tp_t *tp, tp_event_t **events, int nevents, char *err, size_t errn);
/*
 * Wait up to timeout_ms, then hand every pending sample to cb in time order,
 * across all CPUs. Returns samples read, -1 on error.
 */
int  tp_poll(tp_t *tp, int timeout_ms, tp_cb cb, void *ctx);
void tp_close(tp_t *tp);
