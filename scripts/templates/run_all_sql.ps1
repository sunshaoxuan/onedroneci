# ASCII-only SQL execution script generated for PowerShell compatibility.
[CmdletBinding()]
param(
    [string]$OhrDbHost = '@@OHR_DB_HOST@@',
    [int]$OhrDbPort = @@OHR_DB_PORT@@,
    [string]$OhrDbUser = '@@OHR_DB_USER@@',
    [string]$OhrDbPassword = '@@OHR_DB_PASSWORD@@',

    [string]$UpdsDbHost = '@@UPDS_DB_HOST@@',
    [int]$UpdsDbPort = @@UPDS_DB_PORT@@,
    [string]$UpdsDbName = '@@UPDS_DB_NAME@@',
    [string]$UpdsDbUser = '@@UPDS_DB_USER@@',
    [string]$UpdsDbPassword = '@@UPDS_DB_PASSWORD@@',

    [string]$PsqlExe = 'psql',

    [switch]$SkipExtensionAndDblink,
    [switch]$ContinueOnError,
    [switch]$SkipMissing,
    [switch]$PlanOnly,
    [bool]$ConvertSqlToSjis = $true,
    [switch]$ResumeFromDblink,
    [string]$ClientEncoding = 'SJIS'
)

# OHR and tenant share one PostgreSQL server and credential set.
$DbHost = $OhrDbHost
$DbPort = $OhrDbPort
$DbName = 'ohr'
$DbUser = $OhrDbUser
$DbPassword = $OhrDbPassword

$DjnSelfDbName = 'ohr'
$DjnSelfHostAddr = $OhrDbHost
$DjnSelfPort = [string]$OhrDbPort
$DjnSelfUser = $OhrDbUser
$DjnSelfPassword = $OhrDbPassword

$U7ToPhrHost = $UpdsDbHost
$U7ToPhrPort = [string]$UpdsDbPort
$U7ToPhrDbName = $UpdsDbName
$U7ToPhrUser = $UpdsDbUser
$U7ToPhrPassword = $UpdsDbPassword

$TnToPhrHost = $OhrDbHost
$TnToPhrPort = [string]$OhrDbPort
$TnToPhrDbName = 'tenant'
$TnToPhrUser = $OhrDbUser
$TnToPhrPassword = $OhrDbPassword

$PostgresBin = "C:\Program Files\PostgreSQL\18\bin"

if (Test-Path (Join-Path $PostgresBin "psql.exe")) {
    $env:Path = "$PostgresBin;$env:Path"
} elseif (-not $PlanOnly -and -not (Get-Command $PsqlExe -ErrorAction SilentlyContinue)) {
    throw "psql.exe not found in PostgreSQL bin or PATH: $PostgresBin"
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$BaseDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$LogDir = Join-Path $BaseDir 'logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$TimeStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogFile = Join-Path $LogDir "phr_build_$TimeStamp.log"
$GeneratedDir = Join-Path $BaseDir '_generated'
New-Item -ItemType Directory -Path $GeneratedDir -Force | Out-Null
$ConvertedDir = Join-Path $BaseDir '_converted_sjis'
if ($ConvertSqlToSjis) { New-Item -ItemType Directory -Path $ConvertedDir -Force | Out-Null }

try {
    Add-Type -AssemblyName System.Text.Encoding.CodePages -ErrorAction SilentlyContinue
    [System.Text.Encoding]::RegisterProvider([System.Text.CodePagesEncodingProvider]::Instance)
} catch { }
$Cp932Encoding = [System.Text.Encoding]::GetEncoding(932)
$Utf8StrictEncoding = New-Object System.Text.UTF8Encoding($false, $true)
$SqlFolders = @('Sequence', 'Function', 'Table', 'ForeignTable', 'View', 'Procedure')
$script:FailedSqlCount = 0

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = '[{0}] [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Host $line
    [System.IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine, $Cp932Encoding)
}

function Read-TextAutoEncoding {
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        return [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        return [System.Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        return [System.Text.Encoding]::BigEndianUnicode.GetString($bytes, 2, $bytes.Length - 2)
    }
    try {
        return $Utf8StrictEncoding.GetString($bytes)
    } catch {
        return $Cp932Encoding.GetString($bytes)
    }
}

function Write-TextCp932 {
    param([string]$Path, [string]$Text)
    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, $Cp932Encoding)
}

