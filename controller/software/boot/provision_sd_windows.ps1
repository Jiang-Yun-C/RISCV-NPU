param(
    [ValidateSet('Inspect','SelfTest','ReadProbe','WriteVerify')][string]$Mode='Inspect',
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$AuthorizationReceipt,
    [long]$ProbeOffset=24117248
)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $OutputDirectory){throw 'Output directory must be new'}
$null=New-Item -ItemType Directory -Path $OutputDirectory
$result=[ordered]@{schema_version=1;started_at=[DateTime]::UtcNow.ToString('o');mode=$Mode;status='RUNNING';card_written=$false;flash_modified=$false}
$locks=New-Object 'System.Collections.Generic.List[Microsoft.Win32.SafeHandles.SafeFileHandle]'
try {
    $p=Get-Content -Raw -Encoding UTF8 -LiteralPath $Plan | ConvertFrom-Json
    $inventory=[ordered]@{Disks=@(Get-Disk | Select-Object Number,FriendlyName,SerialNumber,UniqueId,BusType,Size,PartitionStyle,IsBoot,IsSystem,IsReadOnly,IsOffline,LogicalSectorSize,PhysicalSectorSize);Partitions=@(Get-Partition | Select-Object DiskNumber,PartitionNumber,DriveLetter,Offset,Size,Type,AccessPaths)}
    $inventory | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutputDirectory 'inventory.json')
    $candidates=@($inventory.Disks | Where-Object {$_.UniqueId -ceq $p.unique_id})
    if($candidates.Count -ne 1){throw 'Approved identity is absent or ambiguous'}
    $d=$candidates[0]
    if($d.Size -ne $p.device_bytes -or $d.BusType -ne 'USB' -or $d.IsBoot -or $d.IsSystem -or $d.IsReadOnly -or $d.IsOffline -or $d.LogicalSectorSize -ne 512){throw 'Target safety/size/sector mismatch'}
    $parts=@($inventory.Partitions | Where-Object {$_.DiskNumber -eq $d.Number})
    if($p.schema_version -ge 2){
        if($p.target_reidentified -ne $true -or -not $p.partition_style){throw 'Fresh target identity/layout snapshot is required'}
        $expected=@();if($null -ne $p.partitions){$expected=@($p.partitions)}
        $layoutSignature={param($rows) @($rows | Sort-Object PartitionNumber | Select-Object PartitionNumber,DriveLetter,Offset,Size,Type,AccessPaths) | ConvertTo-Json -Compress -Depth 5}
        if($d.PartitionStyle -ne $p.partition_style -or $parts.Count -ne $expected.Count -or
            (& $layoutSignature $parts) -cne (& $layoutSignature $expected)){throw 'Freshly approved partition layout changed'}
    } else {
        if($parts.Count -ne 1 -or $parts[0].DriveLetter -ne $p.drive_letter -or $parts[0].Offset -ne $p.partition_offset -or $parts[0].Size -ne $p.partition_bytes){throw 'Approved partition layout changed'}
        if($d.PartitionStyle -ne 'MBR'){throw 'Approved partition style changed'}
    }
    $image=Get-Item -LiteralPath $p.image_windows
    if($image.Length -ne $p.image_bytes -or (Get-FileHash -Algorithm SHA256 -LiteralPath $image.FullName).Hash.ToLowerInvariant() -cne $p.image_sha256){throw 'Approved image mismatch'}
    $result.target=$d;$result.partitions=$parts;$result.image=$p
    $result.administrator=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if($Mode -eq 'Inspect'){$result.status='PASS';return}
    Add-Type -Path (Join-Path $PSScriptRoot 'windows_sd_raw.cs')
    if($Mode -eq 'SelfTest'){$result.self_test=[NxSdRaw]::SelfTest((Join-Path $OutputDirectory 'ordinary-files'));$result.status='PASS';return}
    if($Mode -eq 'ReadProbe'){
        if(-not $result.administrator){throw 'Read-only raw probe requires Windows administrator token'}
        $result.read_only_probe=[NxSdRaw]::ProbeRead($d.Number,$d.Size,$ProbeOffset)
        $result.status='PASS';return
    }
    # No disk/volume is opened for mutation before the explicit receipt gate.
    if(-not $AuthorizationReceipt){throw 'Explicit user overwrite authorization receipt is required'}
    $a=Get-Content -Raw -Encoding UTF8 -LiteralPath $AuthorizationReceipt | ConvertFrom-Json
    if($a.approved -ne $true -or $a.unique_id -cne $p.unique_id -or $a.image_sha256 -cne $p.image_sha256 -or $a.bytes -ne $p.image_bytes -or $a.first_lba -ne 0 -or $a.last_lba -ne ($p.image_bytes/512-1) -or [string]::IsNullOrWhiteSpace($a.user_message)){throw 'User authorization does not cover this exact target/image/range'}
    if(-not $result.administrator){throw 'Windows administrator token required for raw disk/volume access'}
    $result.authorization_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $AuthorizationReceipt).Hash.ToLowerInvariant()
    # Lock and hold every volume on this exact disk, retaining failure originals.
    foreach($part in $parts){
        $paths=@($part.AccessPaths | Where-Object {$_ -match '^\\\\\?\\Volume\{'} )
        if($paths.Count -ne 1){throw 'Cannot resolve one volume GUID for target partition'}
        $locks.Add([NxSdRaw]::LockVolume($paths[0].TrimEnd('\')))
    }
    $again=Get-Disk -Number $d.Number
    if($again.UniqueId -cne $p.unique_id -or $again.Size -ne $p.device_bytes -or $again.IsBoot -or $again.IsSystem){throw 'Target identity changed after volume locking'}
    $result.card_write_attempted=$true
    $result.raw=[NxSdRaw]::WriteVerify($d.Number,$d.Size,$image.FullName,$p.image_sha256,(Join-Path $OutputDirectory 'preimage.img'),(Join-Path $OutputDirectory 'readback.img'))
    $result.card_written=$true;$result.status='PASS'
} catch {
    $result.status='FAIL';$result.failure=$_.Exception.ToString();throw
} finally {
    foreach($h in $locks){$h.Dispose()}
    $result.finished_at=[DateTime]::UtcNow.ToString('o')
    $result | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutputDirectory 'manifest.json')
}
