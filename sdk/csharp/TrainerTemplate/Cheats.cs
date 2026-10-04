using System;
using System.Collections.Generic;

namespace TrainerTemplate
{
    public enum CheatType { Byte, Int16, Int32, Float }

    public sealed class Cheat
    {
        public readonly string Name;
        public readonly uint Address;       // the game's own address, as Ghidra/IDA show it for the XBE
        public readonly CheatType Type;
        public readonly string Value;

        public Cheat(string name, uint address, CheatType type, string value)
        {
            Name = name;
            Address = address;
            Type = type;
            Value = value;
        }

        /// <summary>The value as the bytes the game expects (little endian).</summary>
        public byte[] Bytes()
        {
            return Encode(Type, Value);
        }

        public static byte[] Encode(CheatType type, string value)
        {
            byte[] b;
            switch (type)
            {
                case CheatType.Byte: return new[] { byte.Parse(value) };
                case CheatType.Int16: b = BitConverter.GetBytes(short.Parse(value)); break;
                case CheatType.Float: b = BitConverter.GetBytes(float.Parse(value, System.Globalization.CultureInfo.InvariantCulture)); break;
                default: b = BitConverter.GetBytes(int.Parse(value)); break;
            }
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            return b;
        }
    }

    /// <summary>
    /// Your cheats, one list per game. The key is the game's title ID, which the
    /// trainer shows in its status line when it connects.
    /// </summary>
    public static class Cheats
    {
        public static readonly Dictionary<uint, Cheat[]> Games = new Dictionary<uint, Cheat[]>
        {
            {
                0x4D57000E,     // Gauntlet Dark Legacy
                new[]
                {
                    // players are 0x6140 bytes apart
                    new Cheat("Player 1: 999 health", 0x00BB85B8, CheatType.Float, "999"),
                    new Cheat("Player 2: 999 health", 0x00BB85B8 + 0x6140, CheatType.Float, "999"),
                    new Cheat("Player 3: 999 health", 0x00BB85B8 + 0x6140 * 2, CheatType.Float, "999"),
                    new Cheat("Player 4: 999 health", 0x00BB85B8 + 0x6140 * 3, CheatType.Float, "999"),
                }
            },
        };
    }
}
