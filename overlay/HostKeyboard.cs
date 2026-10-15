// Typing into the page. The overlay never takes the keyboard focus (WS_EX_NOACTIVATE), so clicking a tile
// doesn't pull the focus away from your game or window. A text field that wants keys calls
// __hostKeyboard(1) when it is clicked: the window then takes the focus, and key messages go to the page
// until it calls __hostKeyboard(0) or another window gets the focus, which calls the page's
// __hostKeyboardLost() so the field can blur. The window then goes back to the bottom of the z-order,
// just above the desktop. Windows lets this process take the foreground because the click was its input.
using System;

namespace HubOverlay;

static class HostKeyboard
{
    static readonly UL.JSCallback callback = OnCall;     // kept alive: native code holds it
    static IntPtr hwnd;
    public static bool On { get; private set; }

    public static void Install(IntPtr view, IntPtr window)
    {
        hwnd = window;
        var ctx = UL.ulViewLockJSContext(view);
        try
        {
            var name = UL.JSStringCreateWithUTF8CString("__hostKeyboard");
            var fn = UL.JSObjectMakeFunctionWithCallback(ctx, name, callback);
            UL.JSObjectSetProperty(ctx, UL.JSContextGetGlobalObject(ctx), name, fn, 0, IntPtr.Zero);
            UL.JSStringRelease(name);
        }
        finally { UL.ulViewUnlockJSContext(view); }
    }

    static unsafe IntPtr OnCall(IntPtr ctx, IntPtr function, IntPtr thisObject, UIntPtr argc, IntPtr argv, IntPtr exception)
    {
        bool want = (int)argc >= 1 && UL.JSValueToNumber(ctx, ((IntPtr*)argv)[0], IntPtr.Zero) != 0;
        if (want) Start(); else Stop();
        return UL.JSValueMakeUndefined(ctx);
    }

    static void Start()
    {
        if (On) return;
        On = true;
        Win.SetWindowLongPtr(hwnd, Win.GWL_EXSTYLE, new IntPtr(Win.WS_EX_LAYERED | Win.WS_EX_TOOLWINDOW));
        bool ok = Win.SetForegroundWindow(hwnd);
        Program.Log($"keyboard on{(ok ? "" : " (Windows refused the focus)")}");
    }

    // The page is done typing, or another window took the focus.
    public static void Stop()
    {
        if (!On) return;
        On = false;
        Win.SetWindowLongPtr(hwnd, Win.GWL_EXSTYLE, new IntPtr(Win.WS_EX_LAYERED | Win.WS_EX_TOOLWINDOW | Win.WS_EX_NOACTIVATE));
        Win.SetWindowPos(hwnd, Win.HWND_BOTTOM, 0, 0, 0, 0, Win.SWP_NOMOVE | Win.SWP_NOSIZE | Win.SWP_NOACTIVATE);
        Program.Log("keyboard off");
    }

    // Another window took the focus: stop, and let the page blur its field (calls window.__hostKeyboardLost()).
    public static unsafe void Lost(IntPtr view)
    {
        if (!On) return;
        Stop();
        var ctx = UL.ulViewLockJSContext(view);
        try
        {
            var name = UL.JSStringCreateWithUTF8CString("__hostKeyboardLost");
            var fn = UL.JSObjectGetProperty(ctx, UL.JSContextGetGlobalObject(ctx), name, IntPtr.Zero);
            UL.JSStringRelease(name);
            if (UL.JSValueIsObject(ctx, fn) && UL.JSObjectIsFunction(ctx, fn))
                UL.JSObjectCallAsFunction(ctx, fn, IntPtr.Zero, UIntPtr.Zero, null, IntPtr.Zero);
        }
        finally { UL.ulViewUnlockJSContext(view); }
    }

    // WM_KEYDOWN / WM_KEYUP / WM_CHAR (and the SYS ones) while On. Never passed on to DefWindowProc, so Alt+F4
    // can't close the overlay; Alt+Tab and the Windows key still work, the system handles them first.
    public static void Fire(IntPtr view, uint msg, IntPtr wParam, IntPtr lParam)
    {
        int type = msg switch
        {
            Win.WM_KEYDOWN or Win.WM_SYSKEYDOWN => UL.RawKeyDown,
            Win.WM_KEYUP or Win.WM_SYSKEYUP => UL.KeyUp,
            _ => UL.Char,
        };
        bool system = msg == Win.WM_SYSKEYDOWN || msg == Win.WM_SYSKEYUP || msg == Win.WM_SYSCHAR;
        var evt = UL.ulCreateKeyEventWindows(type, (UIntPtr)(ulong)wParam, lParam, system);
        UL.ulViewFireKeyEvent(view, evt);
        UL.ulDestroyKeyEvent(evt);
    }
}
