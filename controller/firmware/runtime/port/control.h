#ifndef NXC_CONTROL_H
#define NXC_CONTROL_H
#include <stddef.h>
#include <stdint.h>
/* Bounded, nonblocking ASCII command decoder. A command is acted on only at
 * LF and against the exact 64-bit current request identity. */
typedef struct { char line[64]; unsigned used,overflow; } nxc_control;
enum { NXC_NONE=0,NXC_CANCEL=1,NXC_STALE=2,NXC_REJECTED=3 };
int nxc_feed(nxc_control *,unsigned char,uint64_t current_session,uint64_t *target);
int nxc_parse_cancel(const char *,uint64_t *);
#endif
