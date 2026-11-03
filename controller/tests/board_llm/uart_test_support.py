import array
import fcntl
import os
from pathlib import Path
import select
import shutil
import struct
import subprocess
import termios

ROOT=Path(__file__).resolve().parents[2]


def build_native(destination,trusted_header):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    (destination/'trusted.h').write_text(trusted_header)
    stream=ROOT/'firmware/boot/uart_stream';loader=ROOT/'firmware/boot/sd_loader';port=ROOT/'firmware/runtime/port'
    binary=destination/'native-loader'
    command=['gcc','-std=c11','-O2','-fno-strict-aliasing','-ffunction-sections','-fdata-sections','-Wl,--gc-sections',
        '-Wall','-Wextra','-Werror','-Wno-unused-const-variable','-Wno-misleading-indentation',
        '-I',str(destination),'-I',str(stream),'-I',str(loader),'-I',str(port),
        str(ROOT/'tests/board_llm/uart_native.c'),str(stream/'stream.c'),str(stream/'pack.c'),str(loader/'sha256.c'),str(port/'runtime.c'),'-o',str(binary)]
    subprocess.run(command,check=True,capture_output=True,text=True)
    return binary


class PipeLink:
    def __init__(self,process,drop_sequence=None):
        self.process=process;self.drop_sequence=drop_sequence;self.dropped=False
        self.pending=bytearray();self.ready=bytearray()
    def _pump(self,wait=0):
        if select.select([self.process.stdout],[],[],wait)[0]:
            self.pending.extend(os.read(self.process.stdout.fileno(),4096))
        while len(self.pending)>=24:
            ack=bytes(self.pending[:24]);del self.pending[:24]
            if self.drop_sequence is not None and not self.dropped and struct.unpack_from('<2I',ack)==(0x41353255,self.drop_sequence):
                self.dropped=True
            else:self.ready.extend(ack)
    @property
    def in_waiting(self):
        self._pump();return len(self.ready)
    def read(self,n):
        if not self.ready:self._pump(.01)
        data=bytes(self.ready[:n]);del self.ready[:n];return data
    def write(self,data):return os.write(self.process.stdin.fileno(),data)
    def flush(self):pass


def launch(binary,app_bytes):
    return subprocess.Popen([str(binary),str(app_bytes)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)


def stop(process):
    if process.poll() is None:process.kill()
    process.wait(timeout=5)
    for stream in (process.stdin,process.stdout,process.stderr):stream.close()