function Convert-SqlFileToCp932 {
    param([string]$Path)
    if (-not $ConvertSqlToSjis) { return $Path }
    $full = (Get-Item -LiteralPath $Path).FullName
    $relative = $full.Substring($BaseDir.Length).TrimStart('\','/')
    $target = Join-Path $ConvertedDir $relative
    $text = Read-TextAutoEncoding -Path $full
    Write-TextCp932 -Path $target -Text $text
    return $target
}

function Escape-SqlLiteral {
    param([string]$Value)
    if ($null -eq $Value) { return '' }
    return $Value.Replace("'", "''")
}

function Assert-RequiredSetting {
    param([string]$Name, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -eq 'XXX' -or $Value -eq 'DATABASE_NAME') {
        throw "Parameter $Name is not configured. Please specify actual environment value."
    }
}

function Resolve-SqlFile {
    param(
        [string]$Folder,
        [string]$FileName
    )

    $folderPath = Join-Path $BaseDir $Folder
    $candidate = Join-Path $folderPath $FileName
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return (Get-Item -LiteralPath $candidate) }

    if ([System.IO.Path]::GetExtension($FileName) -eq '') {
        $candidate2 = Join-Path $folderPath ($FileName + '.sql')
        if (Test-Path -LiteralPath $candidate2 -PathType Leaf) { return (Get-Item -LiteralPath $candidate2) }
    }

    if ($FileName.ToLower().EndsWith('.sq')) {
        $candidate3 = Join-Path $folderPath ($FileName + 'l')
        if (Test-Path -LiteralPath $candidate3 -PathType Leaf) { return (Get-Item -LiteralPath $candidate3) }
    }

    Write-Verbose "Ordered SQL is not included in this package and was skipped: $Folder\$FileName"
    return $null
}

function Get-AllSqlFilesInFolder {
    param([string]$Folder)

    $folderPath = Join-Path $BaseDir $Folder
    if (-not (Test-Path -LiteralPath $folderPath -PathType Container)) {
        Write-Log "Folder not found: $Folder" 'WARN'
        return @()
    }

    return @(Get-ChildItem -LiteralPath $folderPath -File -Filter '*.sql' -Recurse |
        Where-Object { $_.Name -ine 'all.sql' } |
        Sort-Object FullName)
}

function New-SqlPlanItem {
    param(
        [string]$GroupName,
        [System.IO.FileInfo]$FileInfo,
        [string]$Source,
        [string]$Remark = '',
        [int]$Order = [int]::MaxValue
    )

    return [pscustomobject]@{
        Group = $GroupName
        Path = $FileInfo.FullName
        File = $FileInfo.Name
        Source = $Source
        Remark = $Remark
        Order = $Order
    }
}

function Add-SetValue {
    param(
        [hashtable]$Set,
        [string]$Value
    )
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        $Set[$Value.ToLowerInvariant()] = $true
    }
}

