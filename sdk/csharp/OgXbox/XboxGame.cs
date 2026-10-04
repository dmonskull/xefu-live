using System;
using System.Collections.Generic;
using System.Text;

namespace OgXbox
{
    public sealed class XbeSection
    {
        public string Name;
        public uint Address;
        public uint Size;
        public bool Writable;
    }

    /// <summary>
    /// An original Xbox game running in the 360's emulator (xefu).
    ///
    /// The emulator keeps the Xbox's 64 MB of RAM as one block of 360 memory and
    /// runs a real x86 Xbox kernel in it, so game addresses go through ordinary
    /// x86 page tables stored in that RAM. This class finds the block, walks the
    /// tables and lets you read and write with the game's own addresses, the
    /// ones Ghidra or IDA show for the XBE. Values are little endian like on a
    /// real Xbox, so the usual big endian helpers (xbCon.ReadUInt32, WriteFloat
    /// and so on) give wrong results on game data. Use the methods here.
    /// </summary>
    public sealed class XboxGame
    {
        private const uint RamSize = 0x04000000;
        private const uint PageDir = 0x0000F000;
        private const uint XbeBase = 0x00010000;
        private const uint EmuBase = 0x82000000;

        // (PE timestamp, entry point) of each emulator build
        private static readonly uint[,] Builds =
        {
            { 0x437ACD68, 0x000B4328 }, { 0x4537DDE5, 0x000B4570 }, { 0x43E94E5E, 0x000B51A0 },
            { 0x442C87BD, 0x000AF3F8 }, { 0x44F633D3, 0x000AF058 }, { 0x457DD568, 0x000C37D0 },
            { 0x474B3577, 0x000C3DA0 }, { 0x474B3577, 0x000C1C48 },
        };
        private static readonly string[] BuildNames =
        {
            "xefu", "xefu1_1", "xefu2", "xefu3", "xefu5", "xefu6", "xefu7", "xefu7b",
        };
        // xefu7 keeps the pointer to the Xbox RAM here
        private const uint Xefu7RamPointer = 0x821DE210;

        private readonly IHostMemory host;
        private readonly object gate = new object();
        private uint xbeHost;
        private byte[] xbeMark;
        private readonly Dictionary<uint, uint[]> tables = new Dictionary<uint, uint[]>();
        private readonly Dictionary<uint, DateTime> tableTimes = new Dictionary<uint, DateTime>();
        private uint[] directory;
        private DateTime directoryTime;

        /// <summary>How long page tables are trusted for reads. Writes always check fresh.</summary>
        public TimeSpan TableLifetime = TimeSpan.FromSeconds(10);

        public string Emulator { get; private set; }
        public uint RamBase { get; private set; }
        public uint TitleId { get; private set; }
        public string TitleName { get; private set; }
        public List<XbeSection> Sections { get; private set; }
        public bool IsAttached { get { return RamBase != 0; } }

        public XboxGame(IHostMemory host)
        {
            this.host = host;
            Sections = new List<XbeSection>();
        }

        /// <summary>Looks for a running original Xbox game. False if there is none.</summary>
        public bool Attach()
        {
            lock (gate) return AttachNow();
        }

        /// <summary>
        /// True while the game that was attached is still the one running. One small
        /// read, so it is cheap enough to call before each batch of work.
        /// </summary>
        public bool StillRunning()
        {
            lock (gate)
            {
                if (RamBase == 0 || xbeMark == null) return false;
                byte[] now = TryRead(xbeHost, xbeMark.Length);
                if (now == null) return false;
                for (int i = 0; i < now.Length; i++)
                    if (now[i] != xbeMark[i]) return false;
                return true;
            }
        }

