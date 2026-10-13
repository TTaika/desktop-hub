// Desktop Hub overlay demo: renders the hub page with Ultralight (CPU renderer) into a per-pixel-alpha
// layered window that covers the second monitor. The window is owned by Progman, so it sits above the
// wallpaper (any Wallpaper Engine wallpaper, scenes included) and below normal windows. Fully transparent
// pixels pass clicks through to the desktop, so only the tiles take the mouse.
//
//   hub_overlay [--url http://127.0.0.1:8765/] [--monitor N] [--fps 60] [--snapshot frame.bgra [--snapshot-at 8]] [--gc seconds] [--purge seconds] [--offscreen 1]
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using HubOverlay;

static unsafe class Program
{
    // The page draws its own gradient or video background; over a Wallpaper Engine wallpaper we want neither.
    // (Glass tiles turn denser by themselves: hub.css checks for backdrop-filter, which Ultralight lacks.)
    const string OverlayCss = @"
html, body, body.has-bg { background: transparent !important; background-image: none !important; }
.bg-media, .bg-dim { display: none !important; }";

    // Ticks fast while anything on the page moves and slows down once it has been still for a moment,
    // so springs look smooth without paying for 60 Hz while the screen just sits there.
    const int IdleMs = 50, SettleMs = 400;
    static int activeMs = 16;
    static bool fast;
    static long lastPaint;

    static IntPtr renderer, view, hwnd, memDC;
    static byte* dib;
    static int width, height, posX, posY;
    static double scale = 1;
    static int cursor = UL.CursorPointer;
    static bool tracking;
    static StreamWriter log;
    static readonly Stopwatch clock = Stopwatch.StartNew();
    static long lastStats = -1, retryAt;
    static bool offscreen;        // --offscreen 1: render but never show, for measuring without touching the screen
    static string url = "http://127.0.0.1:8765/";
    static string snapshot;
    static int snapshotAt = 8;
    static int painted, gcSeconds = 10, renderThreads;   // 0 = Ultralight decides
    static double frameMs, maxFrameMs, updateMs, renderMs, presentMs;
    static long dirtyPixels;
    static long lastGc, lastPurge;
    static int purgeSeconds = 10;

    // kept in fields so the GC never frees a callback that native code still holds
    static readonly Win.WndProc wndProc = WndProc;
    static readonly UL.ConsoleMessage onConsole = OnConsole;
    static readonly UL.FrameEvent onFinish = (_, _, _, main, url) => { if (main) Log($"loaded {UL.Str(url)}"); };
    static readonly UL.FailLoading onFail = (_, _, _, main, url, desc, _, code) =>
    {
        Log($"FAILED {UL.Str(url)}: {UL.Str(desc)} ({code})");
        if (main) retryAt = clock.ElapsedMilliseconds + 3000;   // e.g. the server isn't up yet right after login
    };
    static readonly UL.ChangeCursor onCursor = (_, _, c) => cursor = c;
    static readonly UL.FrameEvent onWindowReady = (_, _, _, main, _) => { if (main) HostFetch.Install(view, url); };

