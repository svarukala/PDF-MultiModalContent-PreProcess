param(
    [string]$SubscriptionId = "dad4fa0b-aa0d-42bc-8ec7-a5e83450c6f0",
    [string]$ResourceGroup = "rg-pdf-multimodal-dev",
    [string]$DocumentIntelligenceAccount = "di-pdf-multimodal-dad4fa0b",
    [string]$OpenAIAccount = "aoai-pdf-multimodal-dad4fa0b",
    [string]$DeploymentName = "gpt-4.1"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-AzureJson {
    param([string[]]$Arguments)
    $result = & az @Arguments --subscription $SubscriptionId --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed. Check your sign-in, subscription, and resource permissions."
    }
    return ($result -join "`n" | ConvertFrom-Json)
}

$settingsPath = Join-Path $PWD "local.settings.json"
if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    $settings = Get-Content "local.settings.json.example" -Raw | ConvertFrom-Json
}
if ($settings.IsEncrypted -or $null -eq $settings.Values) {
    throw "Expected unencrypted local.settings.json with a Values object."
}

$di = Invoke-AzureJson @("cognitiveservices", "account", "show", "--name", $DocumentIntelligenceAccount, "--resource-group", $ResourceGroup)
$openai = Invoke-AzureJson @("cognitiveservices", "account", "show", "--name", $OpenAIAccount, "--resource-group", $ResourceGroup)
$deployment = Invoke-AzureJson @("cognitiveservices", "account", "deployment", "show", "--name", $OpenAIAccount, "--resource-group", $ResourceGroup, "--deployment-name", $DeploymentName)
if ($deployment.properties.provisioningState -ne "Succeeded") {
    throw "The model deployment is not ready."
}
$diKeys = Invoke-AzureJson @("cognitiveservices", "account", "keys", "list", "--name", $DocumentIntelligenceAccount, "--resource-group", $ResourceGroup)
$openaiKeys = Invoke-AzureJson @("cognitiveservices", "account", "keys", "list", "--name", $OpenAIAccount, "--resource-group", $ResourceGroup)

$updates = @{
    DOCUMENTINTELLIGENCE_ENDPOINT = $di.properties.endpoint
    DOCUMENTINTELLIGENCE_API_KEY = $diKeys.key1
    AZURE_OPENAI_ENDPOINT = $openai.properties.endpoint
    AZURE_OPENAI_API_KEY = $openaiKeys.key1
    AZURE_OPENAI_DEPLOYMENT_NAME = $DeploymentName
}
foreach ($entry in $updates.GetEnumerator()) {
    if ([string]::IsNullOrWhiteSpace($entry.Value)) {
        throw "Azure returned an empty value for $($entry.Key); settings were not changed."
    }
    $settings.Values | Add-Member -NotePropertyName $entry.Key -NotePropertyValue $entry.Value -Force
}

[System.IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
Write-Host "Azure AI settings saved to gitignored local.settings.json. Storage settings were preserved."
Write-Host "Restart the local Functions host to use the new settings. Keys were not printed."
