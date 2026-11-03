#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    char *end = NULL;
    if (argc != 2) return 2;
    errno = 0;
    unsigned long seed = strtoul(argv[1], &end, 10);
    if (errno || *end || end == argv[1] || seed > UINT32_MAX) return 2;
    int32_t dot = 0;
    for (int i = 0; i < 16; ++i) {
        int32_t a = (int32_t)((seed + (unsigned)i * 17u) & 255u) - 128;
        int32_t b = i * 3 - 19;
        dot += a * b;
    }
    printf("{\"seed\":%lu,\"dot\":%" PRId32 "}\n", seed, dot);
    return 0;
}
