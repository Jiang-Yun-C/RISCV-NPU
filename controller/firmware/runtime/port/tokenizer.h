#ifndef NXT_TOKENIZER_H
#define NXT_TOKENIZER_H
#include <stddef.h>
#include <stdint.h>
#define NXT_TEXT_MAX 4096u
#define NXT_NORMAL_MAX 16384u
enum { NXT_OK=0, NXT_ARGUMENT=-1, NXT_BOUNDS=-4, NXT_UTF8=-12, NXT_FORMAT=-13 };
typedef struct { const uint8_t *data; uint32_t bytes, vocab; } nxt_tokenizer;
typedef struct {
    uint32_t cp[NXT_NORMAL_MAX], ids[NXT_NORMAL_MAX], lengths[NXT_NORMAL_MAX];
    uint8_t normalized[NXT_NORMAL_MAX];
} nxt_work;
typedef struct { const char *role, *text; size_t length; } nxt_message;
typedef struct { uint8_t pending[4]; uint32_t count; } nxt_decoder;
int nxt_init(nxt_tokenizer *, const void *, size_t);
int nxt_encode(const nxt_tokenizer *, nxt_work *, const char *, size_t, uint32_t *, size_t, size_t *);
int nxt_template(const nxt_message *, size_t, int generation_prompt, char *, size_t, size_t *);
/* Exact automatic system prefix used by nxt_template; read-only static bytes. */
const char *nxt_system_prefix(size_t *);
/* UTF-8 output is committed only when the full scalar is available. final=1
 * flushes a truncated sequence as U+FFFD, matching official errors=replace. */
int nxt_decode(const nxt_tokenizer *, nxt_decoder *, uint32_t token, int skip_special,
               int final, char *, size_t, size_t *);
#endif