function Test-SetValue {
    param(
        [hashtable]$Set,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    return $Set.ContainsKey($Value.ToLowerInvariant())
}

function Get-SqlPlan {
    param(
        [string]$GroupName,
        [string]$Folder,
        [object[]]$OrderedScripts,
        [string[]]$ExcludeFileNames = @(),
        [switch]$IncludeExtraFiles
    )

    $plan = @()
    $used = @{}
    $excluded = @{}

    foreach ($name in $ExcludeFileNames) {
        if (-not [string]::IsNullOrWhiteSpace($name)) {
            $baseName = [System.IO.Path]::GetFileName($name)
            Add-SetValue -Set $excluded -Value $baseName
            if ($baseName.ToLowerInvariant().EndsWith('.sq')) { Add-SetValue -Set $excluded -Value ($baseName + 'l') }
            if ([System.IO.Path]::GetExtension($baseName) -eq '') { Add-SetValue -Set $excluded -Value ($baseName + '.sql') }
        }
    }

    foreach ($s in $OrderedScripts) {
        if (Test-SetValue -Set $excluded -Value ([System.IO.Path]::GetFileName($s.File))) { continue }
        $fileInfo = Resolve-SqlFile -Folder $s.Folder -FileName $s.File
        if ($null -ne $fileInfo) {
            Add-SetValue -Set $used -Value $fileInfo.FullName
            $source = 'Procedure No.{0}' -f $s.No
            $plan += (New-SqlPlanItem -GroupName $GroupName -FileInfo $fileInfo -Source $source -Remark $s.Remark -Order ([int]$s.No))
        }
    }

    if ($IncludeExtraFiles) {
        foreach ($fileInfo in (Get-AllSqlFilesInFolder -Folder $Folder)) {
            if (Test-SetValue -Set $used -Value $fileInfo.FullName) { continue }
            if (Test-SetValue -Set $excluded -Value $fileInfo.Name) {
                Write-Log "Deferred or excluded from ${GroupName}: $($fileInfo.Name)" 'INFO'
                continue
            }
            $plan += (New-SqlPlanItem -GroupName $GroupName -FileInfo $fileInfo -Source 'Extra SQL auto-detected' -Remark 'Auto-detected additional SQL in folder')
        }
    }

    return @($plan)
}

function Get-AllPackagedSqlFiles {
    $files = @()
    foreach ($folder in $SqlFolders) {
        $files += @(Get-AllSqlFilesInFolder -Folder $folder)
    }
    return @($files | Sort-Object FullName)
}

function Assert-SqlPlanCoverage {
    param([object[]]$Plans)

    $actual = @(Get-AllPackagedSqlFiles)
    $plannedPaths = @($Plans | ForEach-Object { [System.IO.Path]::GetFullPath($_.Path).ToLowerInvariant() })
    $actualPaths = @($actual | ForEach-Object { [System.IO.Path]::GetFullPath($_.FullName).ToLowerInvariant() })
    $duplicates = @($plannedPaths | Group-Object | Where-Object { $_.Count -ne 1 })
    $missing = @($actualPaths | Where-Object { $_ -notin $plannedPaths })
    $unexpected = @($plannedPaths | Where-Object { $_ -notin $actualPaths })

    if ($duplicates.Count -gt 0 -or $missing.Count -gt 0 -or $unexpected.Count -gt 0) {
        if ($duplicates.Count -gt 0) { Write-Log "Duplicate planned SQL: $($duplicates.Name -join ', ')" 'ERROR' }
        if ($missing.Count -gt 0) { Write-Log "Unplanned SQL: $($missing -join ', ')" 'ERROR' }
        if ($unexpected.Count -gt 0) { Write-Log "Planned SQL not found: $($unexpected -join ', ')" 'ERROR' }
        throw 'SQL execution plan does not cover packaged SQL files exactly once.'
    }

    Write-Log "SQL execution plan coverage passed: $($actual.Count) files"
}

function Invoke-PsqlFile {
    param(
        [string]$Path,
        [string]$Label,
        [string]$Source = '',
        [string]$Remark = ''
    )

    if ([string]::IsNullOrWhiteSpace($Path)) { return }

    if (-not [string]::IsNullOrWhiteSpace($Source)) { Write-Log "Source: $Source" }
    Write-Log "START $Label : $Path"

    $execPath = Convert-SqlFileToCp932 -Path $Path

    if ($PlanOnly) {
        if ($ConvertSqlToSjis) {
            Write-Log "PLAN ONLY. Converted to SJIS temp file: $execPath" 'WARN'
        }
        Write-Log "PLAN ONLY. Not executed: $execPath" 'WARN'
        return
    }

    $env:PGPASSWORD = $DbPassword
    if (-not [string]::IsNullOrWhiteSpace($ClientEncoding)) { $env:PGCLIENTENCODING = $ClientEncoding }
    try {
        & $PsqlExe -h $DbHost -p $DbPort -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -f $execPath 2>&1 | ForEach-Object {
            $text = $_.ToString()
            Write-Host $text
            [System.IO.File]::AppendAllText($LogFile, $text + [Environment]::NewLine, $Cp932Encoding)
        }
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            $msg = "FAILED $Label : exit code $code"
            $script:FailedSqlCount++
            Write-Log $msg 'ERROR'
            if (-not $ContinueOnError) { throw $msg }
        } else {
            Write-Log "END $Label"
        }
    }
    finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
        Remove-Item Env:\PGCLIENTENCODING -ErrorAction SilentlyContinue
    }
}