    static int Main(string[] args)
    {
        int monitorIndex = -1;
        for (int i = 0; i + 1 < args.Length; i += 2)
            switch (args[i])
            {
                case "--url": url = args[i + 1]; break;
                case "--monitor": monitorIndex = int.Parse(args[i + 1]); break;
                case "--fps": activeMs = 1000 / Math.Max(1, int.Parse(args[i + 1])); break;
                case "--snapshot": snapshot = Path.GetFullPath(args[i + 1]); break;
                case "--snapshot-at": snapshotAt = int.Parse(args[i + 1]); break;
                case "--gc": gcSeconds = int.Parse(args[i + 1]); break;
                case "--threads": renderThreads = int.Parse(args[i + 1]); break;
                case "--offscreen": offscreen = args[i + 1] == "1"; break;
                case "--purge": purgeSeconds = int.Parse(args[i + 1]); break;
            }

        // one overlay at a time; off-screen test copies don't count
        using var single = new System.Threading.Mutex(true, offscreen ? null : @"Local\DesktopHubOverlay", out bool first);
        if (!first) return 0;

        // JavaScriptCore's parallel GC starts helper threads and lets them exit when idle, over and over; every
        // new thread left allocator memory behind (about 0.15 MB/s on this page). Collecting on the main thread
        // instead keeps the thread count fixed and the memory flat; for a page this small it costs nothing visible.
        // JSC reads these at start-up through the C runtime, which keeps its own copy of the environment.
        foreach (var (key, value) in new[] { ("JSC_useConcurrentGC", "false"), ("JSC_numberOfGCMarkers", "1") })
        {
            Environment.SetEnvironmentVariable(key, value);
            Win._wputenv_s(key, value);
        }

        var dir = AppContext.BaseDirectory;
        log = new StreamWriter(Path.Combine(dir, "overlay.log"), false) { AutoFlush = true };
        Win.SetProcessDpiAwarenessContext(new IntPtr(-4));     // per-monitor v2: work in real pixels
        PickMonitor(monitorIndex);
        Log($"monitor {width}x{height} at {posX},{posY}, scale {scale}");

        CreateRenderer(dir);
        CreateWindow();
        CreateView(url);

        Win.SetTimer(hwnd, (IntPtr)1, IdleMs, IntPtr.Zero);
        while (Win.GetMessage(out var msg, IntPtr.Zero, 0, 0) > 0)
        {
            Win.TranslateMessage(ref msg);
            Win.DispatchMessage(ref msg);
        }
        return 0;
    }

    // --monitor N picks the Nth monitor; by default the first one that isn't the primary.
    static void PickMonitor(int index)
    {
        var monitors = new System.Collections.Generic.List<(IntPtr handle, Win.MONITORINFO info)>();
        Win.EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (IntPtr mon, IntPtr _, ref Win.RECT _, IntPtr _) =>
        {
            var info = new Win.MONITORINFO { Size = Marshal.SizeOf<Win.MONITORINFO>() };
            Win.GetMonitorInfo(mon, ref info);
            monitors.Add((mon, info));
            return true;
        }, IntPtr.Zero);

