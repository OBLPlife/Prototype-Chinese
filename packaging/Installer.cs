using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("虐杀原形 简体中文补丁")]
[assembly: AssemblyDescription("安装和还原 Prototype 简体中文本地化")]
[assembly: AssemblyVersion("0.2.13.0")]
[assembly: AssemblyFileVersion("0.2.13.0")]

internal sealed class Result
{
    internal readonly int Code;
    internal readonly string Message;
    internal Result(int code, string message) { Code = code; Message = message; }
}

internal static class Installer
{
#if DELTA_PACKAGE
    internal const string Title = "虐杀原形 简体中文补丁 0.2.13 差分版";
#else
    internal const string Title = "虐杀原形 简体中文补丁 0.2.13";
#endif
    internal const string Warning = "所需资源存在变化，可能无法达到预期效果，是否继续安装？";
    static readonly string Exe = Assembly.GetExecutingAssembly().Location;
    static readonly string Game = Path.GetDirectoryName(Exe);

    static bool GameRunning()
    {
        foreach (Process process in Process.GetProcessesByName("prototypef"))
        {
            using (process)
            {
                try
                {
                    if (String.Equals(Path.GetDirectoryName(process.MainModule.FileName), Game,
                                      StringComparison.OrdinalIgnoreCase)) return true;
                }
                catch (Win32Exception) { }
                catch (InvalidOperationException) { }
            }
        }
        return false;
    }

    static void UnpackTools(string destination)
    {
        using (Stream data = Assembly.GetExecutingAssembly().GetManifestResourceStream("bootstrap.zip"))
        using (var zip = new ZipArchive(data, ZipArchiveMode.Read))
        {
            foreach (ZipArchiveEntry entry in zip.Entries)
            {
                if (entry.FullName != Path.GetFileName(entry.FullName))
                    throw new InvalidDataException("安装组件路径无效。");
                using (Stream src = entry.Open())
                using (Stream dst = new FileStream(Path.Combine(destination, entry.Name),
                                                   FileMode.CreateNew, FileAccess.Write))
                    src.CopyTo(dst);
            }
        }
    }

    static string ArgPath(string value) { return "\"" + value.Replace('\\', '/') + "\""; }

