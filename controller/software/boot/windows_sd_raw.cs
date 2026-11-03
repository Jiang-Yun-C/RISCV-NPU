using System;
using System.IO;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Collections.Generic;
using Microsoft.Win32.SafeHandles;

// Sector-aligned unbuffered device I/O. PowerShell resolves/locks the exact
// approved USB identity; this layer verifies the opened handle's disk/length.
public static class NxSdRaw {
    const uint Read=0x80000000, Write=0x40000000, NoBuffer=0x20000000, Through=0x80000000;
    const int Chunk=65536;
    static string auditPath;
    static int splitReads;
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern SafeFileHandle CreateFile(string p,uint a,uint share,IntPtr sa,uint mode,uint flags,IntPtr template);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool ReadFile(SafeFileHandle h,IntPtr buffer,uint bytes,out uint done,IntPtr over);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool WriteFile(SafeFileHandle h,IntPtr buffer,uint bytes,out uint done,IntPtr over);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool FlushFileBuffers(SafeFileHandle h);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool SetFilePointerEx(SafeFileHandle h,long distance,out long result,uint method);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool DeviceIoControl(SafeFileHandle h,uint code,IntPtr input,uint ins,byte[] output,uint outs,out uint done,IntPtr over);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern IntPtr VirtualAlloc(IntPtr address,UIntPtr size,uint allocation,uint protection);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool VirtualFree(IntPtr address,UIntPtr size,uint kind);
    static void Require(bool ok,string what) { if(!ok)throw new Win32Exception(Marshal.GetLastWin32Error(),what); }
    static SafeFileHandle Open(string path,uint access,uint flags) {
        var h=CreateFile(path,access,3,IntPtr.Zero,3,flags,IntPtr.Zero);
        if(h.IsInvalid){h.Dispose();throw new Win32Exception(Marshal.GetLastWin32Error(),"Open "+path);}return h;
    }
    static void Seek(SafeFileHandle h,long pos) {long actual;Require(SetFilePointerEx(h,pos,out actual,0)&&actual==pos,"Seek");}
    static void ReadExact(SafeFileHandle h,IntPtr p,int n){
        int total=0;
        while(total<n){
            long start;Require(SetFilePointerEx(h,0,out start,1),"Read position");
            uint done;bool ok=ReadFile(h,IntPtr.Add(p,total),(uint)(n-total),out done,IntPtr.Zero);
            int error=ok?0:Marshal.GetLastWin32Error();
            if(!ok||done==0||done%512!=0){
                if(auditPath!=null)File.AppendAllText(auditPath,start+",READ_ERROR,"+(n-total)+","+done+","+error+"\n");
                // A failed larger request supplies no trusted bytes. Re-read
                // every sector independently, requiring success for all of them.
                if(!ok&&error==23&&n-total>512){
                    splitReads++;Seek(h,start);
                    for(int off=total;off<n;off+=512)ReadExact(h,IntPtr.Add(p,off),512);
                    return;
                }
                throw new IOException("Exact raw read offset="+start+" requested="+(n-total)+" returned="+done+" win32="+error,new Win32Exception(error));
            }
            total+=(int)done;
        }
    }
    static string Hex(byte[] b){return BitConverter.ToString(b).Replace("-","").ToLowerInvariant();}
    public static SafeFileHandle LockVolume(string path){
        var h=Open(path,Read|Write,0);uint done;
        try {
            Require(DeviceIoControl(h,0x90018,IntPtr.Zero,0,null,0,out done,IntPtr.Zero),"FSCTL_LOCK_VOLUME "+path);
            Require(DeviceIoControl(h,0x90020,IntPtr.Zero,0,null,0,out done,IntPtr.Zero),"FSCTL_DISMOUNT_VOLUME "+path);
            return h;
        }catch{h.Dispose();throw;}
    }
    static void CheckDevice(SafeFileHandle h,int number,long bytes){
        uint done;var len=new byte[8];var dev=new byte[12];
        Require(DeviceIoControl(h,0x7405c,IntPtr.Zero,0,len,8,out done,IntPtr.Zero)&&done==8,"IOCTL_DISK_GET_LENGTH_INFO");
        if(BitConverter.ToInt64(len,0)!=bytes)throw new IOException("Opened disk size changed");
        Require(DeviceIoControl(h,0x2d1080,IntPtr.Zero,0,dev,12,out done,IntPtr.Zero)&&done==12,"IOCTL_STORAGE_GET_DEVICE_NUMBER");
        if(BitConverter.ToInt32(dev,0)!=7||BitConverter.ToInt32(dev,4)!=number)throw new IOException("Opened disk number/type changed");
    }
    // testFile is used only by SelfTest below, never exposed by the CLI.
    static Dictionary<string,object> Run(string device,int number,long diskBytes,string image,string expected,string backup,string readback,bool testFile){
        var result=new Dictionary<string,object>();IntPtr aligned=IntPtr.Zero;
        using(var input=new FileStream(image,FileMode.Open,FileAccess.Read,FileShare.Read)) {
            long length=input.Length;
            if(length<=0||length%512!=0||length+512>diskBytes)throw new IOException("Invalid image/device range");
            using(var sha=SHA256.Create())if(Hex(sha.ComputeHash(input))!=expected)throw new IOException("Approved source image SHA mismatch");
            input.Position=0;
            aligned=VirtualAlloc(IntPtr.Zero,(UIntPtr)(Chunk+512),0x3000,4);
            Require(aligned!=IntPtr.Zero,"Aligned buffer allocation");
            try {
                auditPath=backup+".io-events.csv";splitReads=0;
                File.WriteAllText(auditPath,"offset,event,requested,returned,win32\n0,PREIMAGE_BEGIN,0,0,0\n");
                var buffer=new byte[Chunk];byte[] tailBefore=new byte[512];
                using(var h=Open(device,Read|Write,NoBuffer|Through)) {
                    if(!testFile)CheckDevice(h,number,diskBytes);
                    using(var saved=new FileStream(backup,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                        Seek(h,0);
                        for(long off=0;off<length;off+=Chunk){int n=(int)Math.Min(Chunk,length-off);ReadExact(h,aligned,n);Marshal.Copy(aligned,buffer,0,n);saved.Write(buffer,0,n);}
                        saved.Flush(true);
                    }
                    Seek(h,length);ReadExact(h,aligned,512);Marshal.Copy(aligned,tailBefore,0,512);
                    File.AppendAllText(auditPath,"0,WRITE_BEGIN,0,0,0\n");
                    Seek(h,0);
                    using(var sha=SHA256.Create()) {
                        for(long off=0;off<length;off+=Chunk){
                            int n=(int)Math.Min(Chunk,length-off),got=0;
                            while(got<n){int k=input.Read(buffer,got,n-got);if(k==0)throw new EndOfStreamException();got+=k;}
                            Marshal.Copy(buffer,0,aligned,n);uint done;
                            Require(WriteFile(h,aligned,(uint)n,out done,IntPtr.Zero)&&done==n,"Exact raw write");
                            sha.TransformBlock(buffer,0,n,buffer,0);
                        }
                        sha.TransformFinalBlock(new byte[0],0,0);
                        if(Hex(sha.Hash)!=expected)throw new IOException("Image changed during writing");
                    }
                    Require(FlushFileBuffers(h),"Flush physical device");
                    File.AppendAllText(auditPath,length+",FLUSHED,0,0,0\n");
                }
                // Fresh handle + NO_BUFFERING forces a separate device read.
                using(var h=Open(device,Read,NoBuffer)) {
                    if(!testFile)CheckDevice(h,number,diskBytes);
                    Seek(h,0);
                    using(var output=new FileStream(readback,FileMode.CreateNew,FileAccess.Write,FileShare.None))
                    using(var sha=SHA256.Create()) {
                        for(long off=0;off<length;off+=Chunk){int n=(int)Math.Min(Chunk,length-off);ReadExact(h,aligned,n);Marshal.Copy(aligned,buffer,0,n);output.Write(buffer,0,n);sha.TransformBlock(buffer,0,n,buffer,0);}
                        output.Flush(true);sha.TransformFinalBlock(new byte[0],0,0);
                        result["readback_sha256"]=Hex(sha.Hash);
                        if(Hex(sha.Hash)!=expected)throw new IOException("Full physical readback SHA mismatch");
                    }
                    ReadExact(h,aligned,512);var tailAfter=new byte[512];Marshal.Copy(aligned,tailAfter,0,512);
                    for(int i=0;i<512;i++)if(tailBefore[i]!=tailAfter[i])throw new IOException("Sector immediately after write range changed");
                }
                using(var sha=SHA256.Create())using(var b=File.OpenRead(backup))result["preimage_sha256"]=Hex(sha.ComputeHash(b));
                result["bytes"]=length;result["first_lba"]=0;result["last_lba"]=length/512-1;
                result["fresh_unbuffered_readback"]=true;result["flushed"]=true;
                result["io_chunk_bytes"]=Chunk;result["crc_requests_recovered_by_complete_sector_reads"]=splitReads;
                result["next_sector_unchanged"]=true;result["status"]="PASS";return result;
            } finally {auditPath=null;VirtualFree(aligned,UIntPtr.Zero,0x8000);}
        }
    }
    public static Dictionary<string,object> WriteVerify(int number,long bytes,string image,string sha,string backup,string readback){
        return Run(@"\\.\PhysicalDrive"+number,number,bytes,image,sha,backup,readback,false);
    }
    public static List<Dictionary<string,object>> ProbeRead(int number,long diskBytes,long offset){
        var rows=new List<Dictionary<string,object>>();
        IntPtr buffer=VirtualAlloc(IntPtr.Zero,(UIntPtr)(1024*1024),0x3000,4);Require(buffer!=IntPtr.Zero,"Probe buffer");
        try{
            foreach(uint flags in new uint[]{NoBuffer,0})using(var h=Open(@"\\.\PhysicalDrive"+number,Read,flags)){
                CheckDevice(h,number,diskBytes);
                foreach(long pos in new long[]{0,offset-512,offset,offset+512,33554432,541901824})
                    foreach(int size in new int[]{512,4096,65536,1024*1024}){
                        Seek(h,pos);uint done;bool ok=ReadFile(h,buffer,(uint)size,out done,IntPtr.Zero);int err=ok?0:Marshal.GetLastWin32Error();
                        var row=new Dictionary<string,object>();row["offset"]=pos;row["requested"]=size;row["returned"]=done;
                        row["unbuffered"]=flags==NoBuffer;row["ok"]=ok;row["win32_error"]=err;
                        row["error_message"]=err==0?"":new Win32Exception(err).Message;
                        if(ok&&done==size){var data=new byte[size];Marshal.Copy(buffer,data,0,size);using(var sha=SHA256.Create())row["sha256"]=Hex(sha.ComputeHash(data));}
                        rows.Add(row);
                    }
            }
            return rows;
        }finally{VirtualFree(buffer,UIntPtr.Zero,0x8000);}
    }
    public static Dictionary<string,object> SelfTest(string folder){
        Directory.CreateDirectory(folder);string device=Path.Combine(folder,"device.bin"),image=Path.Combine(folder,"image.bin");
        byte[] disk=new byte[16384],data=new byte[8192];
        for(int i=0;i<disk.Length;i++)disk[i]=(byte)(i*17+3);
        for(int i=0;i<data.Length;i++)data[i]=(byte)(i*29+9);
        File.WriteAllBytes(device,disk);File.WriteAllBytes(image,data);string hash;
        using(var sha=SHA256.Create())hash=Hex(sha.ComputeHash(data));
        var r=Run(device,-1,disk.Length,image,hash,Path.Combine(folder,"before.bin"),Path.Combine(folder,"readback.bin"),true);
        var actual=File.ReadAllBytes(device);for(int i=0;i<actual.Length;i++)if(actual[i]!=(i<data.Length?data[i]:disk[i]))throw new IOException("SelfTest exact range mismatch");
        r["ordinary_file_only"]=true;r["entire_test_tail_unchanged"]=true;
        bool rejected=false;
        try {Run(device,-1,disk.Length,image,new string('0',64),Path.Combine(folder,"bad-before.bin"),Path.Combine(folder,"bad-read.bin"),true);}
        catch(IOException){rejected=true;}
        if(!rejected||File.Exists(Path.Combine(folder,"bad-before.bin")))throw new IOException("Bad hash was not rejected before device access");
        r["bad_source_hash_rejected_before_device_open"]=true;return r;
    }
}
