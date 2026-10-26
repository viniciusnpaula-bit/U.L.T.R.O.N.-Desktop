param(
    [Parameter(Mandatory = $true)][string]$Audio,
    [string]$Cultura = 'pt-BR'
)

# Reconhecimento nativo do Windows (System.Speech). Não acessa a rede.
# Devolve o texto em UTF-8 ou sai com código 1 quando o motor não está instalado.
$ErrorActionPreference = 'Stop'
$engine = $null
try {
    Add-Type -AssemblyName System.Speech
    $culture = [System.Globalization.CultureInfo]::GetCultureInfo($Cultura)
    $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine -ArgumentList $culture
    $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $engine.SetInputToWaveFile($Audio)
    $resultado = $engine.Recognize()
    if ($null -ne $resultado) {
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        [Console]::WriteLine($resultado.Text)
    }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($null -ne $engine) { $engine.Dispose() }
}
