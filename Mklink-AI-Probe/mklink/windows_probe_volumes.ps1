# Passive inventory only. USB ancestry is verified by cfgmgr32 in probe_volumes.py.
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$volumes = @(Get-CimInstance Win32_Volume | Where-Object Label -eq 'MICROKEEN')
$rows = @(foreach ($disk in Get-CimInstance Win32_DiskDrive) {
    if ($disk.PNPDeviceID -notlike 'USBSTOR\*') { continue }
    foreach ($partition in Get-CimAssociatedInstance -InputObject $disk -Association Win32_DiskDriveToDiskPartition) {
        foreach ($logical in Get-CimAssociatedInstance -InputObject $partition -Association Win32_LogicalDiskToPartition) {
            foreach ($volume in $volumes | Where-Object DriveLetter -eq $logical.DeviceID) {
                [pscustomobject]@{pnp_id=$disk.PNPDeviceID; root=$volume.DeviceID; drive=$logical.DeviceID; label=$volume.Label}
            }
        }
    }
})
ConvertTo-Json -InputObject $rows -Compress
