// =============================================================================
// Fin Programming Language
//
// Made with ❤️ for someone special.
//
// This project is genuinely built on love and dedication, a way to express your love can be done through Fin.
// Fin is a semi-object-orientated programming language that specialized in control, giving so much control to the user while asking for the bare minimum.
// Fin is the name of the Angel from BlackNightmare-Stories not yet published.
// “Love is the reason this project exists”
// -----------------------------------------------------------------------------
// Author: M1778
// Repository: https://github.com/M1778/logg
// Profile: https://github.com/M1778M/
// -----------------------------------------------------------------------------
// Copyright (C) 2027 M1778
//
// This file is part of logg, a project for the Fin Programming Language.
//
// Licensed under the MIT License. See LICENSE in the repository root.
//
// SPDX-License-Identifier: MIT
// =============================================================================

/* Linux-only deterministic libc faults for the subprocess regression runner. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Which streams the logger configured unbuffered. A record larger than stdio's
// buffer is split across writes unless the stream is unbuffered, and a split
// record is what lets a second writer land inside it. Tracking the mode makes
// that a deterministic assertion rather than a race the test can lose.
static FILE *unbuffered[8];
static int unbuffered_count;

static int is_unbuffered(FILE *stream) {
    for (int i = 0; i < unbuffered_count; i++) {
        if (unbuffered[i] == stream) return 1;
    }
    return 0;
}

int setvbuf(FILE *stream, char *buffer, int mode, size_t size) {
    static int (*real_setvbuf)(FILE *, char *, int, size_t);
    if (!real_setvbuf) real_setvbuf = dlsym(RTLD_NEXT, "setvbuf");
    int result = real_setvbuf(stream, buffer, mode, size);
    if (result == 0 && mode == _IONBF && unbuffered_count < 8) {
        unbuffered[unbuffered_count++] = stream;
    }
    return result;
}

size_t fwrite(const void *buffer, size_t size, size_t count, FILE *stream) {
    static size_t (*real_fwrite)(const void *, size_t, size_t, FILE *);
    if (!real_fwrite) real_fwrite = dlsym(RTLD_NEXT, "fwrite");
    const char *fault = getenv("LOGG_IO_FAULT");
    // A buffered stream would split this record at its own buffer boundary.
    if (fault && strcmp(fault, "buffered-large-write") == 0
        && size * count > 65536 && !is_unbuffered(stream)) {
        errno = EINVAL;
        return 0;
    }
    return real_fwrite(buffer, size, count, stream);
}

ssize_t write(int fd, const void *buffer, size_t size) {
    static ssize_t (*real_write)(int, const void *, size_t);
    static int calls;
    if (!real_write) real_write = dlsym(RTLD_NEXT, "write");
    const char *fault = getenv("LOGG_IO_FAULT");
    if (fd == 1 && fault && strcmp(fault, "short-eintr") == 0) {
        if (calls++ == 0) { errno = EINTR; return -1; }
        if (size > 3) size = 3;
    }
    if (fd == 1 && fault && strcmp(fault, "zero-write") == 0) return 0;
    return real_write(fd, buffer, size);
}

int fflush(FILE *stream) {
    static int (*real_flush)(FILE *);
    if (!real_flush) real_flush = dlsym(RTLD_NEXT, "fflush");
    const char *fault = getenv("LOGG_IO_FAULT");
    if (fault && strcmp(fault, "flush-error") == 0) { errno = EIO; return EOF; }
    return real_flush(stream);
}
