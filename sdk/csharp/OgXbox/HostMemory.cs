using System;

namespace OgXbox
{
    /// <summary>Raw Xbox 360 memory. Wrap whatever you already use (XDevkit, XBDM) in this.</summary>
    public interface IHostMemory
    {
        byte[] Read(uint address, int length);
        void Write(uint address, byte[] data);
    }

    /// <summary>Builds an IHostMemory out of two lambdas.</summary>
    public sealed class DelegateHost : IHostMemory
    {
        private readonly Func<uint, int, byte[]> read;
        private readonly Action<uint, byte[]> write;

        public DelegateHost(Func<uint, int, byte[]> read, Action<uint, byte[]> write)
        {
            this.read = read;
            this.write = write;
        }

        public byte[] Read(uint address, int length) { return read(address, length); }
        public void Write(uint address, byte[] data) { write(address, data); }
    }

    public class XboxGameException : Exception
    {
        public XboxGameException(string message) : base(message) { }
    }
}
