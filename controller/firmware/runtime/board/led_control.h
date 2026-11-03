#ifndef NX_LED_CONTROL_H
#define NX_LED_CONTROL_H
#include "runtime.h"
#include "../../application/application.h"
#define NX_LED_ID 0x10000400u
#define NX_LED_STATE 0x10000404u
#define NX_LED_ABI 0x3144454cu
#ifndef NX_LED_BANK
#define NX_LED_BANK 0
#endif
#if NX_LED_BANK != 0 && NX_LED_BANK != 1
#error NX_LED_BANK must be 0 or 1
#endif
#define NX_LED_BANK_ID 0x10000408u
#define NX_LED_BANK_CAPS 0x1000040cu
#define NX_LED_BANK_VALUES 0x10000410u
#define NX_LED_BANK_OWNED 0x10000414u
#define NX_LED_BANK_APPLY 0x10000418u
#define NX_LED_BANK_RELEASE 0x1000041cu
#define NX_LED_BANK_ABI 0x3244454cu
#define NX_LED_BANK_MASK 0x2du
enum { NX_LED_BANK_QUERY_COMMAND, NX_LED_BANK_APPLY_COMMAND, NX_LED_BANK_RELEASE_COMMAND };
extern const char nx_led_system_prompt[];
typedef struct {
    void *context;
    uint32_t (*read)(void *,uint32_t);
    void (*write)(void *,uint32_t,uint32_t);
    void (*fence)(void *);
} nx_led_io;
/* Returns 1 only for an exact recognized direct command; -1 rejects a LED
 * command spelling, 0 leaves all other service paths alone. No Chinese input. */
int nx_led_command(const char *,uint32_t *,int *);
int nx_led_read(const nx_led_io *,uint32_t *);
int nx_led_set(const nx_led_io *,uint32_t,uint32_t *);
/* Fully validate with the existing parser, then apply a narrower LED-only
 * whitelist. This function cannot write MMIO or inspect the Chinese request. */
int nx_led_program(struct app_program *,const char *,size_t,struct app_result *);
int nx_led_final(const nxr_request *,int transport_complete,int cancelled,uint64_t now);
int nx_led_execute(const nx_led_io *,const struct app_result *,uint32_t *,uint32_t *);
/* Bank access is a build-time contract with the new bitstream. The default
 * NX_LED_BANK=0 refuses these operations without reading unknown CSRs. Values
 * are software shadow bits, never automatic-status or optical observations. */
int nx_led_bank_mask_valid(uint32_t);
int nx_led_bank_command(const char *,uint32_t *mask,uint32_t *values,int *kind);
int nx_led_bank_read(const nx_led_io *,uint32_t *values,uint32_t *owned);
int nx_led_bank_apply(const nx_led_io *,uint32_t mask,uint32_t values,
                      uint32_t *writes,uint32_t *observed,uint32_t *owned);
int nx_led_bank_release(const nx_led_io *,uint32_t mask,
                        uint32_t *writes,uint32_t *observed,uint32_t *owned);
/* Each validated model LED value is applied to the explicit selected mask.
 * The entire pending program is prechecked before the first atomic store. */
int nx_led_bank_execute(const nx_led_io *,const struct app_result *,uint32_t mask,
                        uint32_t *writes,uint32_t *observed,uint32_t *owned);
#endif
