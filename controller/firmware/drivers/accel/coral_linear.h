#ifndef NX_CORAL_TRANSPORT_H
#define NX_CORAL_TRANSPORT_H
#include "linear_api.h"
/* Platform wait must return periodically even when completion IRQ is lost.
 * NULL selects polling. This transport never treats notification as success. */
typedef struct { nx_context *context; void (*wait)(void *); void *wait_cookie; } nx_coral_transport;
nx_status nx_coral_linear_execute(void *, const nx_call *, const struct nx_stream_request *, struct nx_stream_result *);
#endif
