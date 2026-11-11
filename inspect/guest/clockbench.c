/* Cost of clock reads and of a plain syscall. If clock_gettime costs about
   as much as getpid, the vDSO fast path is off and every clock read is a syscall. */
#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e9 + t.tv_nsec; }
int main(void) {
  struct timespec t; long n; double a, b;
  n = 5000000; a = now(); for (long i = 0; i < n; i++) clock_gettime(CLOCK_MONOTONIC, &t); b = now();
  printf("PROBE clock_gettime_monotonic_ns=%.1f\n", (b - a) / n);
  n = 2000000; a = now(); for (long i = 0; i < n; i++) clock_gettime(CLOCK_REALTIME, &t); b = now();
  printf("PROBE clock_gettime_realtime_ns=%.1f\n", (b - a) / n);
  n = 2000000; a = now(); for (long i = 0; i < n; i++) syscall(SYS_getpid); b = now();
  printf("PROBE getpid_syscall_ns=%.1f\n", (b - a) / n);
  return 0;
}
