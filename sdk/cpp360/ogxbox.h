// ogxbox.h - reach an original Xbox game's memory from code running on the 360.
//
// The 360's Xbox emulator (xefu) keeps the Xbox's 64 MB of RAM as one block of
// 360 memory and runs a real x86 Xbox kernel in it. So the game's addresses go
// through ordinary x86 page tables stored in that RAM. This header finds the
// block, walks the tables, and reads and writes with the game's own addresses
// (the ones Ghidra or IDA show for the XBE).
//
// Everything in the game is little endian and the 360 is big endian. Use the
// functions here instead of plain pointers and you never have to think about it.
//
// Include your kernel header (xkelib or your own) before this one, it needs
// MmIsAddressValid. Header only, plain C++, no other dependencies.

#ifndef OGXBOX_H
#define OGXBOX_H

#include <stddef.h>

// How 360 memory is reached. The defaults are right for a plugin on the console.
#ifndef OGX_HOST_PTR
#define OGX_HOST_PTR(address) ((unsigned char*)(size_t)(address))
#endif
#ifndef OGX_HOST_VALID
#define OGX_HOST_VALID(address) (MmIsAddressValid((void*)(size_t)(address)) != 0)
#endif

namespace ogx
{
    typedef unsigned char u8;
    typedef unsigned short u16;
    typedef unsigned int u32;

    const u32 kRamSize = 0x04000000;
    const u32 kPageDir = 0x0000F000;
    const u32 kXbeBase = 0x00010000;
    const u32 kEmuBase = 0x82000000;
    // what XamGetCurrentTitleId() returns while an original Xbox game runs
    const u32 kEmuTitleId = 0xFFFE07D2;

    struct Build
    {
        u32 stamp;          // PE timestamp of the emulator build
        u32 entry;          // PE entry point
        const char* name;
        u32 ramPointer;     // global that holds the Xbox RAM pointer, 0 if not known
    };

    struct State
    {
        u32 ramBase;
        const char* emulator;
    };

    inline State& Current()
    {
        static State state = { 0, 0 };
        return state;
    }