        private bool AttachNow()
        {
            RamBase = 0;
            xbeMark = null;
            Emulator = null;
            TitleId = 0;
            TitleName = null;
            Sections = new List<XbeSection>();
            Forget();

            byte[] head = TryRead(EmuBase, 0x400);
            if (head == null || head[0] != 'M' || head[1] != 'Z') return false;
            int pe = (int)Le32(head, 0x3C);
            if (pe < 0 || pe + 0x2C > head.Length) return false;
            uint stamp = Le32(head, pe + 8), entry = Le32(head, pe + 0x28);
            for (int i = 0; i < BuildNames.Length; i++)
                if (Builds[i, 0] == stamp && Builds[i, 1] == entry) Emulator = BuildNames[i];
            if (Emulator == null) return false;

            uint found = 0;
            if (Emulator == "xefu7")
            {
                byte[] p = TryRead(Xefu7RamPointer, 4);
                if (p != null)
                {
                    uint candidate = (uint)(p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]);
                    if (candidate != 0 && LooksLikeRam(candidate)) found = candidate;
                }
            }
            // other builds: try every 16 MB step of the 360's physical memory window
            for (uint b = 0xC0000000; found == 0 && b < 0xE0000000; b += 0x01000000)
                if (LooksLikeRam(b)) found = b;
            if (found == 0) return false;

            RamBase = found;
            ReadXbe();
            return true;
        }

        private bool LooksLikeRam(uint b)
        {
            // the emulator's Xbox kernel sits at physical 0x10000 and the page directory maps itself
            byte[] mz = TryRead(b + 0x10000, 2);
            if (mz == null || mz[0] != 'M' || mz[1] != 'Z') return false;
            byte[] self = TryRead(b + PageDir + 0x300 * 4, 4);
            return self != null && (Le32(self, 0) & 0xFFFFF001) == (PageDir | 1);
        }

