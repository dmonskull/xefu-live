using System;
using System.IO;
using System.Net.Sockets;
using System.Text;

namespace OgXbox
{
    /// <summary>
    /// Talks XBDM straight over TCP (port 730). Needs nothing but xbdm.xex on the
    /// console, so it also works where XDevkit is not installed.
    /// </summary>
    public sealed class XbdmSocket : IHostMemory, IDisposable
    {
        private readonly TcpClient client;
        private readonly Stream stream;
        private readonly object gate = new object();

        public XbdmSocket(string host, int timeoutMs = 8000)
        {
            client = new TcpClient();
            client.ReceiveTimeout = timeoutMs;
            client.SendTimeout = timeoutMs;
            client.Connect(host, 730);
            stream = new BufferedStream(client.GetStream(), 0x4000);
            Status();      // "201- connected"
        }

        private string Line()
        {
            StringBuilder sb = new StringBuilder();
            for (;;)
            {
                int c = stream.ReadByte();
                if (c < 0) throw new IOException("The console closed the connection.");
                if (c == '\n') break;
                if (c != '\r') sb.Append((char)c);
            }
            return sb.ToString();
        }

        private string Status()
        {
            string line = Line();
            int code;
            if (line.Length < 3 || !int.TryParse(line.Substring(0, 3), out code)) throw new IOException("Unexpected reply: " + line);
            if (code >= 400) throw new XboxGameException("XBDM error " + line);
            return line;
        }

        private void Exact(byte[] buffer, int offset, int count)
        {
            while (count > 0)
            {
                int n = stream.Read(buffer, offset, count);
                if (n <= 0) throw new IOException("The console closed the connection.");
                offset += n;
                count -= n;
            }
        }

        /// <summary>Sends one command and returns its status line, for example Command("stop").</summary>
        public string Command(string text)
        {
            lock (gate)
            {
                byte[] raw = Encoding.ASCII.GetBytes(text + "\r\n");
                stream.Write(raw, 0, raw.Length);
                stream.Flush();
                return Status();
            }
        }

        public byte[] Read(uint address, int length)
        {
            lock (gate)
            {
                Command("getmemex addr=0x" + address.ToString("X") + " length=0x" + length.ToString("X"));
                // blocks of up to 0x400 bytes, each after a 2 byte header: low 15 bits = count, top bit = last block
                byte[] result = new byte[length];
                byte[] header = new byte[2];
                int done = 0;
                for (;;)
                {
                    Exact(header, 0, 2);
                    int flags = header[0] | header[1] << 8;
                    int count = flags & 0x7FFF;
                    if (count > length - done)
                    {
                        byte[] extra = new byte[count];
                        Exact(extra, 0, count);
                        Buffer.BlockCopy(extra, 0, result, done, length - done);
                        done = length;
                    }
                    else
                    {
                        Exact(result, done, count);
                        done += count;
                    }
                    if ((flags & 0x8000) != 0 || done >= length) break;
                }
                if (done < length) throw new XboxGameException("Memory at " + (address + (uint)done).ToString("X8") + " is not readable.");
                return result;
            }
        }

        public void Write(uint address, byte[] data)
        {
            lock (gate)
            {
                // the command line is limited, so send small pieces
                for (int off = 0; off < data.Length; off += 0x80)
                {
                    int n = Math.Min(0x80, data.Length - off);
                    StringBuilder hex = new StringBuilder(n * 2);
                    for (int i = 0; i < n; i++) hex.Append(data[off + i].ToString("x2"));
                    Command("setmem addr=0x" + (address + (uint)off).ToString("X") + " data=" + hex);
                }
            }
        }

        /// <summary>Freezes the game. Reads are about ten times faster while it is stopped.</summary>
        public void Stop() { try { Command("stop"); } catch (XboxGameException) { } }

        public void Go() { try { Command("go"); } catch (XboxGameException) { } }

        public void Dispose()
        {
            try { Command("bye"); } catch (Exception) { }
            client.Close();
        }
    }
}
