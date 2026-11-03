"""The SD service requires both SD publication and actual hardware seal feedback."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]


class BootStatus(unittest.TestCase):
    def test_actual_header_sd_and_uart(self):
        code=r'''
#define _GNU_SOURCE
#include <sys/mman.h>
#include "boot_status.h"
int main(void){
    if(mmap((void *)0x10000000,0x3000,PROT_READ|PROT_WRITE,
        MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)!=(void *)0x10000000)return 90;
    for(unsigned sd=0;sd<3;sd++)for(unsigned seal=0;seal<2;seal++)for(unsigned uart=0;uart<2;uart++){
        *(volatile uint32_t *)0x10002018=sd;
        *(volatile uint32_t *)0x10000208=seal<<9;
        *(volatile uint32_t *)0x100000e0=1|(uart<<1);
#ifdef NX_T25_UART
        int expected=uart;
#else
        int expected=sd==1&&seal;
#endif
        if(nxr_boot_ready()!=expected)return 1;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder);source=f/'test.c';source.write_text(code)
            for define in ([],['-DNX_T25_UART']):
                binary=f/('uart' if define else 'sd')
                subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror',*define,
                    '-I',str(ROOT/'firmware/runtime/board'),str(source),'-o',str(binary)],check=True,capture_output=True)
                subprocess.run([str(binary)],check=True,capture_output=True)
