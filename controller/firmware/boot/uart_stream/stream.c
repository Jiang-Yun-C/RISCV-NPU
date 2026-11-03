#include "stream.h"
static nx_uart_io io;
static uint8_t packet[536];
static uint32_t expected,last_sequence,last_frame_crc,last_payload_crc;
static int pending,have_last;
static uint32_t word(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint32_t crc(const uint8_t *p,unsigned n){
    uint32_t c=~0u;while(n--){c^=*p++;for(unsigned i=0;i<8;i++)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}return ~c;
}
static void response(uint32_t seq,uint32_t status,uint32_t value){
    uint32_t words[6]={NX_UART_ACK,seq,status,expected,value,0};words[5]=crc((const uint8_t *)words,20);
    io.put(io.cookie,(const uint8_t *)words,sizeof(words));
}
void nx_uart_init(const nx_uart_io *value){
    io=*value;expected=last_sequence=last_frame_crc=last_payload_crc=0;pending=have_last=0;
}
/* A sector ACK is deferred until the parser requests its successor. The host
 * cannot fill the 64-byte FIFO while hashing/storing the previous sector. */
static void commit(void){if(pending){response(last_sequence,0,last_payload_crc);pending=0;}}
static int receive(void){
    uint32_t magic=0;uint64_t deadline=0;uint8_t v;
    do{
        int rc=io.get(io.cookie,deadline,&v);if(rc<0)return -1;if(!rc)return NX_UART_TIMEOUT;
        if(!deadline)deadline=io.ticks(io.cookie)+io.frame_ticks;
        magic=(magic>>8)|((uint32_t)v<<24);
    }while(magic!=NX_UART_MAGIC);
    packet[0]='U';packet[1]='2';packet[2]='5';packet[3]='1';
    for(unsigned i=4;i<sizeof(packet);i++){
        int rc=io.get(io.cookie,deadline,packet+i);if(rc<0)return -1;if(!rc)return NX_UART_TIMEOUT;
    }
    return crc(packet,532)==word(packet+532)?0:NX_UART_CRC;
}
static int control(void){
    if(word(packet+8)||word(packet+16))return 0;
    for(unsigned i=20;i<532;i++)if(packet[i])return 0;
    return 1;
}
static int duplicate(void){
    return have_last&&word(packet+4)==NX_UART_DATA&&word(packet+8)==expected-1&&
        word(packet+12)==last_sequence&&word(packet+16)==512&&word(packet+532)==last_frame_crc;
}
static int read_frame(void){
    for(;;){
        int rc=receive();if(rc<0)return -1;
        if(rc){response(rc==NX_UART_CRC?word(packet+12):0,(uint32_t)rc,0);continue;}
        if(duplicate()){response(last_sequence,0,last_payload_crc);continue;}
        if(word(packet+4)==NX_UART_RESET&&control()&&word(packet+12)==0){
            response(0,0,0);io.reset(io.cookie);return -1;
        }
        return 0;
    }
}
int nx_uart_sector(uint32_t lba,uint8_t out[512]){
    if(lba!=expected||!out||expected==UINT32_MAX)return NX_UART_SEQUENCE;
    commit();
    for(;;){
        if(read_frame()<0)return NX_UART_TIMEOUT;
        uint32_t command=word(packet+4),address=word(packet+8),seq=word(packet+12),bytes=word(packet+16);
        if(command!=NX_UART_DATA||bytes!=512){response(seq,NX_UART_FORMAT,0);continue;}
        if(address!=expected||seq!=expected+1){response(seq,NX_UART_SEQUENCE,0);continue;}
        for(unsigned i=0;i<512;i++)out[i]=packet[20+i];
        expected++;last_sequence=seq;
        last_frame_crc=word(packet+532);last_payload_crc=crc(packet+20,512);have_last=pending=1;return 0;
    }
}
int nx_uart_finish(void){
    if(!pending||!have_last)return NX_UART_STATE;
    int rc=io.seal(io.cookie);if(rc)return rc;
    commit();
    /* Final DATA ACK confirms authentication/seal. START is separate, so a
     * lost final ACK can be retried while the verified loader still owns RX. */
    for(;;){
        if(read_frame()<0)return NX_UART_TIMEOUT;
        uint32_t seq=word(packet+12);
        if(word(packet+4)==NX_UART_START&&control()&&seq==expected+1){response(seq,0,0);return 0;}
        response(seq,NX_UART_STATE,0);
    }
}
void nx_uart_reject(uint32_t error){response(have_last?last_sequence:0,error,0);pending=0;}
