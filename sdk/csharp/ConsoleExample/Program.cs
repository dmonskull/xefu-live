using System;
using OgXbox;

// Smallest possible tool: connect over plain XBDM, find the game, read and write with its own addresses.
//   dotnet run -- 192.168.1.50
//   dotnet run -- 192.168.1.50 peek BB85B8 float
//   dotnet run -- 192.168.1.50 poke BB85B8 float 999
namespace ConsoleExample
{
    static class Program
    {
        static int Main(string[] args)
        {
            if (args.Length < 1)
            {
                Console.WriteLine("usage: ConsoleExample <console ip> [peek <address> <type> | poke <address> <type> <value>]");
                Console.WriteLine("types: byte, int16, int32, float, string");
                return 1;
            }
            using (XbdmSocket xbdm = new XbdmSocket(args[0]))
            {
                XboxGame game = new XboxGame(xbdm);
                if (!game.Attach())
                {
                    Console.WriteLine("No original Xbox game is running on that console.");
                    return 2;
                }
                Console.WriteLine("{0}  (title {1:X8}, {2}, game RAM at {3:X8})", game.TitleName, game.TitleId, game.Emulator, game.RamBase);

                if (args.Length < 3)
                {
                    foreach (XbeSection s in game.Sections)
                        Console.WriteLine("  {0,-10} {1:X8} - {2:X8}{3}", s.Name, s.Address, s.Address + s.Size, s.Writable ? "  writable" : "");
                    return 0;
                }

                try
                {
                    uint address = Convert.ToUInt32(args[2], 16);
                    string type = args.Length > 3 ? args[3] : "int32";
                    if (args[1] == "poke") Poke(game, address, type, args[4]);
                    Console.WriteLine(Peek(game, address, type));
                    Console.WriteLine("360 address: {0:X8}", game.ToHost(address));
                    return 0;
                }
                catch (XboxGameException e)
                {
                    Console.WriteLine(e.Message);
                    return 3;
                }
            }
        }

        static object Peek(XboxGame game, uint address, string type)
        {
            switch (type)
            {
                case "byte": return game.ReadByte(address);
                case "int16": return game.ReadInt16(address);
                case "float": return game.ReadFloat(address);
                case "string": return game.ReadString(address);
                default: return game.ReadInt32(address);
            }
        }

        static void Poke(XboxGame game, uint address, string type, string value)
        {
            switch (type)
            {
                case "byte": game.WriteByte(address, byte.Parse(value)); break;
                case "int16": game.WriteInt16(address, short.Parse(value)); break;
                case "float": game.WriteFloat(address, float.Parse(value)); break;
                case "string": game.WriteString(address, value); break;
                default: game.WriteInt32(address, int.Parse(value)); break;
            }
        }
    }
}
