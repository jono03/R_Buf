/* host test stub: only what trace_log.[ch] needs */
#ifndef FTL_CONFIG_H_
#define FTL_CONFIG_H_
#define USER_CHANNELS	4
#define USER_WAYS		2
#ifndef RBUF_ENABLE
#define RBUF_ENABLE		1
#endif
#define RBUF_ENTRY_COUNT	8
#ifndef TRACE_ENABLE
#define TRACE_ENABLE	1
#endif
#define VERIFY_PRINT	0
#endif
