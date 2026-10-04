using System;
using System.Runtime.InteropServices;
using XDevkit;

namespace OgXbox
{
    /// <summary>
    /// Connects to the default console through XDevkit, the same way DMONET does it.
    /// The console is the one set as default in Xbox 360 Neighborhood.
    /// </summary>
    public static class XboxConnection
    {
        public static IXboxManager xbManager = null;
        public static IXboxConsole xbCon = null;
        public static bool activeConnection = false;

        public static bool ConnectToConsole()
        {
            string debuggerName, userName;
            if (activeConnection && xbCon.DebugTarget.IsDebuggerConnected(out debuggerName, out userName))
            {
                return true;
            }
            try
            {
                xbManager = (XboxManager)Activator.CreateInstance(Marshal.GetTypeFromCLSID(new Guid("A5EB45D8-F3B6-49B9-984A-0D313AB60342")));
                xbCon = xbManager.OpenConsole(xbManager.DefaultConsole);
                xbCon.OpenConnection(null);

                if (!xbCon.DebugTarget.IsDebuggerConnected(out debuggerName, out userName))
                {
                    xbCon.DebugTarget.ConnectAsDebugger("OgXbox", XboxDebugConnectFlags.Force);
                }

                activeConnection = xbCon.DebugTarget.IsDebuggerConnected(out debuggerName, out userName);
                return activeConnection;
            }
            catch (Exception)
            {
                activeConnection = false;
                return false;
            }
        }
    }
}
