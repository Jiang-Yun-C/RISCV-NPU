#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <time.h>
uint64_t nx_port_ticks(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
