#ifndef NX_APPLICATION_H
#define NX_APPLICATION_H
#include <stddef.h>
#include <stdint.h>
#define APP_TEXT_MAX 4096
#define APP_ACTION_MAX 8
#define APP_TTL_CYCLES 1000000u
enum app_status { APP_OK,APP_FORMAT,APP_RANGE,APP_UNSUPPORTED,APP_STATE,APP_STALE,
    APP_NACK,APP_TIMEOUT,APP_DUPLICATE,APP_REQUEST_ID };
struct app_state { int32_t temperature; uint32_t light,epoch,sampled_at; };
struct app_action { uint32_t device,value; }; /* 0 LED, 1 PWM */
struct app_result { struct app_action actions[8]; uint32_t count,read_mask; };
struct app_token { int kind,child,next,count; int32_t number; char string[24]; };
struct app_program { struct app_token tokens[256]; int used,root; };
int app_parse(struct app_program *,const char *,size_t);
int app_evaluate(const struct app_program *,const struct app_state *,uint32_t,uint32_t,struct app_result *);
const char *app_status_name(int);
uint32_t app_fingerprint(const char *,size_t);
#endif
