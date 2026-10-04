using XDevkit;

namespace OgXbox
{
    /// <summary>
    /// 360 memory through an XDevkit console, the same calls DMONET's
    /// xbCon.ReadBytes / xbCon.WriteBytes make.
    /// </summary>
    public sealed class XDevkitHost : IHostMemory
    {
        private readonly IXboxConsole console;

        public XDevkitHost(IXboxConsole console)
        {
            this.console = console;
        }

        public byte[] Read(uint address, int length)
        {
            byte[] data = new byte[length];
            uint done;
            console.DebugTarget.GetMemory(address, (uint)length, data, out done);
            // XDevkit caches what it reads, without this you keep getting the old bytes
            console.DebugTarget.InvalidateMemoryCache(true, address, (uint)length);
            return data;
        }

        public void Write(uint address, byte[] data)
        {
            uint done;
            console.DebugTarget.SetMemory(address, (uint)data.Length, data, out done);
        }
    }
}
