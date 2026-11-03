"""Browser QA; all serial interactions in this test use an explicit fake device.

Run with a Python environment containing Playwright and its Chromium browser:
python software/demo_console/tests/browser_smoke.py --url http://localhost:8765
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import time

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from software.demo_console.server import ConsoleServer, SerialBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8765")
    parser.add_argument("--output", default="build/demo-qa/screenshots")
    args = parser.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    samples = json.loads((ROOT / "software/demo_console/static/replays.json").read_text())
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, reduced_motion="reduce")
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url, wait_until="networkidle")
        page.screenshot(path=str(out / "live-1080p.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth") == 1920
        page.locator("#mode-replay").click()
        assert page.locator("#result-text").inner_text() == "你好！很高兴能与你交流。"
        assert "1,347.68" in page.locator("#metric-time").inner_text()
        assert "6,422" in page.locator("#metric-calls").inner_text()
        assert "旧 v7" in page.locator("#source-detail").inner_text()
        page.screenshot(path=str(out / "replay-1080p.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth") == 1920

        # Byte-level framing, complete multiline output, missing records and invalid input.
        checks = page.evaluate("""async samples => {
          const {T25Parser, commandFor, metricValues} = await import('./protocol.js');
          const enc = new TextEncoder(); let tests = 0;
          const check = (value, name) => { if (!value) throw new Error(name); tests++; };
          for (const sample of samples) for (const size of [1,2,7,31,65536]) {
            const events = []; const parser = new T25Parser(e => events.push(e));
            const bytes = enc.encode(sample.raw);
            for (let i=0;i<bytes.length;i+=size) parser.feed(bytes.slice(i,i+size));
            parser.finish();
            const results = events.filter(e=>e.type==='result');
            check(results.length===1 && results[0].complete, sample.id+' chunk '+size);
            check(events.filter(e=>e.type==='profile')[0].profile.length===8, '8 cumulative operators');
          }
          const latest = samples[1].raw;
          for (const raw of [latest.replace(/^T25 IDS .*\\n/m,''), latest.replace(/^T25 METRICS .*\\n/m,''), latest.replace('generated=0000000000000001','generated=0000000000000002'), latest.replace(/^T25 STEP .*\\n/m,'')]) {
            const events=[]; let failed=false;
            try { const parser=new T25Parser(e=>events.push(e));parser.feed(enc.encode(raw));parser.finish(); } catch {failed=true;}
            check(failed || !events.some(e=>e.type==='result' && e.complete), 'incomplete cannot pass');
          }
          const multiline = latest.replace('T25 TEXT er\\n', 'T25 TEXT first\\nT25 READY\\nlast\\n');
          const events=[]; const parser=new T25Parser(e=>events.push(e));parser.feed(enc.encode(multiline));parser.finish();
          check(events.find(e=>e.type==='result').text==='first\\nT25 READY\\nlast', 'multiline payload boundary');
          check(metricValues(events.find(e=>e.type==='result').metrics).speed===null,'single token has no decode rate');
          const errors=[];new T25Parser(e=>errors.push(e)).feed(enc.encode('T25 ERROR fffffffc\\nT25 READY\\n'));
          check(errors.some(e=>e.type==='result'&&!e.complete),'board error not success');
          for (const text of [':reload','a\\nb','a\\r','a\\0b','中'.repeat(1366)]) { let failed=false;try {commandFor('text',text)}catch{failed=true}check(failed,'invalid text'); }
          for(const [text,max] of [['151936',1],['0',0],['0',129],['-1',1]]) {let failed=false;try {commandFor('ids',text,max)}catch{failed=true}check(failed,'invalid ids');}
          check(commandFor('text','你好')==='你好','UTF8 request');
          return tests;
        }""", samples)
        print(f"Parser assertions: {checks}")
        page.locator("#replay-select").select_option("32-tokens")
        assert "A. locker\nB. lock" in page.locator("#result-text").inner_text()
        assert "0.0283" in page.locator("#metric-speed").inner_text()
        page.locator("#replay-select").select_option("one-token")
        assert page.locator("#result-text").inner_text() == "er"
        assert "—" in page.locator("#metric-speed").inner_text()
        page.locator("#replay-play").click(); page.locator("#replay-play").click()
        page.locator("#replay-end").click()
        assert page.locator("#result-text").inner_text() == "er"
        page.locator('[data-view="performance"]').click()
        assert page.locator(".profile-row").count() == 8
        assert "累计" in page.locator("#profile-caption").inner_text()
        page.screenshot(path=str(out / "performance-1080p.png"), full_page=True)
        for width, height in [(1600,900),(1440,900),(390,844)]:
            page.set_viewport_size({"width":width,"height":height})
            page.locator('[data-view="demo"]').click()
            assert page.evaluate("document.documentElement.scrollWidth") == width
            # Added timing panel may legitimately require vertical scrolling.
            if width==390: page.screenshot(path=str(out/"mobile.png"),full_page=True)
        page.close()

        # Exercise browser USB serial path with a fake CP2102, without any hardware.
        context = browser.new_context(viewport={"width":1600,"height":900}, accept_downloads=True)
        context.add_init_script("""window.fakeUART={writes:[],signals:null,closed:false};
          Object.defineProperty(navigator,'serial',{value:{requestPort:async()=>{
            let controller;
            const port={getInfo:()=>({usbVendorId:0x10c4,usbProductId:0xea60}),
              open:async()=>{},setSignals:async s=>{window.fakeUART.signals=s},
              close:async()=>{window.fakeUART.closed=true},
              readable:new ReadableStream({start(c){controller=c},cancel(){}}),
              writable:new WritableStream({write(data){
                const text=new TextDecoder().decode(data);window.fakeUART.writes.push(text);
                const raw=text==='\\n'?'T25 READY\\n':text.startsWith('error')?'T25 ERROR fffffffc\\nT25 READY\\n':window.fakeReply;
                setTimeout(()=>controller.enqueue(new TextEncoder().encode(raw)),120);
              }})};return port;}}});""" + "window.fakeReply=" + json.dumps(samples[1]["raw"]) + ";")
        page=context.new_page();page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.url,wait_until="networkidle")
        page.locator("#run-button").click();page.locator("#connect-confirm").click()
        expect(page.locator('#connection-label')).to_have_text('板端服务就绪')
        assert page.evaluate("window.fakeUART.writes") == ["\n"]
        assert page.evaluate("window.fakeUART.signals") == {"dataTerminalReady":False,"requestToSend":False}
        page.locator('[data-preset="token"]').click();page.locator("#run-button").click()
        assert page.locator("#run-button").is_disabled()
        expect(page.locator('#result-text')).to_have_text('er')
        assert page.evaluate("window.fakeUART.writes") == ["\n",":ids 1 0 255 1023\n"]
        assert page.locator("#connection-label").inner_text() == "板端服务就绪"
        with page.expect_download() as exported: page.locator("#export-button").click()
        target=out/"fake-serial-export.json";exported.value.save_as(str(target))
        record=json.loads(target.read_text());assert record["complete"] and record["source"]=="live"
        page.locator('[data-preset="custom"]').click();page.locator("#prompt").fill("error");page.locator("#run-button").click()
        expect(page.locator('#result-text')).to_contain_text('T25 ERROR')
        assert page.locator("#connection-label").inner_text() == "板端服务就绪"
        page.locator('[data-view="history"]').click();assert page.locator(".history-item").count()==2
        page.locator(".history-item").last.get_by_role("button",name="查看记录").click()
        assert page.locator("#result-text").inner_text()=="er"
        assert page.evaluate("window.fakeUART.closed")
        assert page.locator(".history-item").count()==2
        print("Browser serial: sync, DTR/RTS, bounded request, error, history, export, disconnect passed")
        context.close()

        # Full HTTP bridge path with a fake serial device: no model, no physical IO.
        class FakePort:
            def __init__(self,*a,**kw): self.pending=bytearray(); self.writes=[]; self.dtr=self.rts=True
            def open(self): assert not self.dtr and not self.rts
            def close(self): pass
            def flush(self): pass
            @property
            def in_waiting(self): return len(self.pending)
            def read(self,n):
                if not self.pending: time.sleep(.005);return b""
                data=bytes(self.pending[:n]);del self.pending[:n];return data
            def write(self,data):
                self.writes.append(data);self.pending.extend(b"T25 READY\n" if data==b"\n" else samples[1]["raw"].encode());return len(data)
        device=FakePort();bridge=SerialBridge(serial_factory=lambda *a,**kw:device)
        bridge.ports=lambda:dict(available=True,ports=[dict(device="COM10",description="QA Fake CP2102",serial="0001",expected=True)])
        server=ConsoleServer(("127.0.0.1",0),bridge);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            page=browser.new_page(viewport={"width":1600,"height":900});page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto(f"http://localhost:{server.server_port}",wait_until="networkidle")
            page.locator("#connection-status").click();page.locator("#transport-kind").select_option("python")
            expect(page.locator('#python-port')).to_have_value('COM10')
            page.locator("#connect-confirm").click()
            expect(page.locator('#connection-label')).to_have_text('板端服务就绪')
            page.locator('[data-preset="token"]').click();page.locator("#run-button").click()
            expect(page.locator('#result-text')).to_have_text('er')
            assert device.writes==[b"\n",b":ids 1 0 255 1023\n"]
            # Refresh and explicitly reconnect the same tab; the server reuses its owner.
            page.reload(wait_until="networkidle");page.locator("#connection-status").click();page.locator("#transport-kind").select_option("python")
            expect(page.locator('#python-port')).to_have_value('COM10');page.locator("#connect-confirm").click()
            expect(page.locator('#connection-label')).to_have_text('板端服务就绪')
            page.locator("#connection-status").click();page.locator("#disconnect-button").click()
            page.close(); print("HTTP serial bridge: full browser integration and reconnect passed")
        finally:
            bridge.disconnect();server.shutdown();server.server_close();thread.join()
        browser.close()
    assert not errors, errors
    print("PASS: frontend rendering, replay, protocol, fake Web Serial and fake HTTP bridge; zero browser errors")


if __name__ == "__main__":
    main()