function Invoke-Plan {
    param(
        [string]$GroupName,
        [object[]]$Plan
    )

    Write-Log "========== $GroupName =========="
    if ($Plan.Count -eq 0) {
        Write-Log "No SQL file in $GroupName" 'WARN'
        return
    }

    $i = 0
    foreach ($item in $Plan) {
        $i++
        $label = '{0} #{1} {2}' -f $GroupName, $i, $item.File
        Invoke-PsqlFile -Path $item.Path -Label $label -Source $item.Source -Remark $item.Remark
    }
}

function New-ExtensionAndDblinkSql {
    Assert-RequiredSetting 'U7ToPhrHost' $U7ToPhrHost
    Assert-RequiredSetting 'U7ToPhrPort' $U7ToPhrPort
    Assert-RequiredSetting 'U7ToPhrDbName' $U7ToPhrDbName
    Assert-RequiredSetting 'U7ToPhrUser' $U7ToPhrUser
    Assert-RequiredSetting 'U7ToPhrPassword' $U7ToPhrPassword

    $sqlPath = Join-Path $GeneratedDir '04_extension_and_dblink.sql'

    $sql = @"
CREATE EXTENSION IF NOT EXISTS postgres_fdw
    SCHEMA public
    VERSION '1.1';

DO `$`$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_foreign_data_wrapper
        WHERE fdwname = 'dblink_fdw'
    ) THEN
        CREATE FOREIGN DATA WRAPPER dblink_fdw
            VALIDATOR public.dblink_fdw_validator;
    END IF;
END
`$`$;

CREATE SERVER IF NOT EXISTS djn_self
    FOREIGN DATA WRAPPER dblink_fdw
    OPTIONS (dbname '$(Escape-SqlLiteral $DjnSelfDbName)', hostaddr '$(Escape-SqlLiteral $DjnSelfHostAddr)', port '$(Escape-SqlLiteral $DjnSelfPort)');

CREATE USER MAPPING IF NOT EXISTS FOR postgres SERVER djn_self
    OPTIONS (password '$(Escape-SqlLiteral $DjnSelfPassword)', "user" '$(Escape-SqlLiteral $DjnSelfUser)');

CREATE SERVER IF NOT EXISTS u7tophr
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host '$(Escape-SqlLiteral $U7ToPhrHost)', port '$(Escape-SqlLiteral $U7ToPhrPort)', dbname '$(Escape-SqlLiteral $U7ToPhrDbName)');

CREATE USER MAPPING IF NOT EXISTS FOR postgres SERVER u7tophr
    OPTIONS ("user" '$(Escape-SqlLiteral $U7ToPhrUser)', password '$(Escape-SqlLiteral $U7ToPhrPassword)');

CREATE SERVER IF NOT EXISTS tntophr
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host '$(Escape-SqlLiteral $TnToPhrHost)', port '$(Escape-SqlLiteral $TnToPhrPort)', dbname '$(Escape-SqlLiteral $TnToPhrDbName)');

CREATE USER MAPPING IF NOT EXISTS FOR postgres SERVER tntophr
    OPTIONS ("user" '$(Escape-SqlLiteral $TnToPhrUser)', password '$(Escape-SqlLiteral $TnToPhrPassword)');
"@

    Write-TextCp932 -Path $sqlPath -Text $sql
    return $sqlPath
}
$SequenceScripts = @(
    [pscustomobject]@{ Folder = 'Sequence'; No = 1; File = 'kihon_snow_id_seq.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Sequence'; No = 2; File = 'seq_acc_common_id.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Sequence'; No = 3; File = 'salary_snow_id_seq'; Remark = '' }
    [pscustomobject]@{ Folder = 'Sequence'; No = 4; File = 'hist_u01_shodaku_hus_id_seq.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Sequence'; No = 5; File = 'gensen_snow_id_seq.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Sequence'; No = 6; File = 'ido_snow_id_seq.sql'; Remark = '' }
)

