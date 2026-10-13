// Network requests for the page, made by the host instead of Ultralight.
// Ultralight 1.3 leaks roughly 150 KB of native memory per fetch (with or without keep-alive), which for a page
// that polls several times a second means hundreds of MB a day. So the page gets a function,
// __hostFetch(id, method, url, body), and web/compat.js routes same-origin fetch() calls through it. The answer
// comes back on the UI thread as __hostFetchDone(id, status, text); status 0 means the request failed.
// The answer is passed by calling that function through the JavaScriptCore API, never as script source:
// evaluating a new piece of source per response made JavaScriptCore compile and keep every one of them.
using System;
using System.Collections.Concurrent;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace HubOverlay;

static class HostFetch
{
    static readonly HttpClient http = new() { Timeout = TimeSpan.FromSeconds(15) };
    static readonly ConcurrentQueue<(int id, int status, string text)> done = new();
    static readonly IntPtr doneName = UL.JSStringCreateWithUTF8CString("__hostFetchDone");   // kept for the process
    static readonly UL.JSCallback callback = OnCall;     // kept alive: native code holds it
    static Uri origin;

    // Defines __hostFetch on the page's window. Call it from the window-object-ready callback.
    public static void Install(IntPtr view, string pageUrl)
    {
        origin = new Uri(new Uri(pageUrl).GetLeftPart(UriPartial.Authority));
        var ctx = UL.ulViewLockJSContext(view);
        try
        {
            var name = UL.JSStringCreateWithUTF8CString("__hostFetch");
            var fn = UL.JSObjectMakeFunctionWithCallback(ctx, name, callback);
            UL.JSObjectSetProperty(ctx, UL.JSContextGetGlobalObject(ctx), name, fn, 0, IntPtr.Zero);
            UL.JSStringRelease(name);
        }
        finally { UL.ulViewUnlockJSContext(view); }
    }

    // Hands finished requests to the page. Call it on the UI thread, e.g. every frame.
    public static unsafe void Deliver(IntPtr view)
    {
        if (done.IsEmpty) return;
        var ctx = UL.ulViewLockJSContext(view);
        try
        {
            var fn = UL.JSObjectGetProperty(ctx, UL.JSContextGetGlobalObject(ctx), doneName, IntPtr.Zero);
            bool callable = UL.JSValueIsObject(ctx, fn) && UL.JSObjectIsFunction(ctx, fn);
            while (done.TryDequeue(out var r))
            {
                if (!callable) continue;              // a page without compat.js: nobody is waiting
                var text = UL.JSStringCreateWithUTF8CString(r.text);
                var args = stackalloc IntPtr[3];
                args[0] = UL.JSValueMakeNumber(ctx, r.id);
                args[1] = UL.JSValueMakeNumber(ctx, r.status);
                args[2] = UL.JSValueMakeString(ctx, text);
                UL.JSStringRelease(text);
                UL.JSObjectCallAsFunction(ctx, fn, IntPtr.Zero, (UIntPtr)3, args, IntPtr.Zero);
            }
        }
        finally { UL.ulViewUnlockJSContext(view); }
    }

    static unsafe IntPtr OnCall(IntPtr ctx, IntPtr function, IntPtr thisObject, UIntPtr argc, IntPtr argv, IntPtr exception)
    {
        var args = (IntPtr*)argv;
        if ((int)argc >= 4)
        {
            int id = (int)UL.JSValueToNumber(ctx, args[0], IntPtr.Zero);
            string method = UL.JsString(ctx, args[1]), url = UL.JsString(ctx, args[2]), body = UL.JsString(ctx, args[3]);
            _ = Run(id, method, url, body);
        }
        return UL.JSValueMakeUndefined(ctx);
    }

    static async Task Run(int id, string method, string url, string body)
    {
        int status = 0;
        string text = "";
        try
        {
            var uri = new Uri(url);
            if (uri.GetLeftPart(UriPartial.Authority) != origin.GetLeftPart(UriPartial.Authority))
                throw new InvalidOperationException("only the hub's own server");
            bool idempotent = method == "GET" || method == "HEAD";
            for (int attempt = 1; ; attempt++)
            {
                try
                {
                    using var req = new HttpRequestMessage(new HttpMethod(method), uri);
                    if (!idempotent) req.Content = new StringContent(body, Encoding.UTF8, "application/json");
                    using var res = await http.SendAsync(req);
                    status = (int)res.StatusCode;
                    text = await res.Content.ReadAsStringAsync();
                    break;
                }
                // While the page loads, a request's connection is sometimes aborted on this machine (WSAECONNABORTED)
                // before the answer arrives; the server never sees a failure. A read can safely be asked again.
                catch (HttpRequestException e) when (idempotent && attempt < 3)
                {
                    Program.Log($"fetch {method} {url}: {e.InnerException?.Message ?? e.Message}; retrying");
                    await Task.Delay(100 * attempt);
                }
            }
        }
        catch (Exception e)
        {
            status = 0;
            Program.Log($"fetch {method} {url} failed: {e.GetType().Name}: {e.Message}{(e.InnerException != null ? " <- " + e.InnerException.Message : "")}");
        }
        done.Enqueue((id, status, text));
    }
}
