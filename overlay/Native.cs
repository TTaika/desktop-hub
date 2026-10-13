// P/Invoke declarations: the Ultralight 1.3 C API (Ultralight.dll, AppCore.dll) and the bits of Win32 we use.
using System;
using System.Runtime.InteropServices;

namespace HubOverlay;

[StructLayout(LayoutKind.Sequential)]
struct ULIntRect { public int Left, Top, Right, Bottom; public bool IsEmpty => Right <= Left || Bottom <= Top; }

static class UL
{
    const string Lib = "Ultralight", App = "AppCore";

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void ConsoleMessage(IntPtr userData, IntPtr view, int source, int level, IntPtr message,
                                        uint line, uint column, IntPtr sourceId);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void FrameEvent(IntPtr userData, IntPtr view, ulong frameId,
                                    [MarshalAs(UnmanagedType.I1)] bool isMainFrame, IntPtr url);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void FailLoading(IntPtr userData, IntPtr view, ulong frameId,
                                     [MarshalAs(UnmanagedType.I1)] bool isMainFrame, IntPtr url,
                                     IntPtr description, IntPtr errorDomain, int errorCode);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate void ChangeCursor(IntPtr userData, IntPtr view, int cursor);

    public const int CursorPointer = 0, CursorHand = 2;
    public const int MouseMoved = 0, MouseDown = 1, MouseUp = 2;
    public const int ButtonNone = 0, ButtonLeft = 1, ButtonMiddle = 2, ButtonRight = 3;
    public const int ScrollByPixel = 0;

    [DllImport(Lib)] public static extern IntPtr ulCreateString([MarshalAs(UnmanagedType.LPUTF8Str)] string s);
    [DllImport(Lib)] public static extern void ulDestroyString(IntPtr s);
    [DllImport(Lib)] public static extern IntPtr ulStringGetData(IntPtr s);

    [DllImport(Lib)] public static extern IntPtr ulCreateConfig();
    [DllImport(Lib)] public static extern void ulConfigSetResourcePathPrefix(IntPtr config, IntPtr prefix);
    [DllImport(Lib)] public static extern void ulConfigSetCachePath(IntPtr config, IntPtr path);
    [DllImport(Lib)] public static extern void ulConfigSetUserStylesheet(IntPtr config, IntPtr css);
    [DllImport(Lib)] public static extern void ulConfigSetMemoryCacheSize(IntPtr config, uint bytes);
    [DllImport(Lib)] public static extern void ulConfigSetNumRendererThreads(IntPtr config, uint n);

    [DllImport(App)] public static extern void ulEnablePlatformFontLoader();
    [DllImport(App)] public static extern void ulEnablePlatformFileSystem(IntPtr baseDir);
    [DllImport(App)] public static extern void ulEnableDefaultLogger(IntPtr logPath);

    [DllImport(Lib)] public static extern IntPtr ulCreateRenderer(IntPtr config);
    [DllImport(Lib)] public static extern void ulUpdate(IntPtr renderer);
    [DllImport(Lib)] public static extern void ulRender(IntPtr renderer);
    [DllImport(Lib)] public static extern void ulPurgeMemory(IntPtr renderer);

    [DllImport(Lib)] public static extern IntPtr ulCreateViewConfig();
    [DllImport(Lib)] public static extern void ulViewConfigSetIsAccelerated(IntPtr config, [MarshalAs(UnmanagedType.I1)] bool on);
    [DllImport(Lib)] public static extern void ulViewConfigSetIsTransparent(IntPtr config, [MarshalAs(UnmanagedType.I1)] bool on);
    [DllImport(Lib)] public static extern void ulViewConfigSetInitialDeviceScale(IntPtr config, double scale);
    [DllImport(Lib)] public static extern void ulViewConfigSetFontFamilySansSerif(IntPtr config, IntPtr font);
    [DllImport(Lib)] public static extern void ulViewConfigSetFontFamilyStandard(IntPtr config, IntPtr font);

