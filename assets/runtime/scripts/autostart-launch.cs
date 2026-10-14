using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
internal static class AutostartLauncher {
    [STAThread]
    private static int Main(string[] args) {
        string runtime = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string root = Path.GetDirectoryName(runtime);
        try {
            if (args.Length != 1 || !File.Exists(args[0])) return 2;
            string script = Path.Combine(root, "scripts", "autostart.ps1");
            if (!File.Exists(script)) return 3;
            ProcessStartInfo start = new ProcessStartInfo(args[0]);
            start.Arguments = "-NoLogo -NoProfile -NonInteractive -File \"" + script + "\"";
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            Process child = Process.Start(start);
            if (child == null) return 4;
            File.AppendAllText(Path.Combine(runtime, "autostart-launch.log"), DateTime.Now.ToString("o") + " launched=" + child.Id + Environment.NewLine);
            child.Dispose();
            return 0;
        } catch (Exception e) {
            File.AppendAllText(Path.Combine(runtime, "autostart-launch.log"), DateTime.Now.ToString("o") + " error=" + e.GetType().Name + Environment.NewLine);
            return 1;
        }
    }
}