        private byte[] TryRead(uint address, int length)
        {
            try
            {
                byte[] data = host.Read(address, length);
                return data != null && data.Length == length ? data : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private void ReadXbe()
        {
            byte[] head;
            try { head = ReadBytes(XbeBase, 0x1000); }
            catch (XboxGameException) { return; }
            if (head[0] != 'X' || head[1] != 'B' || head[2] != 'E' || head[3] != 'H') return;
            // the start of the header (magic plus the game's signature) tells us later if the game changed
            uint physical;
            if (Walk(XbeBase, false, out physical))
            {
                xbeHost = RamBase + physical;
                xbeMark = new byte[0x20];
                Buffer.BlockCopy(head, 0, xbeMark, 0, 0x20);
            }
            uint imageBase = Le32(head, 0x104), headerSize = Le32(head, 0x108);
            uint cert = Le32(head, 0x118), count = Le32(head, 0x11C), sections = Le32(head, 0x120);
            if (headerSize > 0x1000 && headerSize <= 0x8000)
            {
                try { head = ReadBytes(imageBase, (int)headerSize); }
                catch (XboxGameException) { }
            }
            long c = (long)cert - imageBase;
            if (c >= 0 && c + 0x5C <= head.Length)
            {
                TitleId = Le32(head, (int)c + 8);
                TitleName = Encoding.Unicode.GetString(head, (int)c + 0xC, 80).Split('\0')[0];
            }
            for (uint i = 0; i < count && i < 64; i++)
            {
                long s = (long)sections + i * 0x38 - imageBase;
                if (s < 0 || s + 0x18 > head.Length) break;
                XbeSection sec = new XbeSection();
                uint flags = Le32(head, (int)s);
                sec.Address = Le32(head, (int)s + 4);
                sec.Size = Le32(head, (int)s + 8);
                sec.Writable = (flags & 1) != 0;
                long n = (long)Le32(head, (int)s + 0x14) - imageBase;
                sec.Name = "";
                for (long k = n; k >= 0 && k < head.Length && k < n + 16 && head[k] != 0; k++) sec.Name += (char)head[k];
                Sections.Add(sec);
            }
        }

        /// <summary>Drops the cached page tables. Call after the game loads a level if addresses look stale.</summary>
        public void Forget()
        {
            lock (gate)
            {
                directory = null;
                tables.Clear();
                tableTimes.Clear();
            }
        }

        private void NeedGame()
        {
            if (RamBase == 0) throw new XboxGameException("No original Xbox game is attached. Call Attach() first.");
        }

        private uint[] Table(uint physical, bool fresh)
        {
            DateTime now = DateTime.UtcNow;
            uint[] t;
            if (!fresh && tables.TryGetValue(physical, out t) && now - tableTimes[physical] < TableLifetime) return t;
            byte[] raw = host.Read(RamBase + physical, 0x1000);
            t = new uint[1024];
            for (int i = 0; i < 1024; i++) t[i] = Le32(raw, i * 4);
            tables[physical] = t;
            tableTimes[physical] = now;
            return t;
        }

        private bool Walk(uint address, bool fresh, out uint physical)
        {
            physical = 0;
            uint pde;
            if (fresh)
            {
                pde = Le32(host.Read(RamBase + PageDir + (address >> 22) * 4, 4), 0);
            }
            else
            {
                if (directory == null || DateTime.UtcNow - directoryTime >= TableLifetime)
                {
                    directory = Table(PageDir, true);
                    directoryTime = DateTime.UtcNow;
                }
                pde = directory[address >> 22];
            }
            if ((pde & 1) == 0) return false;
            if ((pde & 0x80) != 0)
            {
                physical = (pde & 0xFFC00000) | (address & 0x3FFFFF);      // 4 MB page
            }
            else
            {
                uint table = pde & 0xFFFFF000;
                if (table >= RamSize) return false;
                uint pte;
                if (fresh) pte = Le32(host.Read(RamBase + table + ((address >> 12) & 0x3FF) * 4, 4), 0);
                else pte = Table(table, false)[(address >> 12) & 0x3FF];
                if ((pte & 1) == 0) return false;
                physical = (pte & 0xFFFFF000) | (address & 0xFFF);
            }
            return physical < RamSize;
        }

        /// <summary>Game address to the 360 address behind it. False if nothing is mapped there.</summary>
        public bool TryToHost(uint address, out uint hostAddress)
        {
            lock (gate)
            {
                NeedGame();
                uint physical;
                bool ok = Walk(address, false, out physical);
                hostAddress = ok ? RamBase + physical : 0;
                return ok;
            }
        }

        public uint ToHost(uint address)
        {
            uint h;
            if (!TryToHost(address, out h)) throw new XboxGameException("Game address " + address.ToString("X8") + " is not mapped.");
            return h;
        }

        public byte[] ReadBytes(uint address, int length)
        {
            lock (gate) return ReadNow(address, length);
        }

        public void WriteBytes(uint address, byte[] data)
        {
            lock (gate) WriteNow(address, data);
        }

        private byte[] ReadNow(uint address, int length)
        {
            NeedGame();
            byte[] result = new byte[length];
            int done = 0;
            while (done < length)
            {
                uint at = address + (uint)done;
                int n = Math.Min(0x1000 - (int)(at & 0xFFF), length - done);
                uint physical;
                if (!Walk(at, false, out physical)) throw new XboxGameException("Game address " + at.ToString("X8") + " is not mapped.");
                // keep going while the next pages follow on in physical memory, so big reads stay one request
                int run = n;
                while (done + run < length)
                {
                    uint next;
                    if (!Walk(at + (uint)run, false, out next) || next != physical + (uint)run) break;
                    run += Math.Min(0x1000, length - done - run);
                }
                Buffer.BlockCopy(host.Read(RamBase + physical, run), 0, result, done, run);
                done += run;
            }
            return result;
        }

        private void WriteNow(uint address, byte[] data)
        {
            NeedGame();
            // check every page first, fresh from the console, so nothing is half written or sent through a stale mapping
            List<uint> targets = new List<uint>();
            int done = 0;
            while (done < data.Length)
            {
                uint at = address + (uint)done;
                uint physical;
                if (!Walk(at, true, out physical)) throw new XboxGameException("Game address " + at.ToString("X8") + " is not mapped. Nothing was written.");
                targets.Add(RamBase + physical);
                done += Math.Min(0x1000 - (int)(at & 0xFFF), data.Length - done);
            }
            done = 0;
            foreach (uint target in targets)
            {
                int n = Math.Min(0x1000 - (int)((address + (uint)done) & 0xFFF), data.Length - done);
                byte[] part = new byte[n];
                Buffer.BlockCopy(data, done, part, 0, n);
                host.Write(target, part);
                done += n;
            }
        }

        /// <summary>Follows a pointer chain: Follow(a, 0x10, 0x4) is [[a] + 0x10] + 0x4.</summary>
        public uint Follow(uint address, params uint[] offsets)
        {
            foreach (uint offset in offsets) address = ReadUInt32(address) + offset;
            return address;
        }

        public byte ReadByte(uint address) { return ReadBytes(address, 1)[0]; }
        public sbyte ReadSByte(uint address) { return (sbyte)ReadBytes(address, 1)[0]; }
        public bool ReadBool(uint address) { return ReadBytes(address, 1)[0] != 0; }
        public ushort ReadUInt16(uint address) { byte[] b = ReadBytes(address, 2); return (ushort)(b[0] | b[1] << 8); }
        public short ReadInt16(uint address) { return (short)ReadUInt16(address); }
        public uint ReadUInt32(uint address) { return Le32(ReadBytes(address, 4), 0); }
        public int ReadInt32(uint address) { return (int)ReadUInt32(address); }
        public float ReadFloat(uint address) { return BitConverter.ToSingle(Native(ReadBytes(address, 4)), 0); }
        public double ReadDouble(uint address) { return BitConverter.ToDouble(Native(ReadBytes(address, 8)), 0); }

        /// <summary>Reads text up to the first zero byte.</summary>
        public string ReadString(uint address, int maxLength = 64)
        {
            byte[] b = ReadBytes(address, maxLength);
            int n = Array.IndexOf(b, (byte)0);
            return Encoding.ASCII.GetString(b, 0, n < 0 ? b.Length : n);
        }

        public string ReadUnicodeString(uint address, int maxChars = 64)
        {
            return Encoding.Unicode.GetString(ReadBytes(address, maxChars * 2)).Split('\0')[0];
        }

        public void WriteByte(uint address, byte value) { WriteBytes(address, new[] { value }); }
        public void WriteSByte(uint address, sbyte value) { WriteBytes(address, new[] { (byte)value }); }
        public void WriteBool(uint address, bool value) { WriteBytes(address, new[] { (byte)(value ? 1 : 0) }); }
        public void WriteUInt16(uint address, ushort value) { WriteBytes(address, new[] { (byte)value, (byte)(value >> 8) }); }
        public void WriteInt16(uint address, short value) { WriteUInt16(address, (ushort)value); }
        public void WriteUInt32(uint address, uint value)
        {
            WriteBytes(address, new[] { (byte)value, (byte)(value >> 8), (byte)(value >> 16), (byte)(value >> 24) });
        }
        public void WriteInt32(uint address, int value) { WriteUInt32(address, (uint)value); }
        public void WriteFloat(uint address, float value) { WriteBytes(address, Native(BitConverter.GetBytes(value))); }
        public void WriteDouble(uint address, double value) { WriteBytes(address, Native(BitConverter.GetBytes(value))); }

        /// <summary>Writes text followed by a zero byte.</summary>
        public void WriteString(uint address, string text)
        {
            byte[] b = Encoding.ASCII.GetBytes(text);
            Array.Resize(ref b, b.Length + 1);
            WriteBytes(address, b);
        }

        public void WriteUnicodeString(uint address, string text)
        {
            byte[] b = Encoding.Unicode.GetBytes(text);
            Array.Resize(ref b, b.Length + 2);
            WriteBytes(address, b);
        }

        private static uint Le32(byte[] b, int i)
        {
            return (uint)(b[i] | b[i + 1] << 8 | b[i + 2] << 16 | b[i + 3] << 24);
        }

        // BitConverter follows the PC's byte order, the game is always little endian
        private static byte[] Native(byte[] littleEndian)
        {
            if (!BitConverter.IsLittleEndian) Array.Reverse(littleEndian);
            return littleEndian;
        }
    }
}
