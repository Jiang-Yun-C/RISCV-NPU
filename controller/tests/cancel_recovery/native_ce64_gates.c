/* Actual production CE64 idle/reset functions with a controlled MMIO boundary.
 * No C implementation of the health decision or reset protocol is substituted.
 * This bus fixture is not RTL, DDR training, numerical acceleration or hardware.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ce64_linear.h"

enum fault_mode { CLEAN, QUARANTINE, HOLD_DRAIN, HOLD_EPOCH, STICKY_BRIDGE, HOLD_RELEASE };
typedef struct {
    uint32_t bridge_status,bridge_control,epoch,status,reset_status,outstanding;
    unsigned mode,reads,writes,fences,reset_requested,polls,epoch_before,drain_proven;
    unsigned releases,early_releases,ack_writes;
    uint64_t ticks;
} fixture_bus;
static uint64_t observer_ticks;
uint64_t nx_port_ticks(void){return ++observer_ticks;}

static void check(int condition,const char *name,const fixture_bus *bus,int rc){
    printf("{\"check\":\"%s\",\"passed\":%s,\"rc\":%d,\"mmio_reads\":%u,\"mmio_writes\":%u,\"epoch\":%u,\"bridge_control\":%u,\"reset_polls\":%u,\"early_releases\":%u}\n",
           name,condition?"true":"false",rc,bus->reads,bus->writes,bus->epoch,bus->bridge_control,bus->polls,bus->early_releases);
    if(!condition)exit(1);
}
static void progress(fixture_bus *bus){
    if(!bus->reset_requested)return;
    bus->polls++;
    if(bus->mode==QUARANTINE||bus->polls<3)return;
    if(bus->mode!=HOLD_EPOCH)bus->epoch=bus->epoch_before+1;
    if(bus->mode!=HOLD_DRAIN){
        bus->bridge_status=1;bus->outstanding=0;
        bus->status=CE64_ST_IDLE|CE64_ST_DRAINED|CE64_ST_ISOLATE;
    }
}
static uint32_t read32(void *cookie,uint32_t address){
    fixture_bus *bus=cookie;bus->reads++;
    if(address==NX_BRIDGE_STATUS)return bus->bridge_status;
    if(address==NX_BRIDGE_CONTROL)return bus->bridge_control;
    if(address==NX_BRIDGE_ADDRESS)return 0;
    if(address==CE64_MMIO_BASE+CE64_EPOCH){progress(bus);return bus->epoch;}
    if(address==CE64_MMIO_BASE+CE64_STATUS){
        if(bus->reset_requested&&bus->epoch==bus->epoch_before+1&&
           (bus->bridge_status&1)&&(bus->status&CE64_ST_DRAINED))bus->drain_proven=1;
        return bus->status;
    }
    if(address==CE64_MMIO_BASE+CE64_RESET_STATUS)return bus->reset_status;
    if(address==CE64_MMIO_BASE+CE64_OUTSTANDING)return bus->outstanding;
    if(address==CE64_MMIO_BASE+CE64_ID)return CE64_DESC_MAGIC;
    if(address==CE64_MMIO_BASE+CE64_VERSION)return NX_API_VERSION_V2;
    fprintf(stderr,"unexpected gate fixture MMIO read %08x\n",address);exit(2);
}
static void write32(void *cookie,uint32_t address,uint32_t value){
    fixture_bus *bus=cookie;bus->writes++;
    if(address==NX_BRIDGE_CONTROL){
        if(value==0){
            bus->releases++;if(!bus->drain_proven)bus->early_releases++;
            if(bus->mode==HOLD_RELEASE)return;
        }
        bus->bridge_control=value;return;
    }
    if(address==NX_BRIDGE_CLEAR){
        if(bus->mode==STICKY_BRIDGE)bus->bridge_status|=4;
        else bus->bridge_status&=~6u;
        return;
    }
    if(address==NX_BRIDGE_IRQ||address==CE64_MMIO_BASE+CE64_IRQ_STATUS||
       address==CE64_MMIO_BASE+CE64_CLEAR_SHADOW)return;
    if(address==CE64_MMIO_BASE+CE64_ACK){bus->ack_writes++;return;}
    if(address==CE64_MMIO_BASE+CE64_CONTROL){
        if(value&CE64_CTL_ISOLATE)bus->status|=CE64_ST_ISOLATE;
        if(value&CE64_CTL_RESET_REQUEST){
            bus->reset_requested=1;bus->polls=0;bus->epoch_before=bus->epoch;
            bus->bridge_status=0;bus->outstanding=3;bus->status=CE64_ST_ISOLATE;
            bus->reset_status=bus->mode==QUARANTINE?2u:0u;
        }
        return;
    }
    fprintf(stderr,"unexpected gate fixture MMIO write %08x\n",address);exit(2);
}
static uint64_t ticks(void *cookie){return ++((fixture_bus *)cookie)->ticks;}
static void fence(void *cookie){((fixture_bus *)cookie)->fences++;}
static void init(fixture_bus *bus,nx_ce64_context *context,nx_linear_binding *binding){
    *bus=(fixture_bus){.bridge_status=1,.epoch=7,.status=CE64_ST_IDLE|CE64_ST_DRAINED};
    *context=(nx_ce64_context){.base={.initialized=1,.state=NX_ACCEL_IDLE,.session=19,
        .io={.cookie=bus,.read32=read32,.write32=write32,.ticks=ticks,.fence=fence,.tick_hz=125000000}},
        .epoch=7,.acquired_generation=9,.binding=binding};
    *binding=(nx_linear_binding){.context=&context->base};
}
static void health_gates(void){
    fixture_bus bus;nx_ce64_context context;nx_linear_binding binding;
    init(&bus,&context,&binding);
    int rc=nx_ce64_idle_safe(&context);check(rc==NX_OK,"clean_idle_including_previous_ack_generation",&bus,rc);
#define BAD(name,change,restore) do {change;rc=nx_ce64_idle_safe(&context);check(rc!=NX_OK,name,&bus,rc);restore;} while(0)
    BAD("software_running_rejected",context.base.state=NX_ACCEL_RUNNING,context.base.state=NX_ACCEL_IDLE);
    BAD("software_fault_rejected",context.base.state=NX_ACCEL_FAULTED,context.base.state=NX_ACCEL_IDLE);
    BAD("binding_context_mismatch_rejected",binding.context=NULL,binding.context=&context.base);
    BAD("hardware_not_idle_rejected",bus.status=CE64_ST_DRAINED,bus.status=CE64_ST_IDLE|CE64_ST_DRAINED);
    BAD("hardware_running_rejected",bus.status|=CE64_ST_RUNNING,bus.status&=~CE64_ST_RUNNING);
    BAD("held_completion_ack_rejected",bus.status|=CE64_ST_COMPLETION_PENDING,bus.status&=~CE64_ST_COMPLETION_PENDING);
    BAD("hardware_fault_rejected",bus.status|=CE64_ST_FAULTED,bus.status&=~CE64_ST_FAULTED);
    BAD("native_quarantine_rejected",bus.reset_status=2,bus.reset_status=0);
    BAD("epoch_exhaustion_rejected",bus.reset_status=4,bus.reset_status=0);
    BAD("outstanding_transfer_rejected",bus.outstanding=1,bus.outstanding=0);
    BAD("epoch_mismatch_rejected",bus.epoch=8,bus.epoch=7);
    BAD("bridge_owned_rejected",bus.bridge_control=1,bus.bridge_control=0);
    BAD("bridge_not_drained_rejected",bus.bridge_status=0,bus.bridge_status=1);
    BAD("bridge_fault_rejected",bus.bridge_status=5,bus.bridge_status=1);
#undef BAD
    check(bus.writes==0,"idle_health_gate_never_writes_to_hide_an_error",&bus,0);
    rc=nx_ce64_idle_safe(&context);check(rc==NX_OK,"restored_clean_observation_is_healthy",&bus,rc);
}
static void reset_gate(unsigned mode,const char *name){
    fixture_bus bus;nx_ce64_context context;nx_linear_binding binding;
    init(&bus,&context,&binding);bus.mode=mode;
    uint64_t session=0;int rc=nx_ce64_reset_session(&context,32,&session);
    if(mode==CLEAN){
        check(rc==NX_OK&&session==20&&context.epoch==8&&context.base.state==NX_ACCEL_IDLE,
              "real_reset_advances_epoch_and_session_after_drain",&bus,rc);
        check(bus.polls>=3&&bus.drain_proven&&bus.releases==1&&!bus.early_releases,
              "real_reset_waits_for_async_epoch_and_drain_proof_before_release",&bus,rc);
        check(context.acquired_generation==0&&context.base.sequence==0&&!context.base.kv_valid,
              "real_reset_clears_old_generation_and_kv_ownership",&bus,rc);
        rc=nx_ce64_idle_safe(&context);check(rc==NX_OK,"post_reset_actual_health_gate_passes",&bus,rc);
    }else{
        check(rc!=NX_OK&&session==0&&context.base.state==NX_ACCEL_FAULTED&&bus.bridge_control==3,
              name,&bus,rc);
        check(!bus.early_releases,"failed_reset_never_releases_before_drain_proof",&bus,rc);
        rc=nx_ce64_idle_safe(&context);check(rc!=NX_OK,"failed_reset_cannot_pass_post_health",&bus,rc);
        fixture_bus other_bus;nx_ce64_context other;nx_linear_binding other_binding;
        init(&other_bus,&other,&other_binding);
        rc=nx_ce64_idle_safe(&other);check(rc!=NX_OK,"failed_reset_retains_global_owner_against_other_context",&other_bus,rc);
        rc=nx_ce64_reset_session(&other,32,&session);
        check(rc==NX_EBUSY&&other_bus.writes==0,"other_context_cannot_reset_through_retained_owner",&other_bus,rc);
    }
}
int main(int argc,char **argv){
    if(argc!=2)return 2;
    nx_diag_init();
    if(!strcmp(argv[1],"health"))health_gates();
    else if(!strcmp(argv[1],"healthy_reset"))reset_gate(CLEAN,"unused");
    else if(!strcmp(argv[1],"quarantine"))reset_gate(QUARANTINE,"quarantined_native_reset_stays_isolated");
    else if(!strcmp(argv[1],"drain_timeout"))reset_gate(HOLD_DRAIN,"undrained_native_reset_stays_isolated");
    else if(!strcmp(argv[1],"epoch_timeout"))reset_gate(HOLD_EPOCH,"unchanged_epoch_reset_stays_isolated");
    else if(!strcmp(argv[1],"sticky_bridge_fault"))reset_gate(STICKY_BRIDGE,"unclearable_bridge_fault_stays_isolated");
    else if(!strcmp(argv[1],"release_failure"))reset_gate(HOLD_RELEASE,"failed_owner_release_stays_isolated");
    else return 2;
    return 0;
}