    [DllImport(Lib)] public static extern IntPtr ulCreateView(IntPtr renderer, uint width, uint height, IntPtr viewConfig, IntPtr session);
    [DllImport(Lib)] public static extern void ulViewLoadURL(IntPtr view, IntPtr url);
    [DllImport(Lib)] public static extern void ulViewFocus(IntPtr view);
    [DllImport(Lib)] public static extern IntPtr ulViewGetSurface(IntPtr view);
    [DllImport(Lib)] public static extern void ulViewFireMouseEvent(IntPtr view, IntPtr evt);
    [DllImport(Lib)] public static extern void ulViewFireScrollEvent(IntPtr view, IntPtr evt);
    [DllImport(Lib)] public static extern void ulViewSetAddConsoleMessageCallback(IntPtr view, ConsoleMessage cb, IntPtr userData);
    [DllImport(Lib)] public static extern void ulViewSetFinishLoadingCallback(IntPtr view, FrameEvent cb, IntPtr userData);
    [DllImport(Lib)] public static extern void ulViewSetFailLoadingCallback(IntPtr view, FailLoading cb, IntPtr userData);
    [DllImport(Lib)] public static extern void ulViewSetChangeCursorCallback(IntPtr view, ChangeCursor cb, IntPtr userData);

    [DllImport(Lib)] public static extern IntPtr ulViewLockJSContext(IntPtr view);
    [DllImport(Lib)] public static extern void ulViewUnlockJSContext(IntPtr view);
    [DllImport(Lib)] public static extern void ulViewSetWindowObjectReadyCallback(IntPtr view, FrameEvent cb, IntPtr userData);
    [DllImport(Lib)] public static extern IntPtr ulViewEvaluateScript(IntPtr view, IntPtr js, IntPtr exception);

    // JavaScriptCore C API (exported by WebCore.dll), for the host functions the page can call
    const string JS = "WebCore";
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    public delegate IntPtr JSCallback(IntPtr ctx, IntPtr function, IntPtr thisObject, UIntPtr argc, IntPtr argv, IntPtr exception);
    [DllImport(JS)] public static extern void JSGarbageCollect(IntPtr ctx);
    [DllImport(JS)] public static extern IntPtr JSContextGetGlobalObject(IntPtr ctx);
    [DllImport(JS)] public static extern IntPtr JSStringCreateWithUTF8CString([MarshalAs(UnmanagedType.LPUTF8Str)] string s);
    [DllImport(JS)] public static extern void JSStringRelease(IntPtr s);
    [DllImport(JS)] public static extern UIntPtr JSStringGetMaximumUTF8CStringSize(IntPtr s);
    [DllImport(JS)] public static extern unsafe UIntPtr JSStringGetUTF8CString(IntPtr s, byte* buffer, UIntPtr size);
    [DllImport(JS)] public static extern IntPtr JSObjectMakeFunctionWithCallback(IntPtr ctx, IntPtr name, JSCallback cb);
    [DllImport(JS)] public static extern void JSObjectSetProperty(IntPtr ctx, IntPtr obj, IntPtr name, IntPtr value, uint attributes, IntPtr exception);
    [DllImport(JS)] public static extern IntPtr JSValueToStringCopy(IntPtr ctx, IntPtr value, IntPtr exception);
    [DllImport(JS)] public static extern double JSValueToNumber(IntPtr ctx, IntPtr value, IntPtr exception);
    [DllImport(JS)] public static extern IntPtr JSValueMakeUndefined(IntPtr ctx);
    [DllImport(JS)] public static extern IntPtr JSValueMakeNumber(IntPtr ctx, double value);
    [DllImport(JS)] public static extern IntPtr JSValueMakeString(IntPtr ctx, IntPtr str);
    [DllImport(JS)] public static extern IntPtr JSObjectGetProperty(IntPtr ctx, IntPtr obj, IntPtr name, IntPtr exception);
    [DllImport(JS)] [return: MarshalAs(UnmanagedType.I1)] public static extern bool JSObjectIsFunction(IntPtr ctx, IntPtr obj);
    [DllImport(JS)] [return: MarshalAs(UnmanagedType.I1)] public static extern bool JSValueIsObject(IntPtr ctx, IntPtr value);
    [DllImport(JS)] public static extern unsafe IntPtr JSObjectCallAsFunction(IntPtr ctx, IntPtr fn, IntPtr thisObject, UIntPtr argc, IntPtr* argv, IntPtr exception);

