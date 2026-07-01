<# Musically PostToolUse Lint Hook
.SYNOPSIS
Runs ruff on backend Python files after they are edited by an agent.
#>

$input = $input | Out-String
if (-not $input) { exit 0 }

try {
    $hookData = $input | ConvertFrom-Json
} catch {
    exit 0
}

# Only act on edit-type tools
$toolName = $hookData.tool_name
if ($toolName -notin @('edit', 'replace_string_in_file', 'multi_replace_string_in_file', 'create_file', 'edit_notebook_file')) {
    exit 0
}

# Extract the file path from tool input
$toolInput = $hookData.tool_input
$filePath = $toolInput.filePath ?? $toolInput.file_path ?? $toolInput.fileUri ?? ''

if (-not $filePath) { exit 0 }

# Only lint Python files under backend/
$normalizedPath = $filePath -replace '\\', '/'
if ($normalizedPath -notmatch '/backend/.*\.py$') {
    exit 0
}

# Resolve to absolute workspace path
$workspaceRoot = $env:VSCODE_WORKSPACE_ROOT
if (-not $workspaceRoot) { exit 0 }

$fullPath = Join-Path $workspaceRoot (($normalizedPath -replace '^.*?/backend/', 'backend/'))
if (-not (Test-Path $fullPath)) {
    # File might not exist yet (create_file), that's fine
    exit 0
}

# Run ruff check on the file
$ruffResult = ruff check $fullPath --output-format concise 2>&1
$ruffExit = $LASTEXITCODE

if ($ruffExit -ne 0 -and $ruffResult) {
    $message = "## Lint warnings in ``$normalizedPath``:`n``````n$ruffResult``````"
    $output = @{
        decision = "continue"
        systemMessage = $message
    } | ConvertTo-Json -Compress
    Write-Output $output
}

exit 0