    static Result Execute(bool restore, Func<bool> confirm, Action<string> status)
    {
        if (!File.Exists(Path.Combine(Game, "cementfiles.p3d")) &&
            !(File.Exists(Path.Combine(Game, "art.rcf")) && File.Exists(Path.Combine(Game, "scripts.rcf"))) &&
            !File.Exists(Path.Combine(Game, "PrototypeZh", "setup.pending")))
            return new Result(1, "请把安装器放进《虐杀原形》的游戏目录，与 cementfiles.p3d 放在一起。");
        if (GameRunning()) return new Result(1, "请先退出正在运行的《虐杀原形》。");
        string temp = Path.Combine(Path.GetTempPath(), "PrototypeZh-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temp);
        try
        {
            UnpackTools(temp);
            var start = new ProcessStartInfo
            {
                FileName = Path.Combine(temp, "python.exe"),
                WorkingDirectory = temp,
                Arguments = "-I -B -X utf8 release_install.py " + (restore ? "restore" : "install") +
                            " --ipc --game " + ArgPath(Game) + " --package " + ArgPath(Exe),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardInput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8
            };
            using (var child = Process.Start(start))
            {
                var errors = child.StandardError.ReadToEndAsync();
                string line, result = null;
                while ((line = child.StandardOutput.ReadLine()) != null)
                {
                    int split = line.IndexOf('\t');
                    if (split < 0) continue;
                    string type = line.Substring(0, split), message = line.Substring(split + 1);
                    if (type == "progress") status(message);
                    else if (type == "warning")
                    {
                        child.StandardInput.WriteLine(confirm() ? "yes" : "no");
                        child.StandardInput.Flush();
                    }
                    else if (type == "result") result = message;
                }
                child.WaitForExit();
                string error = errors.GetAwaiter().GetResult().Trim();
                if (result == null)
                    result = error.Length == 0 ? "安装组件未能完成操作。" : error;
                return new Result(child.ExitCode, result);
            }
        }
        finally
        {
            try { Directory.Delete(temp, true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    internal static Result Run(bool restore, Func<bool> confirm, Action<string> status)
    {
        Result result;
        bool warned = false;
        try
        {
            string lockName;
            using (var sha = SHA256.Create())
                lockName = @"Local\PrototypeZhSetup-" +
                    BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(Game.ToUpperInvariant()))).Replace("-", "");
            using (var mutex = new Mutex(false, lockName))
            {
                bool acquired;
                try { acquired = mutex.WaitOne(0); }
                catch (AbandonedMutexException) { acquired = true; }
                if (!acquired) return new Result(1, "此目录中已有一个汉化安装操作正在进行。");
                try
                {
                    result = Execute(restore, delegate { warned = true; return confirm(); }, status);
                }
                finally { mutex.ReleaseMutex(); }
            }
        }
        catch (Exception ex) { result = new Result(1, ex.Message); }
        try
        {
            string log = (warned ? Warning + Environment.NewLine : "") + result.Message;
            File.WriteAllText(Path.ChangeExtension(Exe, ".log"), log + Environment.NewLine, new UTF8Encoding(false));
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        return result;
    }

    [STAThread]
    static int Main(string[] args)
    {
        bool quiet = false, restore = false, accept = false;
        foreach (string arg in args)
        {
            switch (arg.ToLowerInvariant())
            {
                case "/quiet": quiet = true; break;
                case "/restore": restore = true; break;
                case "/accept-risk": accept = true; break;
                default: return 1;
            }
        }
        if (quiet) return Run(restore, delegate { return accept; }, delegate { }).Code;
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        using (var form = new PatchWindow()) Application.Run(form);
        return 0;
    }
}

internal sealed class PatchWindow : Form
{
    readonly Button install = new Button(), restore = new Button();
    readonly Label status = new Label();
    readonly BackgroundWorker worker = new BackgroundWorker();

    internal PatchWindow()
    {
        Text = Installer.Title;
        Font = new Font("Microsoft YaHei UI", 10F);
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(380, 105);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        install.Text = "安装"; install.Name = "InstallButton"; install.SetBounds(60, 15, 120, 40);
        restore.Text = "还原"; restore.Name = "RestoreButton"; restore.SetBounds(200, 15, 120, 40);
        status.SetBounds(8, 65, 364, 30);
        status.TextAlign = ContentAlignment.MiddleCenter;
        Controls.AddRange(new Control[] { install, restore, status });
        worker.WorkerReportsProgress = true;
        install.Click += delegate { Start(false); };
        restore.Click += delegate { Start(true); };
        worker.DoWork += delegate(object sender, DoWorkEventArgs e)
        {
            e.Result = Installer.Run((bool)e.Argument,
                delegate { return (bool)Invoke(new Func<bool>(Ask)); },
                delegate(string text) { worker.ReportProgress(0, text); });
        };
        worker.ProgressChanged += delegate(object sender, ProgressChangedEventArgs e) { status.Text = (string)e.UserState; };
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e)
        {
            install.Enabled = restore.Enabled = true;
            Result r = e.Error == null ? (Result)e.Result : new Result(1, e.Error.Message);
            status.Text = r.Code == 1 ? "" : r.Message;
            if (r.Code != 2)
                MessageBox.Show(this, r.Message, Installer.Title, MessageBoxButtons.OK,
                                r.Code == 0 ? MessageBoxIcon.Information : MessageBoxIcon.Error);
        };
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (worker.IsBusy) e.Cancel = true; };
    }

    bool Ask()
    {
        return MessageBox.Show(this, Installer.Warning, Installer.Title, MessageBoxButtons.YesNo,
                               MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) == DialogResult.Yes;
    }

    void Start(bool reverting)
    {
        install.Enabled = restore.Enabled = false;
        status.Text = "正在准备…";
        worker.RunWorkerAsync(reverting);
    }
}
