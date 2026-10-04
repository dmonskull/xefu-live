using System;
using System.Collections.Generic;
using System.Threading;

namespace OgXbox
{
    /// <summary>
    /// Keeps writing values so the game cannot change them back (infinite health and the like).
    ///
    /// Either call Apply() yourself from a WinForms timer, or call Start() to have
    /// it run on its own thread. With XDevkit use the WinForms timer: XDevkit is
    /// COM and likes to stay on the thread that created it.
    /// </summary>
    public sealed class Freezer : IDisposable
    {
        private readonly XboxGame game;
        private readonly Dictionary<uint, byte[]> values = new Dictionary<uint, byte[]>();
        private readonly object round = new object();
        private Timer timer;

        /// <summary>The last write problem, if any (for example the address is not mapped any more).</summary>
        public string LastError { get; private set; }

        public Freezer(XboxGame game)
        {
            this.game = game;
        }

        public int Count { get { lock (values) return values.Count; } }

        public void Set(uint address, byte[] littleEndianBytes) { lock (values) values[address] = littleEndianBytes; }
        public void SetFloat(uint address, float value) { Set(address, Little(BitConverter.GetBytes(value))); }
        public void SetInt32(uint address, int value) { Set(address, Little(BitConverter.GetBytes(value))); }
        public void SetInt16(uint address, short value) { Set(address, Little(BitConverter.GetBytes(value))); }
        public void SetByte(uint address, byte value) { Set(address, new[] { value }); }
        public void Remove(uint address) { lock (values) values.Remove(address); }
        public void Clear() { lock (values) values.Clear(); }

        private static byte[] Little(byte[] b)
        {
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            return b;
        }

        /// <summary>Writes every frozen value once.</summary>
        public void Apply()
        {
            if (!Monitor.TryEnter(round)) return;      // the last round is still writing
            try
            {
                KeyValuePair<uint, byte[]>[] copy;
                lock (values)
                {
                    copy = new KeyValuePair<uint, byte[]>[values.Count];
                    ((ICollection<KeyValuePair<uint, byte[]>>)values).CopyTo(copy, 0);
                }
                foreach (KeyValuePair<uint, byte[]> item in copy)
                {
                    try { game.WriteBytes(item.Key, item.Value); LastError = null; }
                    catch (Exception e) { LastError = e.Message; }
                }
            }
            finally { Monitor.Exit(round); }
        }

        /// <summary>Runs Apply() on a background timer.</summary>
        public void Start(int intervalMs = 250)
        {
            Stop();
            timer = new Timer(delegate { Apply(); }, null, intervalMs, intervalMs);
        }

        public void Stop()
        {
            if (timer != null) timer.Dispose();
            timer = null;
        }

        public void Dispose() { Stop(); }
    }
}
