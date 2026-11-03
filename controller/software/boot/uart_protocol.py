"""NXU1 wire format. This packer is shared by host download tools and fixtures."""
import struct
import zlib

BASE=0xb4000000
LIMIT=0xb7ff0000
MAX_IMAGE=65536
MAX_CHUNK=256
BEGIN,DATA,RUN=1,2,3
OK,DUP,CRC,RANGE,SEQUENCE,TIMEOUT,INCOMPLETE,FORMAT,IMAGE_CRC=range(9)

def image_range(address,length,entry):
    return (BASE<=address<LIMIT and 0<length<=MAX_IMAGE and length<=LIMIT-address
            and address%4==entry%4==0 and address<=entry and entry-address<=length-4)

def packet(command,sequence,address,length,entry=0,image_crc=0,payload=b''):
    if (command==DATA and len(payload)!=length) or (command!=DATA and payload):
        raise ValueError('payload length differs from command format')
    wire=struct.pack('<4s6I',b'NXU1',command,sequence,address,length,entry,image_crc)+payload
    return wire+struct.pack('<I',zlib.crc32(wire))

def response(wire):
    if len(wire)!=20 or wire[:4]!=b'NXAK' or zlib.crc32(wire[:16])!=struct.unpack_from('<I',wire,16)[0]:
        raise ValueError('invalid UART response length, magic or CRC')
    return struct.unpack_from('<3I',wire,4)

def download_packets(image,address=BASE,entry=BASE):
    if not image_range(address,len(image),entry):raise ValueError('illegal image address, size or entry')
    crc=zlib.crc32(image)
    yield packet(BEGIN,0,address,len(image),entry,crc)
    seq=1
    for offset in range(0,len(image),MAX_CHUNK):
        chunk=image[offset:offset+MAX_CHUNK]
        yield packet(DATA,seq,address+offset,len(chunk),payload=chunk)
        seq+=1
    yield packet(RUN,seq,address,len(image),entry,crc)