$InitialFunctionScripts = @(
    [pscustomobject]@{ Folder = 'Function'; No = 1; File = 'crypt.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 2; File = 'dblink_connect.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 3; File = 'dblink_disconnect.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 4; File = 'dblink_exec.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 5; File = 'dblink_fdw_validator.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 6; File = 'decode.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 7; File = 'f_get_address_hr.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 9; File = 'gen_salt.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 10; File = 'gensen_snow_next_id.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 11; File = 'ido_snow_next_id.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 12; File = 'jinjiido_to_sreki.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 13; File = 'kihon_snow_next_id.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 14; File = 'nvl.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 15; File = 'salary_convert_to_japanese_date'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 16; File = 'salary_snow_next_id.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 17; File = 'f_get_address_ohr.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 18; File = 'dblink.sql'; Remark = '' }
)

$TableScripts = @(
    [pscustomobject]@{ Folder = 'Table'; No = 1; File = 'bp_ru_decision.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 2; File = 'upds_in_dhjrkaisei_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 3; File = 'upds_in_djnd0110_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 4; File = 'upds_in_djnd0120_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 5; File = 'upds_in_djnd0130_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 6; File = 'upds_in_djnd0140_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 7; File = 'upds_in_djnd0310_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 8; File = 'upds_in_djnd3001_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 9; File = 'upds_in_djnd3002_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 10; File = 'upds_in_djnd3003_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 11; File = 'upds_in_djnd3004_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 12; File = 'upds_in_djnd3005_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 13; File = 'upds_in_djnd3050_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 14; File = 'upds_in_djnd4001_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 15; File = 'upds_in_drkaisei_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 16; File = 'upds_in_dt_hist_u01_salary_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 17; File = 'upds_in_dt_hist_u01_salary_key_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 18; File = 'upds_in_dt_hist_u01_salaryprint_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 19; File = 'upds_in_dt_hist_u01_salaryprinttitle_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 20; File = 'upds_in_family_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 21; File = 'upds_in_gensen_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 22; File = 'upds_in_idoreki_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 23; File = 'upds_in_jinjiido_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 24; File = 'upds_in_kaisei_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 25; File = 'upds_in_kihon_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 26; File = 'upds_in_kyoyoinfo_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 27; File = 'upds_in_kyugoho_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 28; File = 'upds_in_qualification_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 29; File = 'upds_in_schoolcareer_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 30; File = 'upds_in_training_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 31; File = 'upds_in_urjyusho_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 32; File = 'upds_in_urkazoku_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 33; File = 'upds_in_xccompany_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 34; File = 'upds_in_xkkihon_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 35; File = 'upds_in_xkkijun_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 36; File = 'upds_in_xmmeisaikb_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 37; File = 'UPDS_SYNC_FAMILY.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 38; File = 'UPDS_SYNC_FAMILY_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 39; File = 'UPDS_SYNC_FAMILY_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 40; File = 'UPDS_SYNC_IDOREKI.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 41; File = 'UPDS_SYNC_IDOREKI_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 42; File = 'UPDS_SYNC_IDOREKI_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 43; File = 'UPDS_SYNC_KAISEI.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 44; File = 'UPDS_SYNC_KAISEI_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 45; File = 'UPDS_SYNC_KAISEI_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 46; File = 'UPDS_SYNC_KIHON.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 47; File = 'UPDS_SYNC_KIHON_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 48; File = 'UPDS_SYNC_KIHON_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 49; File = 'UPDS_SYNC_KYOYOINFO.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 50; File = 'UPDS_SYNC_KYOYOINFO_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 51; File = 'UPDS_SYNC_KYOYOINFO_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 52; File = 'UPDS_SYNC_KYUGOHO.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 53; File = 'UPDS_SYNC_KYUGOHO_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 54; File = 'UPDS_SYNC_KYUGOHO_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 55; File = 'UPDS_SYNC_QUALIFICATION.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 56; File = 'UPDS_SYNC_QUALIFICATION_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 57; File = 'UPDS_SYNC_QUALIFICATION_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 58; File = 'UPDS_SYNC_SCHOOLCAREER.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 59; File = 'UPDS_SYNC_SCHOOLCAREER_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 60; File = 'UPDS_SYNC_SCHOOLCAREER_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 61; File = 'UPDS_SYNC_TRAINING.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 62; File = 'UPDS_SYNC_TRAINING_GEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 63; File = 'UPDS_SYNC_TRAINING_ZEN.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 64; File = 'UPDS_SYNC_KENMU_TABLE.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Table'; No = 65; File = 'UPDS_SYNC_KENMU_WK_TABLE.sql'; Remark = '' }
)

$ForeignTableScripts = @(
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 1; File = 'upds_in_dhjrkaisei.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 2; File = 'upds_in_djnd0110.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 3; File = 'upds_in_djnd0120.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 4; File = 'upds_in_djnd0130.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 5; File = 'upds_in_djnd0140.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 6; File = 'upds_in_djnd0310.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 7; File = 'upds_in_djnd2101.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 8; File = 'upds_in_djnd2213.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 9; File = 'upds_in_djnd2201.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 10; File = 'upds_in_djnd2401.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 11; File = 'upds_in_djnd3001.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 12; File = 'upds_in_djnd3002.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 13; File = 'upds_in_djnd3003.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 14; File = 'upds_in_djnd3004.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 15; File = 'upds_in_djnd3005.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 16; File = 'upds_in_djnd3050.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 17; File = 'upds_in_djnd4001.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 18; File = 'upds_in_djnd4002.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 19; File = 'upds_in_djnd25016m.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 20; File = 'upds_in_djnd25026m.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 21; File = 'upds_in_djnd25036m.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 22; File = 'upds_in_djnd25046m.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 23; File = 'upds_in_drkaisei.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 24; File = 'upds_in_gensen.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 25; File = 'upds_in_jinjiido.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 26; File = 'upds_in_jmaddress.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 27; File = 'upds_in_umkshogai.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 28; File = 'upds_in_umshokugyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 29; File = 'upds_in_umtuzuki.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 30; File = 'upds_in_umyubinbango.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 31; File = 'upds_in_urjyusho.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 32; File = 'upds_in_urkazoku.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 33; File = 'upds_in_uwprintshain.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 34; File = 'upds_in_xccompany.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 35; File = 'upds_in_xckanri.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 36; File = 'upds_in_xcprintpatan.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 37; File = 'upds_in_xkkihon.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 38; File = 'upds_in_xkkijun.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 39; File = 'upds_in_xkmynohojin.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 40; File = 'upds_in_xmbank.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 41; File = 'upds_in_xmfurikomi.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 42; File = 'upds_in_xmkoza.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 43; File = 'upds_in_xmmeisaikb.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 44; File = 'upds_in_xmnenharai.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 45; File = 'upds_in_xmsbank.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 46; File = 'upds_out_kazoku.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 47; File = 'upds_out_zeifuyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 48; File = 'upds_out_renkei_mapping.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 49; File = 'upds_out_renkei_sinsei_data.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 50; File = 'upds_out_xxxx_nen_jyusho.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 51; File = 'upds_out_xxxx_nen_kazoku.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 52; File = 'upds_out_xxxx_nen_lifeinsurance.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 53; File = 'upds_out_xxxx_nen_loandeduction.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 54; File = 'upds_out_xxxx_nen_request.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 55; File = 'upds_out_xxxx_nen_spouseincome.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 56; File = 'upds_out_xxxx_nen_stkkgkcyosei.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 57; File = 'upds_out_xxxx_nen_syotkzeifuyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 58; File = 'upds_out_xxxx_nen_tokuteifuyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 59; File = 'upds_out_xxxx_nen_tskhaigsfuyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 60; File = 'upds_out_xxxx_nen_zeifuyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 61; File = 'upds_out_xxxx_nen_zensyoku.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 62; File = 'upds_in_dokyoinspecial.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 63; File = 'upds_out_xxxx_kazoku.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 64; File = 'upds_out_xxxx_zeifuyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'ForeignTable'; No = 65; File = 'tn_in_tenant.sql'; Remark = '' }
)

$LateFunctionScripts = @(
    [pscustomobject]@{ Folder = 'Function'; No = 13; File = 'f_get_xckanri.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 19; File = 'f_get_language.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 20; File = 'f_get_timezone.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Function'; No = 21; File = 'f_get_jmaddress.sql'; Remark = '' }
)

$ViewScripts = @(
    [pscustomobject]@{ Folder = 'View'; No = 1; File = 'upds_in_hist_u01_shodaku_view.sql'; Remark = '' }
)

$ProcedureScripts = @(
    [pscustomobject]@{ Folder = 'Procedure'; No = 1; File = 'p_ins_pslog.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 2; File = 'p_writepslog.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 3; File = 'proc_hr_to_upds_shoteate.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 4; File = 'upds_in_all_masterdata.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 5; File = 'upds_in_djnd250x6m.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 6; File = 'upds_in_djnd2101.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 7; File = 'upds_in_djnd2213.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 8; File = 'upds_in_djnd2401.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 9; File = 'upds_in_gensen.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 10; File = 'upds_in_gensen_phrif_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 11; File = 'upds_in_jinjiido_rodo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 12; File = 'upds_in_jinjiido_rodo_phrif_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 13; File = 'upds_in_kihon_joho.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 14; File = 'upds_in_kihon_joho_phrif_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 15; File = 'upds_in_kihon_joho_nama_table.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 16; File = 'upds_in_mdm_code.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 17; File = 'upds_in_mdm_code_firsttime.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 18; File = 'upds_in_organisation.sq'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 19; File = 'upds_in_organisation_firsttime.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 20; File = 'upds_in_salary.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 21; File = 'upds_in_umkshogai.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 22; File = 'upds_in_umshokugyo.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 23; File = 'upds_in_umtuzuki.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 24; File = 'upds_in_umyubinbango.sq'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 25; File = 'upds_in_xmbank.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 26; File = 'upds_in_xmfurikomi.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 27; File = 'upds_in_xmkoza.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 28; File = 'upds_in_xmmeisaikb.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 29; File = 'upds_in_xmnenharai.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 30; File = 'upds_in_xmsbank.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 31; File = 'upds_out_getnenrequest.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 32; File = 'upds_out_nenmatsuchosei.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 33; File = 'upds_out_nenmatsuchosei_nextyear.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 34; File = 'UPDS2PHR_FAMILY.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 35; File = 'UPDS2PHR_IDOREKI.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 36; File = 'UPDS2PHR_KAISEI.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 37; File = 'UPDS2PHR_KIHON.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 38; File = 'UPDS2PHR_KYOYOINFO.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 39; File = 'UPDS2PHR_KYUGOHO.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 40; File = 'UPDS2PHR_QUALIFICATION.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 41; File = 'UPDS2PHR_SCHOOLCAREER.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 42; File = 'UPDS2PHR_TRAINING.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 43; File = 'upds_out_getsukazoku.sql'; Remark = '' }
    [pscustomobject]@{ Folder = 'Procedure'; No = 44; File = 'hr_to_upds_getsukazoku.sql'; Remark = '' }
)


Write-Log "BaseDir: $BaseDir"
Write-Log "LogFile: $LogFile"
Write-Log "Database: ${DbHost}:${DbPort}/${DbName} user=${DbUser}"
Write-Log "Log encoding: CP932/SJIS"
Write-Log "Client encoding: $ClientEncoding"
if ($ConvertSqlToSjis) { Write-Log "SQL conversion: source auto-detect to CP932 temp files" }

try {
    Assert-RequiredSetting 'DbName' $DbName
    if ([string]::IsNullOrWhiteSpace($DbPassword)) {
        Write-Log 'DbPassword is empty. psql may prompt or fail depending on pg_hba.conf / pgpass.conf.' 'WARN'
    }

    $LateFunctionFileNames = @($LateFunctionScripts | ForEach-Object { $_.File })

    $SequencePlan = @(Get-SqlPlan -GroupName '01_Sequence' -Folder 'Sequence' -OrderedScripts $SequenceScripts -IncludeExtraFiles)
    $InitialFunctionPlan = @(Get-SqlPlan -GroupName '02_Function_initial' -Folder 'Function' -OrderedScripts $InitialFunctionScripts -ExcludeFileNames $LateFunctionFileNames -IncludeExtraFiles)
    $TablePlan = @(Get-SqlPlan -GroupName '03_Table' -Folder 'Table' -OrderedScripts $TableScripts -IncludeExtraFiles)
    $ForeignTablePlan = @(Get-SqlPlan -GroupName '06_ForeignTable' -Folder 'ForeignTable' -OrderedScripts $ForeignTableScripts -IncludeExtraFiles)
    $LateFunctionPlan = @(Get-SqlPlan -GroupName '07_Function_after_foreign_table' -Folder 'Function' -OrderedScripts $LateFunctionScripts)
    $ViewPlan = @(Get-SqlPlan -GroupName '08_View' -Folder 'View' -OrderedScripts $ViewScripts -IncludeExtraFiles)
    $ProcedurePlan = @(Get-SqlPlan -GroupName '09_Procedure' -Folder 'Procedure' -OrderedScripts $ProcedureScripts -IncludeExtraFiles)

    $AllSqlPlans = @($SequencePlan) + @($InitialFunctionPlan) + @($TablePlan) + @($ForeignTablePlan) + @($LateFunctionPlan) + @($ViewPlan) + @($ProcedurePlan)
    Assert-SqlPlanCoverage -Plans $AllSqlPlans

    Write-Log 'Execution plan summary:'
    Write-Log "01_Sequence: $($SequencePlan.Count) files"
    Write-Log "02_Function_initial: $($InitialFunctionPlan.Count) files"
    Write-Log "03_Table: $($TablePlan.Count) files"
    Write-Log "06_ForeignTable: $($ForeignTablePlan.Count) files"
    Write-Log "07_Function_after_foreign_table: $($LateFunctionPlan.Count) files"
    Write-Log "08_View: $($ViewPlan.Count) files"
    Write-Log "09_Procedure: $($ProcedurePlan.Count) files"

    if ($ResumeFromDblink) {
        Write-Log '01_Sequence skipped by ResumeFromDblink.' 'WARN'
        Write-Log '02_Function_initial skipped by ResumeFromDblink.' 'WARN'
        Write-Log '03_Table skipped by ResumeFromDblink.' 'WARN'
    } else {
        Invoke-Plan -GroupName '01_Sequence' -Plan $SequencePlan
        Invoke-Plan -GroupName '02_Function_initial' -Plan $InitialFunctionPlan
        Invoke-Plan -GroupName '03_Table' -Plan $TablePlan
    }

    if ($SkipExtensionAndDblink) {
        Write-Log '04_Extension_and_05_dblink skipped by parameter.' 'WARN'
    } else {
        Write-Log '========== 04_Extension_and_05_dblink =========='
        $extensionSql = New-ExtensionAndDblinkSql
        Invoke-PsqlFile -Path $extensionSql -Label '04_Extension_and_05_dblink' -Source '4, 5' -Remark 'Extension, FDW, server, user mapping'
    }

    $ForeignTablePlanBeforeLateFunction = @($ForeignTablePlan | Where-Object { $_.Order -le 49 })
    $ForeignTablePlanAfterLateFunction = @($ForeignTablePlan | Where-Object { $_.Order -gt 49 })

    Invoke-Plan -GroupName '06_ForeignTable_before_late_function' -Plan $ForeignTablePlanBeforeLateFunction
    Invoke-Plan -GroupName '07_Function_after_foreign_table' -Plan $LateFunctionPlan
    Invoke-Plan -GroupName '06_ForeignTable_after_late_function' -Plan $ForeignTablePlanAfterLateFunction
    Invoke-Plan -GroupName '08_View' -Plan $ViewPlan
    Invoke-Plan -GroupName '09_Procedure' -Plan $ProcedurePlan

    if ($script:FailedSqlCount -gt 0) {
        throw "$($script:FailedSqlCount) SQL file(s) failed. See log: $LogFile"
    } elseif ($PlanOnly) {
        Write-Log 'PLAN ONLY DONE'
    } else {
        Write-Log 'ALL DONE'
    }
    exit 0
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    Write-Log 'ABORTED' 'ERROR'
    exit 1
}