    // JS value -> .NET string
    public static unsafe string JsString(IntPtr ctx, IntPtr value)
    {
        var s = JSValueToStringCopy(ctx, value, IntPtr.Zero);
        try
        {
            int max = (int)JSStringGetMaximumUTF8CStringSize(s);
            var buf = new byte[max];
            fixed (byte* p = buf)
            {
                int n = (int)JSStringGetUTF8CString(s, p, (UIntPtr)max);
                return System.Text.Encoding.UTF8.GetString(buf, 0, Math.Max(0, n - 1));   // n counts the terminating 0
            }
        }
        finally { JSStringRelease(s); }
    }

    [DllImport(Lib)] public static extern IntPtr ulCreateMouseEvent(int type, int x, int y, int button);
    [DllImport(Lib)] public static extern void ulDestroyMouseEvent(IntPtr evt);
    [DllImport(Lib)] public static extern IntPtr ulCreateScrollEvent(int type, int dx, int dy);
    [DllImport(Lib)] public static extern void ulDestroyScrollEvent(IntPtr evt);

    [DllImport(Lib)] public static extern uint ulSurfaceGetWidth(IntPtr surface);
    [DllImport(Lib)] public static extern uint ulSurfaceGetHeight(IntPtr surface);
    [DllImport(Lib)] public static extern uint ulSurfaceGetRowBytes(IntPtr surface);
    [DllImport(Lib)] public static extern IntPtr ulSurfaceLockPixels(IntPtr surface);
    [DllImport(Lib)] public static extern void ulSurfaceUnlockPixels(IntPtr surface);
    [DllImport(Lib)] public static extern ULIntRect ulSurfaceGetDirtyBounds(IntPtr surface);
    [DllImport(Lib)] public static extern void ulSurfaceClearDirtyBounds(IntPtr surface);

    // ULString -> .NET string (null for a null pointer)
    public static string Str(IntPtr s) => s == IntPtr.Zero ? null : Marshal.PtrToStringUTF8(ulStringGetData(s));

    // Calls f with a temporary ULString.
    public static void With(string s, Action<IntPtr> f)
    {
        var u = ulCreateString(s);
        try { f(u); } finally { ulDestroyString(u); }
    }
}

static class Win
{
    public const int WS_POPUP = unchecked((int)0x80000000);
    public const int WS_EX_LAYERED = 0x80000, WS_EX_TOOLWINDOW = 0x80, WS_EX_NOACTIVATE = 0x8000000;
    public const int GWLP_HWNDPARENT = -8;
    public const int SW_SHOWNOACTIVATE = 4;
    public const uint WM_DESTROY = 0x2, WM_SETCURSOR = 0x20, WM_MOUSEACTIVATE = 0x21, WM_TIMER = 0x113,
        WM_MOUSEMOVE = 0x200, WM_LBUTTONDOWN = 0x201, WM_LBUTTONUP = 0x202, WM_RBUTTONDOWN = 0x204,
        WM_RBUTTONUP = 0x205, WM_MBUTTONDOWN = 0x207, WM_MBUTTONUP = 0x208, WM_MOUSEWHEEL = 0x20A,
        WM_MOUSELEAVE = 0x2A3;
    public const int MA_NOACTIVATE = 3, HTCLIENT = 1;
    public const int IDC_ARROW = 32512, IDC_HAND = 32649;

