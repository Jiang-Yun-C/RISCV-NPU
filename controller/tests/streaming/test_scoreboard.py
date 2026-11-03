"""Fail-closed controls for actual-byte/response/counter acceptance."""
import copy,csv,hashlib,json,tempfile,unittest
from pathlib import Path
from streaming_check import score

class ScoreboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
        source=0x80001000;dest=0xac100000;data=b'\x01\x02\x03';regions=[]
        for name,a,blob,kind in [('input',source,data,'input'),('output',dest-16,b'\xa5'*64,'output')]:
            path=self.d/(name+'.bin');path.write_bytes(blob);regions.append(dict(name=name,address=a,bytes=len(blob),path=str(path),sha256=hashlib.sha256(blob).hexdigest(),kind=kind))
        p=self.d/'expected.bin';p.write_bytes(data)
        request=[0x53543134,96,1,0,1,0,1,0,1,0,source,dest,0,0,0,0,0,3,16,16,0,0,0,0]
        result=dict(abi=0x53543134,size=104,session_lo=1,session_hi=0,sequence_lo=1,sequence_hi=0,status=0,valid=1,tiles=1,rows=1,checksum=6,payload_read=3,payload_write=3,cycles=10,load_cycles=3,compute_cycles=2,write_cycles=2,other_cycles=3)
        self.fixture=dict(regions=regions,scope='SCOREBOARD_UNIT_ONLY')
        self.golden=dict(jobs=[dict(name='copy',request=request,expected_path=str(p),rows=1,row_bytes=3,source_stride=16,destination_stride=16,checksum=6,logical_read=3,logical_write=3,status=0)])
        self.obs=dict(jobs=[dict(name='copy',start=1,stop=10,result=result,counters=dict(ar=1,r=1,aw=1,w=1,b=1,read_bytes=16,write_bytes=3,cycles=10,read_wait=0,write_wait=1))],protocol_error=0,protocol_checks=2000,stack_guard=[0xa5]*16,stack_peak=16)
        self.fields='cycle ch addr id len size burst data strb last resp'.split()
        self.rows=[dict(zip(self.fields,r)) for r in [['1','AR',f'{source:x}','1','0','4','1','0','0','0','0'],['2','R','0','1','0','0','0','030201','0','1','0'],['3','AW',f'{dest:x}','2','0','4','1','0','0','0','0'],['4','W','0','0','0','0','0','030201','7','1','0'],['5','B','0','2','0','0','0','0','0','0','0']]]
    def run_score(self):
        with (self.d/'transactions.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=self.fields);w.writeheader();w.writerows(self.rows)
        return score(self.d,self.fixture,self.golden,self.obs,self.d)
    def test_valid_byte_tail(self):self.assertGreater(self.run_score()[0].counts['data'],0)
    def test_missing_read_response(self):
        self.rows.pop(1)
        with self.assertRaisesRegex(AssertionError,'completion'):self.run_score()
    def test_duplicate_write_beat(self):
        self.rows.insert(4,copy.deepcopy(self.rows[3]))
        with self.assertRaisesRegex(AssertionError,'completion'):self.run_score()
    def test_response_before_write_data(self):
        self.rows[3],self.rows[4]=self.rows[4],self.rows[3]
        with self.assertRaisesRegex(AssertionError,'axi_response'):self.run_score()
    def test_corrupt_read_byte(self):
        self.rows[1]['data']='030200'
        with self.assertRaisesRegex(AssertionError,'read_data'):self.run_score()
    def test_corrupt_output_byte(self):
        self.rows[3]['data']='030200'
        with self.assertRaisesRegex(AssertionError,'data'):self.run_score()
    def test_missing_tail_strobe(self):
        self.rows[3]['strb']='3';self.obs['jobs'][0]['counters']['write_bytes']=2
        with self.assertRaisesRegex(AssertionError,'data'):self.run_score()
    def test_counter_forgery(self):
        self.obs['jobs'][0]['counters']['read_bytes']=3
        with self.assertRaisesRegex(AssertionError,'counters'):self.run_score()
    def test_zero_job_evidence(self):
        self.obs['jobs']=[]
        with self.assertRaisesRegex(AssertionError,'output_set'):self.run_score()
    def test_wrong_completion_identity(self):
        self.obs['jobs'][0]['result']['sequence_lo']=2
        with self.assertRaisesRegex(AssertionError,'completion'):self.run_score()
    def test_cross_4k_transaction(self):
        self.rows[0]['addr']='80000ff0';self.rows[0]['len']='1'
        with self.assertRaisesRegex(AssertionError,'axi_request'):self.run_score()
    def test_partial_write_never_valid_on_error(self):
        self.golden['jobs'][0]['status']='IO_FAULT';self.obs['jobs'][0].update(output_valid=True,drained=True,recovered=True,guard_error=True)
        with self.assertRaisesRegex(AssertionError,'fault'):self.run_score()
if __name__=='__main__':unittest.main()