        var (handle, m) = index >= 0 && index < monitors.Count ? monitors[index]
            : monitors.Find(x => (x.info.Flags & 1) == 0 /* not MONITORINFOF_PRIMARY */) is var s && s.handle != IntPtr.Zero ? s
            : monitors[0];
        posX = m.Monitor.Left; posY = m.Monitor.Top;
        width = m.Monitor.Right - m.Monitor.Left; height = m.Monitor.Bottom - m.Monitor.Top;
        if (Win.GetDpiForMonitor(handle, 0, out var dpi, out _) == 0) scale = dpi / 96.0;
    }

    static void CreateRenderer(string dir)
    {
        UL.ulEnablePlatformFontLoader();
        UL.With(dir, UL.ulEnablePlatformFileSystem);
        UL.With(Path.Combine(dir, "ultralight.log"), UL.ulEnableDefaultLogger);

        var config = UL.ulCreateConfig();
        UL.With("resources/", p => UL.ulConfigSetResourcePathPrefix(config, p));
        UL.With(Path.Combine(dir, "cache"), p => UL.ulConfigSetCachePath(config, p));
        UL.With(OverlayCss, p => UL.ulConfigSetUserStylesheet(config, p));
        UL.ulConfigSetMemoryCacheSize(config, 8 * 1024 * 1024);
        if (renderThreads > 0) UL.ulConfigSetNumRendererThreads(config, (uint)renderThreads);
        renderer = UL.ulCreateRenderer(config);
    }

    static void CreateView(string url)
    {
        var config = UL.ulCreateViewConfig();
        UL.ulViewConfigSetIsAccelerated(config, false);
        UL.ulViewConfigSetIsTransparent(config, true);
        UL.ulViewConfigSetInitialDeviceScale(config, scale);
        UL.With("Segoe UI", f => { UL.ulViewConfigSetFontFamilySansSerif(config, f); UL.ulViewConfigSetFontFamilyStandard(config, f); });
        view = UL.ulCreateView(renderer, (uint)width, (uint)height, config, IntPtr.Zero);
        UL.ulViewSetAddConsoleMessageCallback(view, onConsole, IntPtr.Zero);
        UL.ulViewSetFinishLoadingCallback(view, onFinish, IntPtr.Zero);
        UL.ulViewSetFailLoadingCallback(view, onFail, IntPtr.Zero);
        UL.ulViewSetChangeCursorCallback(view, onCursor, IntPtr.Zero);
        UL.ulViewSetWindowObjectReadyCallback(view, onWindowReady, IntPtr.Zero);
        UL.ulViewFocus(view);
        UL.With(url, u => UL.ulViewLoadURL(view, u));
    }

    static void CreateWindow()
    {
        var wc = new Win.WNDCLASSEX
        {
            Size = Marshal.SizeOf<Win.WNDCLASSEX>(), WndProc = wndProc, ClassName = "DesktopHubOverlay",
            Instance = Win.GetModuleHandle(IntPtr.Zero),
        };
        Win.RegisterClassEx(ref wc);
        hwnd = Win.CreateWindowEx(Win.WS_EX_LAYERED | Win.WS_EX_TOOLWINDOW | Win.WS_EX_NOACTIVATE, wc.ClassName,
                                  "Desktop Hub", Win.WS_POPUP, posX, posY, width, height,
                                  IntPtr.Zero, IntPtr.Zero, wc.Instance, IntPtr.Zero);

        // Owned by the desktop window: always above it (and the wallpaper), always below normal windows.
        var progman = Win.FindWindow("Progman", null);
        Win.SetWindowLongPtr(hwnd, Win.GWLP_HWNDPARENT, progman);

        // 32-bit top-down DIB the frames are copied into; UpdateLayeredWindow reads it with per-pixel alpha.
        var bmi = new Win.BITMAPINFOHEADER
        {
            Size = Marshal.SizeOf<Win.BITMAPINFOHEADER>(), Width = width, Height = -height, Planes = 1, BitCount = 32,
        };
        memDC = Win.CreateCompatibleDC(IntPtr.Zero);
        var bitmap = Win.CreateDIBSection(memDC, ref bmi, 0, out var bits, IntPtr.Zero, 0);
        Win.SelectObject(memDC, bitmap);
        dib = (byte*)bits;
        if (!offscreen) Win.ShowWindow(hwnd, Win.SW_SHOWNOACTIVATE);
    }

    static void Frame()
    {
        long t0 = Stopwatch.GetTimestamp();
        HostFetch.Deliver(view);
        UL.ulUpdate(renderer);
        long t1 = Stopwatch.GetTimestamp();
        UL.ulRender(renderer);
        long t2 = Stopwatch.GetTimestamp();

        var surface = UL.ulViewGetSurface(view);
        var dirty = UL.ulSurfaceGetDirtyBounds(surface);
        if (!dirty.IsEmpty)
        {
            painted++;
            lastPaint = clock.ElapsedMilliseconds;
            if (!fast) { fast = true; Win.SetTimer(hwnd, (IntPtr)1, (uint)activeMs, IntPtr.Zero); }
            // Ultralight's bitmap is BGRA, premultiplied: exactly what UpdateLayeredWindow wants.
            int top = Math.Max(0, dirty.Top), bottom = Math.Min(height, dirty.Bottom);
            int left = Math.Max(0, dirty.Left), right = Math.Min(width, dirty.Right);
            int rowBytes = (int)UL.ulSurfaceGetRowBytes(surface), stride = width * 4, bytes = (right - left) * 4;
            var src = (byte*)UL.ulSurfaceLockPixels(surface);
            for (int y = top; y < bottom; y++)
                Buffer.MemoryCopy(src + y * rowBytes + left * 4, dib + y * stride + left * 4, bytes, bytes);
            UL.ulSurfaceUnlockPixels(surface);
            UL.ulSurfaceClearDirtyBounds(surface);

            // Only the changed rectangle goes to the compositor, not the whole 8 MB frame.
            var dst = new Win.POINT { X = posX, Y = posY };
            var size = new Win.SIZE { Cx = width, Cy = height };
            var origin = new Win.POINT();
            var blend = new Win.BLENDFUNCTION { SourceAlpha = 255, AlphaFormat = 1 /* AC_SRC_ALPHA */ };
            var rect = new Win.RECT { Left = left, Top = top, Right = right, Bottom = bottom };
            var info = new Win.UPDATELAYEREDWINDOWINFO
            {
                Size = sizeof(Win.UPDATELAYEREDWINDOWINFO), PptDst = &dst, Psize = &size, HdcSrc = memDC,
                PptSrc = &origin, Pblend = &blend, Flags = 2 /* ULW_ALPHA */, PrcDirty = &rect,
            };
            if (!offscreen) Win.UpdateLayeredWindowIndirect(hwnd, &info);
            long t3 = Stopwatch.GetTimestamp();
            double ms = (t3 - t0) * 1000.0 / Stopwatch.Frequency;
            frameMs += ms;
            updateMs += (t1 - t0) * 1000.0 / Stopwatch.Frequency;
            renderMs += (t2 - t1) * 1000.0 / Stopwatch.Frequency;
            presentMs += (t3 - t2) * 1000.0 / Stopwatch.Frequency;
            dirtyPixels += (long)(right - left) * (bottom - top);
            maxFrameMs = Math.Max(maxFrameMs, ms);
        }
        else if (fast && clock.ElapsedMilliseconds - lastPaint > SettleMs)
        {
            fast = false;
            Win.SetTimer(hwnd, (IntPtr)1, IdleMs, IntPtr.Zero);
        }

        long sec = clock.ElapsedMilliseconds / 10000;
        if (sec != lastStats) { lastStats = sec; Stats(); }
        if (gcSeconds > 0 && clock.ElapsedMilliseconds - lastGc > gcSeconds * 1000)
        {
            // JavaScriptCore collects lazily; a nudge every few seconds keeps its heap small.
            lastGc = clock.ElapsedMilliseconds;
            var ctx = UL.ulViewLockJSContext(view);
            UL.JSGarbageCollect(ctx);
            UL.ulViewUnlockJSContext(view);
        }
        if (purgeSeconds > 0 && clock.ElapsedMilliseconds - lastPurge > purgeSeconds * 1000)
        {
            // Ultralight's paint caches only shrink when asked; without this, any page that animates grows
            // by ~0.2 MB/s. (It looked harmful once, but that was the GC thread churn fixed above.)
            lastPurge = clock.ElapsedMilliseconds;
            UL.ulPurgeMemory(renderer);
        }
        if (retryAt > 0 && clock.ElapsedMilliseconds > retryAt)
        {
            retryAt = 0;
            UL.With(url, u => UL.ulViewLoadURL(view, u));
        }
        if (snapshot != null && clock.ElapsedMilliseconds > snapshotAt * 1000) { Snapshot(snapshot); snapshot = null; }
    }

    // --snapshot file.bgra: after 8 s (--snapshot-at seconds), writes the current frame as raw premultiplied BGRA (width*height*4 bytes),
    // to check the rendering when windows cover the monitor.
    static void Snapshot(string path)
    {
        using var f = File.Create(path);
        f.Write(new ReadOnlySpan<byte>(dib, width * height * 4));
        Log($"snapshot {width}x{height} -> {path}");
    }

    // Memory every 10 s. Ultralight runs in this one process, so these numbers are the whole cost.
    static void Stats()
    {
        using var p = Process.GetCurrentProcess();
        Log($"memory: private {p.PrivateMemorySize64 >> 20} MB, working set {p.WorkingSet64 >> 20} MB, " +
            $"threads {p.Threads.Count}; " +
            $"frames painted {painted}/10 s, avg {Avg(frameMs)} ms (js+layout {Avg(updateMs)}, paint {Avg(renderMs)}, " +
            $"present {Avg(presentMs)}), max {maxFrameMs:F1} ms, avg dirty {(painted > 0 ? dirtyPixels / painted / 1000 : 0)}k px");
        painted = 0; frameMs = maxFrameMs = updateMs = renderMs = presentMs = 0; dirtyPixels = 0;
    }

    static string Avg(double total) => (painted > 0 ? total / painted : 0).ToString("F1");

    static IntPtr WndProc(IntPtr h, uint msg, IntPtr wParam, IntPtr lParam)
    {
        switch (msg)
        {
            case Win.WM_TIMER: Frame(); return IntPtr.Zero;
            case Win.WM_MOUSEACTIVATE: return new IntPtr(Win.MA_NOACTIVATE);   // clicking a tile doesn't steal focus
            case Win.WM_MOUSEMOVE:
                if (!tracking)
                {
                    var tme = new Win.TRACKMOUSEEVENT { Size = Marshal.SizeOf<Win.TRACKMOUSEEVENT>(), Flags = 2, Hwnd = h };
                    tracking = Win.TrackMouseEvent(ref tme);
                }
                Mouse(UL.MouseMoved, lParam, UL.ButtonNone); return IntPtr.Zero;
            case Win.WM_MOUSELEAVE:
                tracking = false;
                Fire(UL.ulCreateMouseEvent(UL.MouseMoved, -1, -1, UL.ButtonNone)); return IntPtr.Zero;
            case Win.WM_LBUTTONDOWN: Mouse(UL.MouseDown, lParam, UL.ButtonLeft); return IntPtr.Zero;
            case Win.WM_LBUTTONUP: Mouse(UL.MouseUp, lParam, UL.ButtonLeft); return IntPtr.Zero;
            case Win.WM_RBUTTONDOWN: Mouse(UL.MouseDown, lParam, UL.ButtonRight); return IntPtr.Zero;
            case Win.WM_RBUTTONUP: Mouse(UL.MouseUp, lParam, UL.ButtonRight); return IntPtr.Zero;
            case Win.WM_MBUTTONDOWN: Mouse(UL.MouseDown, lParam, UL.ButtonMiddle); return IntPtr.Zero;
            case Win.WM_MBUTTONUP: Mouse(UL.MouseUp, lParam, UL.ButtonMiddle); return IntPtr.Zero;
            case Win.WM_MOUSEWHEEL:
                var scroll = UL.ulCreateScrollEvent(UL.ScrollByPixel, 0, (short)((long)wParam >> 16));
                UL.ulViewFireScrollEvent(view, scroll);
                UL.ulDestroyScrollEvent(scroll);
                return IntPtr.Zero;
            case Win.WM_SETCURSOR when ((long)lParam & 0xFFFF) == Win.HTCLIENT:
                Win.SetCursor(Win.LoadCursor(IntPtr.Zero, new IntPtr(cursor == UL.CursorHand ? Win.IDC_HAND : Win.IDC_ARROW)));
                return new IntPtr(1);
            case Win.WM_DESTROY: Win.PostQuitMessage(0); return IntPtr.Zero;
        }
        return Win.DefWindowProc(h, msg, wParam, lParam);
    }

    // Window messages carry real pixels; Ultralight wants page units.
    static void Mouse(int type, IntPtr lParam, int button)
    {
        int x = (short)((long)lParam & 0xFFFF), y = (short)(((long)lParam >> 16) & 0xFFFF);
        Fire(UL.ulCreateMouseEvent(type, (int)(x / scale), (int)(y / scale), button));
    }

    static void Fire(IntPtr evt)
    {
        UL.ulViewFireMouseEvent(view, evt);
        UL.ulDestroyMouseEvent(evt);
    }

    static void OnConsole(IntPtr _, IntPtr __, int source, int level, IntPtr message, uint line, uint column, IntPtr sourceId)
    {
        string lvl = level switch { 2 => "warn", 3 => "ERROR", _ => "log" };
        Log($"console {lvl}: {UL.Str(message)}  ({UL.Str(sourceId)}:{line})");
    }

    internal static void Log(string s)        // also called from request threads (HostFetch)
    {
        var line = $"{DateTime.Now:HH:mm:ss} {s}";
        lock (log)
        {
            Console.WriteLine(line);
            log.WriteLine(line);
        }
    }
}