    public delegate IntPtr WndProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
    public delegate bool MonitorEnumProc(IntPtr monitor, IntPtr hdc, ref RECT rect, IntPtr data);

    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] public struct SIZE { public int Cx, Cy; }
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct MSG { public IntPtr Hwnd; public uint Message; public IntPtr WParam, LParam; public uint Time; public POINT Pt; }
    [StructLayout(LayoutKind.Sequential)] public struct MONITORINFO { public int Size; public RECT Monitor, Work; public uint Flags; }
    [StructLayout(LayoutKind.Sequential)] public struct BLENDFUNCTION { public byte Op, Flags, SourceAlpha, AlphaFormat; }
    [StructLayout(LayoutKind.Sequential)] public struct TRACKMOUSEEVENT { public int Size; public uint Flags; public IntPtr Hwnd; public uint HoverTime; }
    [StructLayout(LayoutKind.Sequential)]
    public struct BITMAPINFOHEADER
    {
        public int Size, Width, Height; public short Planes, BitCount; public uint Compression, SizeImage;
        public int XPelsPerMeter, YPelsPerMeter; public uint ClrUsed, ClrImportant;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct WNDCLASSEX
    {
        public int Size; public uint Style; public WndProc WndProc; public int ClsExtra, WndExtra;
        public IntPtr Instance, Icon, Cursor, Background; public string MenuName, ClassName; public IntPtr IconSm;
    }

    [DllImport("user32", CharSet = CharSet.Unicode)] public static extern ushort RegisterClassEx(ref WNDCLASSEX wc);
    [DllImport("user32", CharSet = CharSet.Unicode)]
    public static extern IntPtr CreateWindowEx(int exStyle, string cls, string title, int style, int x, int y, int w, int h,
                                               IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32")] public static extern IntPtr DefWindowProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32")] public static extern bool ShowWindow(IntPtr hwnd, int cmd);
    [DllImport("user32")] public static extern int GetMessage(out MSG msg, IntPtr hwnd, uint min, uint max);
    [DllImport("user32")] public static extern bool TranslateMessage(ref MSG msg);
    [DllImport("user32")] public static extern IntPtr DispatchMessage(ref MSG msg);
    [DllImport("user32")] public static extern void PostQuitMessage(int code);
    [DllImport("user32")] public static extern IntPtr SetTimer(IntPtr hwnd, IntPtr id, uint ms, IntPtr proc);
    [DllImport("user32", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32")] public static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);
    [DllImport("user32")] public static extern IntPtr LoadCursor(IntPtr instance, IntPtr name);
    [DllImport("user32")] public static extern IntPtr SetCursor(IntPtr cursor);
    [DllImport("user32")] public static extern bool TrackMouseEvent(ref TRACKMOUSEEVENT tme);
    [DllImport("user32")] public static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc proc, IntPtr data);
    [DllImport("user32")] public static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);
    [DllImport("user32")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    [DllImport("shcore")] public static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint dpiX, out uint dpiY);
    [StructLayout(LayoutKind.Sequential)]
    public unsafe struct UPDATELAYEREDWINDOWINFO
    {
        public int Size; public IntPtr HdcDst; public POINT* PptDst; public SIZE* Psize; public IntPtr HdcSrc;
        public POINT* PptSrc; public uint CrKey; public BLENDFUNCTION* Pblend; public uint Flags; public RECT* PrcDirty;
    }
    [DllImport("user32")] public static extern unsafe bool UpdateLayeredWindowIndirect(IntPtr hwnd, UPDATELAYEREDWINDOWINFO* info);

    [DllImport("gdi32")] public static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32")] public static extern IntPtr SelectObject(IntPtr hdc, IntPtr obj);
    [DllImport("gdi32")]
    public static extern IntPtr CreateDIBSection(IntPtr hdc, ref BITMAPINFOHEADER bmi, uint usage, out IntPtr bits, IntPtr section, uint offset);

    [DllImport("kernel32")] public static extern IntPtr GetModuleHandle(IntPtr name);
    // sets a variable in the C runtime's own copy of the environment, which native libraries read with getenv
    [DllImport("ucrtbase", CharSet = CharSet.Unicode)] public static extern int _wputenv_s(string name, string value);
}
