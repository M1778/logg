/* Linux-only deterministic libc faults for the subprocess regression runner. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

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