    inline u32 Le16(const u8* p) { return (u32)p[0] | ((u32)p[1] << 8); }
    inline u32 Le32(const u8* p) { return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24); }
    inline u32 Be32(const u8* p) { return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | (u32)p[3]; }

    inline bool LooksLikeRam(u32 base)
    {
        // the emulator's Xbox kernel sits at physical 0x10000 and the page directory maps itself
        if (!OGX_HOST_VALID(base + 0x10000) || !OGX_HOST_VALID(base + kPageDir + 0xC00)) return false;
        const u8* kernel = OGX_HOST_PTR(base + 0x10000);
        if (kernel[0] != 'M' || kernel[1] != 'Z') return false;
        return (Le32(OGX_HOST_PTR(base + kPageDir + 0x300 * 4)) & 0xFFFFF001) == (kPageDir | 1);
    }

    // Looks for a running original Xbox game. Call again after the game changes.
    inline bool Attach()
    {
        static const Build builds[] =
        {
            { 0x437ACD68, 0x000B4328, "xefu", 0 },
            { 0x4537DDE5, 0x000B4570, "xefu1_1", 0 },
            { 0x43E94E5E, 0x000B51A0, "xefu2", 0 },
            { 0x442C87BD, 0x000AF3F8, "xefu3", 0 },
            { 0x44F633D3, 0x000AF058, "xefu5", 0 },
            { 0x457DD568, 0x000C37D0, "xefu6", 0 },
            { 0x474B3577, 0x000C3DA0, "xefu7", 0x821DE210 },
            { 0x474B3577, 0x000C1C48, "xefu7b", 0 },
        };

        State& state = Current();
        state.ramBase = 0;
        state.emulator = 0;

        if (!OGX_HOST_VALID(kEmuBase) || !OGX_HOST_VALID(kEmuBase + 0x3FF)) return false;
        const u8* head = OGX_HOST_PTR(kEmuBase);
        if (head[0] != 'M' || head[1] != 'Z') return false;
        u32 pe = Le32(head + 0x3C);
        if (pe > 0x400 - 0x2C) return false;
        u32 stamp = Le32(head + pe + 8);
        u32 entry = Le32(head + pe + 0x28);

        const Build* build = 0;
        for (size_t i = 0; i < sizeof(builds) / sizeof(builds[0]); i++)
            if (builds[i].stamp == stamp && builds[i].entry == entry) build = &builds[i];
        if (!build) return false;

        u32 base = 0;
        if (build->ramPointer && OGX_HOST_VALID(build->ramPointer))
        {
            u32 candidate = Be32(OGX_HOST_PTR(build->ramPointer));
            if (candidate && LooksLikeRam(candidate)) base = candidate;
        }
        // other builds: try every 16 MB step of the 360's physical memory window
        for (u32 b = 0xC0000000; !base && b < 0xE0000000; b += 0x01000000)
            if (LooksLikeRam(b)) base = b;
        if (!base) return false;

        state.ramBase = base;
        state.emulator = build->name;
        return true;
    }

    inline bool Attached() { return Current().ramBase != 0; }
    inline void Detach() { Current().ramBase = 0; Current().emulator = 0; }
    inline const char* Emulator() { return Current().emulator; }
    inline u32 RamBase() { return Current().ramBase; }

    // True while the game we attached to is still there. Check it every so often,
    // the RAM goes away when the player quits the game.
    inline bool StillRunning()
    {
        return Attached() && LooksLikeRam(Current().ramBase);
    }

    // Game address -> pointer into 360 memory, or NULL if nothing is mapped there.
    // The pointer is only good up to the end of that 4 KB page, and what it points
    // at is little endian. Read() and Write() below handle both for you.
    inline u8* Ptr(u32 address)
    {
        u32 base = Current().ramBase;
        if (!base) return 0;
        u32 slot = base + kPageDir + (address >> 22) * 4;
        if (!OGX_HOST_VALID(slot)) return 0;
        u32 pde = Le32(OGX_HOST_PTR(slot));
        if (!(pde & 1)) return 0;

        u32 physical;
        if (pde & 0x80)
        {
            physical = (pde & 0xFFC00000) | (address & 0x3FFFFF);      // 4 MB page
        }
        else
        {
            u32 table = pde & 0xFFFFF000;
            if (table >= kRamSize) return 0;
            slot = base + table + ((address >> 12) & 0x3FF) * 4;
            if (!OGX_HOST_VALID(slot)) return 0;
            u32 pte = Le32(OGX_HOST_PTR(slot));
            if (!(pte & 1)) return 0;
            physical = (pte & 0xFFFFF000) | (address & 0xFFF);
        }
        if (physical >= kRamSize || !OGX_HOST_VALID(base + physical)) return 0;
        return OGX_HOST_PTR(base + physical);
    }

    inline bool Mapped(u32 address, u32 size = 1)
    {
        for (u32 at = address & ~0xFFFu; at < address + size; at += 0x1000)
            if (!Ptr(at)) return false;
        return true;
    }

    // Raw bytes, exactly as the game has them. False if any part is not mapped
    // (then nothing is read or written).
    inline bool Read(u32 address, void* out, u32 size)
    {
        if (!Mapped(address, size)) return false;
        u8* dst = (u8*)out;
        while (size)
        {
            u32 n = 0x1000 - (address & 0xFFF);
            if (n > size) n = size;
            const u8* src = Ptr(address);
            if (!src) return false;
            for (u32 i = 0; i < n; i++) dst[i] = src[i];
            dst += n;
            address += n;
            size -= n;
        }
        return true;
    }

    inline bool Write(u32 address, const void* in, u32 size)
    {
        if (!Mapped(address, size)) return false;
        const u8* src = (const u8*)in;
        while (size)
        {
            u32 n = 0x1000 - (address & 0xFFF);
            if (n > size) n = size;
            u8* dst = Ptr(address);
            if (!dst) return false;
            for (u32 i = 0; i < n; i++) dst[i] = src[i];
            src += n;
            address += n;
            size -= n;
        }
        return true;
    }

    // Typed reads. An address that is not mapped reads as 0.
    inline u8 ReadU8(u32 address) { u8 b = 0; Read(address, &b, 1); return b; }
    inline u16 ReadU16(u32 address) { u8 b[2] = { 0, 0 }; Read(address, b, 2); return (u16)Le16(b); }
    inline u32 ReadU32(u32 address) { u8 b[4] = { 0, 0, 0, 0 }; Read(address, b, 4); return Le32(b); }
    inline short ReadS16(u32 address) { return (short)ReadU16(address); }
    inline int ReadS32(u32 address) { return (int)ReadU32(address); }
    inline bool ReadBool(u32 address) { return ReadU8(address) != 0; }

    inline float ReadFloat(u32 address)
    {
        union { u32 bits; float value; } u;
        u.bits = ReadU32(address);
        return u.value;
    }

    // Typed writes. False if the address is not mapped.
    inline bool WriteU8(u32 address, u8 value) { return Write(address, &value, 1); }
    inline bool WriteBool(u32 address, bool value) { return WriteU8(address, value ? 1 : 0); }

    inline bool WriteU16(u32 address, u16 value)
    {
        u8 b[2] = { (u8)value, (u8)(value >> 8) };
        return Write(address, b, 2);
    }

    inline bool WriteU32(u32 address, u32 value)
    {
        u8 b[4] = { (u8)value, (u8)(value >> 8), (u8)(value >> 16), (u8)(value >> 24) };
        return Write(address, b, 4);
    }

    inline bool WriteS16(u32 address, short value) { return WriteU16(address, (u16)value); }
    inline bool WriteS32(u32 address, int value) { return WriteU32(address, (u32)value); }

    inline bool WriteFloat(u32 address, float value)
    {
        union { u32 bits; float value; } u;
        u.value = value;
        return WriteU32(address, u.bits);
    }

    // Text up to the first zero byte. Returns the length, out is always terminated.
    inline u32 ReadString(u32 address, char* out, u32 outSize)
    {
        u32 n = 0;
        while (outSize && n + 1 < outSize)
        {
            u8 c = 0;
            if (!Read(address + n, &c, 1) || !c) break;
            out[n++] = (char)c;
        }
        if (outSize) out[n] = 0;
        return n;
    }

    inline bool WriteString(u32 address, const char* text)
    {
        u32 n = 0;
        while (text[n]) n++;
        return Write(address, text, n + 1);
    }

    // Pointer chain: Follow(a, offs, 2) is [[a] + offs[0]] + offs[1].
    inline u32 Follow(u32 address, const u32* offsets, int count)
    {
        for (int i = 0; i < count; i++) address = ReadU32(address) + offsets[i];
        return address;
    }

    // Title ID of the Xbox game itself (from its XBE header), 0 if it has not loaded yet.
    // This is how you tell which game is running, XamGetCurrentTitleId() only says "the emulator".
    inline u32 TitleId()
    {
        if (ReadU32(kXbeBase) != 0x48454258) return 0;      // "XBEH"
        return ReadU32(ReadU32(kXbeBase + 0x118) + 8);
    }

    // The game's name from its XBE header, as 16 bit characters.
    inline u32 TitleName(wchar_t* out, u32 outChars)
    {
        u32 n = 0;
        if (ReadU32(kXbeBase) == 0x48454258)
        {
            u32 name = ReadU32(kXbeBase + 0x118) + 0xC;
            while (outChars && n + 1 < outChars && n < 40)
            {
                u32 c = ReadU16(name + n * 2);
                if (!c) break;
                out[n++] = (wchar_t)c;
            }
        }
        if (outChars) out[n] = 0;
        return n;
    }
}

#endif
