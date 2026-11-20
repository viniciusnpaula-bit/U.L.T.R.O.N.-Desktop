using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace UltronLauncher
{
    internal static class Program
    {
        private const string AppName = "U.L.T.R.O.N. Desktop";
        private const uint AttachParentProcess = 0xFFFFFFFF;

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AttachConsole(uint dwProcessId);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AllocConsole();

        [STAThread]
        private static int Main(string[] args)
        {
            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
            string launcherPy = Path.Combine(root, "launcher.py");
            if (!File.Exists(launcherPy))
            {
                ShowError(
                    "Os arquivos principais do U.L.T.R.O.N. Desktop não foram encontrados nesta pasta.\n\n" +
                    "Execute o instalador oficial (ULTRON-Setup) para reparar a instalação."
                );
                return 1;
            }

            bool consoleMode = IsConsoleMode(args);
            string runtimeDir;
            string pythonExe;
            if (!TryResolvePython(root, consoleMode, out pythonExe, out runtimeDir))
            {
                ShowError(
                    "O runtime Python embarcado do U.L.T.R.O.N. Desktop está ausente ou incompleto.\n\n" +
                    "Execute o instalador oficial (ULTRON-Setup) para restaurar a instalação."
                );
                return 1;
            }

            if (consoleMode && !Console.IsOutputRedirected && !Console.IsErrorRedirected)
            {
                if (!AttachConsole(AttachParentProcess))
                {
                    AllocConsole();
                }
            }

            var psi = new ProcessStartInfo();
            psi.FileName = pythonExe;
            psi.Arguments = BuildArguments(launcherPy, args);
            psi.WorkingDirectory = root;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = !consoleMode;
            ApplyIsolatedEnvironment(psi, runtimeDir);

            try
            {
                using (Process proc = Process.Start(psi))
                {
                    if (proc == null)
                    {
                        ShowError("Não foi possível iniciar o interpretador Python do ULTRON.");
                        return 1;
                    }
                    if (consoleMode)
                    {
                        proc.WaitForExit();
                        return proc.ExitCode;
                    }
                    return 0;
                }
            }
            catch (Exception ex)
            {
                ShowError("Falha ao iniciar o U.L.T.R.O.N. Desktop (" + ex.GetType().Name + ").");
                return 1;
            }
        }

        private static bool IsConsoleMode(string[] args)
        {
            if (args == null || args.Length == 0)
            {
                return false;
            }
            string first = (args[0] ?? string.Empty).Trim().ToLowerInvariant();
            return first == "--doctor"
                || first == "--diagnostico"
                || first == "-d"
                || first == "--texto"
                || first == "--instalar-inicio"
                || first == "--remover-inicio"
                || first == "--help"
                || first == "-h";
        }

        private static bool TryResolvePython(string root, bool preferConsole, out string pythonExe, out string runtimeDir)
        {
            pythonExe = null;
            runtimeDir = null;

            string primaryDir = Path.Combine(root, "runtime", "python");
            if (TryFromDir(primaryDir, preferConsole, out pythonExe))
            {
                runtimeDir = primaryDir;
                return true;
            }

            bool isInstalled = string.Equals(Environment.GetEnvironmentVariable("ULTRON_INSTALLED"), "1", StringComparison.Ordinal);
            bool isDev = !isInstalled && (
                Directory.Exists(Path.Combine(root, ".git")) ||
                string.Equals(Environment.GetEnvironmentVariable("ULTRON_DEV"), "1", StringComparison.Ordinal)
            );
            bool allowSecondary = string.Equals(Environment.GetEnvironmentVariable("ULTRON_ALLOW_SECONDARY_RUNTIME"), "1", StringComparison.Ordinal)
                || (isDev && !Directory.Exists(primaryDir));

            if (allowSecondary)
            {
                string secondaryDir = Path.Combine(root, "build", "runtime", "python");
                if (TryFromDir(secondaryDir, preferConsole, out pythonExe))
                {
                    runtimeDir = secondaryDir;
                    return true;
                }
            }

            if (isDev)
            {
                string[] venvNames = new[] { "venv", ".venv" };
                for (int i = 0; i < venvNames.Length; i++)
                {
                    string venvDir = Path.Combine(root, venvNames[i]);
                    string scriptsDir = Path.Combine(venvDir, "Scripts");
                    if (TryFromDir(scriptsDir, preferConsole, out pythonExe))
                    {
                        runtimeDir = venvDir;
                        return true;
                    }
                }
            }

            return false;
        }

        private static bool TryFromDir(string dir, bool preferConsole, out string exePath)
        {
            exePath = null;
            if (!Directory.Exists(dir))
            {
                return false;
            }
            string py = Path.Combine(dir, "python.exe");
            string pyw = Path.Combine(dir, "pythonw.exe");
            if (preferConsole)
            {
                if (File.Exists(py))
                {
                    exePath = py;
                    return true;
                }
                return false;
            }
            if (File.Exists(pyw))
            {
                exePath = pyw;
                return true;
            }
            if (File.Exists(py))
            {
                exePath = py;
                return true;
            }
            return false;
        }

        private static string BuildArguments(string scriptPath, string[] args)
        {
            var sb = new StringBuilder();
            sb.Append(QuoteArg(scriptPath));
            if (args != null)
            {
                for (int i = 0; i < args.Length; i++)
                {
                    if (!string.IsNullOrEmpty(args[i]))
                    {
                        sb.Append(' ');
                        sb.Append(QuoteArg(args[i]));
                    }
                }
            }
            return sb.ToString();
        }

        private static string QuoteArg(string arg)
        {
            if (string.IsNullOrEmpty(arg))
            {
                return "\"\"";
            }
            if (arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
            {
                return arg;
            }
            var sb = new StringBuilder("\"");
            int backslashes = 0;
            for (int i = 0; i < arg.Length; i++)
            {
                char ch = arg[i];
                if (ch == '\\')
                {
                    backslashes++;
                }
                else if (ch == '"')
                {
                    sb.Append('\\', backslashes * 2 + 1);
                    sb.Append('"');
                    backslashes = 0;
                }
                else
                {
                    if (backslashes > 0)
                    {
                        sb.Append('\\', backslashes);
                        backslashes = 0;
                    }
                    sb.Append(ch);
                }
            }
            if (backslashes > 0)
            {
                sb.Append('\\', backslashes * 2);
            }
            sb.Append('"');
            return sb.ToString();
        }

        private static void ApplyIsolatedEnvironment(ProcessStartInfo psi, string runtimeDir)
        {
            psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            psi.EnvironmentVariables["OPENBLAS_NUM_THREADS"] = "1";
            psi.EnvironmentVariables.Remove("PYTHONPATH");
            psi.EnvironmentVariables.Remove("PYTHONHOME");

            string sysRoot = Environment.GetEnvironmentVariable("SYSTEMROOT");
            if (string.IsNullOrEmpty(sysRoot))
            {
                sysRoot = @"C:\Windows";
            }
            var pathEntries = new List<string>();
            if (!string.IsNullOrEmpty(runtimeDir))
            {
                pathEntries.Add(runtimeDir);
                string scripts = Path.Combine(runtimeDir, "Scripts");
                if (Directory.Exists(scripts))
                {
                    pathEntries.Add(scripts);
                }
            }
            pathEntries.Add(Path.Combine(sysRoot, "System32"));
            pathEntries.Add(sysRoot);
            psi.EnvironmentVariables["PATH"] = string.Join(";", pathEntries.ToArray());
        }

        private static void ShowError(string message)
        {
            MessageBox.Show(message, AppName, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
