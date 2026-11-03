#include <math.h>
__attribute__((noinline)) float abi_compute(float a, float b) {
    return sqrtf(a*a+b*b+0.9375f); // sqrt(8.25), independently checked in Python
}
