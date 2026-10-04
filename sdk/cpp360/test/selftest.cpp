// Builds a tiny fake Xbox RAM image on a PC and checks the address translation.
//   c++ -I.. selftest.cpp -o selftest && ./selftest
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char* g_emu;    // stands in for 0x82000000
static unsigned char* g_ram;    // stands in for the Xbox RAM block
static const unsigned int kFakeRam = 0xD0000000;

static unsigned char* FakePtr(unsigned int a)
{
    if (a >= 0x82000000 && a < 0x82000000 + 0x200000) return g_emu + (a - 0x82000000);
    if (a >= kFakeRam && a - kFakeRam < 0x04000000) return g_ram + (a - kFakeRam);
    return 0;
}

#define OGX_HOST_PTR(address) FakePtr((unsigned int)(address))
#define OGX_HOST_VALID(address) (FakePtr((unsigned int)(address)) != 0)
#include "ogxbox.h"

static void Put32(unsigned char* p, unsigned int v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

static int failures;
#define CHECK(what) do { if (!(what)) { printf("FAILED: %s\n", #what); failures++; } } while (0)

int main()
{
    g_emu = (unsigned char*)calloc(1, 0x200000);
    g_ram = (unsigned char*)calloc(1, 0x04000000);

    // emulator image: PE header with xefu7's timestamp and entry, and its RAM pointer (big endian)
    g_emu[0] = 'M'; g_emu[1] = 'Z';
    Put32(g_emu + 0x3C, 0xE0);
    Put32(g_emu + 0xE0 + 8, 0x474B3577);
    Put32(g_emu + 0xE0 + 0x28, 0x000C3DA0);
    unsigned char* global = g_emu + 0x1DE210;
    global[0] = 0xD0; global[1] = 0; global[2] = 0; global[3] = 0;

    // Xbox RAM: kernel marker, page directory with self map, one page table
    g_ram[0x10000] = 'M'; g_ram[0x10001] = 'Z';
    unsigned char* pd = g_ram + 0xF000;
    Put32(pd + 0x300 * 4, 0x0000F063);
    Put32(pd + 0 * 4, 0x00039067);                  // table for 0x00000000 - 0x003FFFFF
    unsigned char* pt = g_ram + 0x39000;
    Put32(pt + 0x10 * 4, 0x0003A067);               // 0x10000 -> physical 0x3A000
    Put32(pt + 0x11 * 4, 0x00200067);               // 0x11000 -> physical 0x200000 (not next to it)
    Put32(pd + 0x3C0 * 4, 0x000000EB);              // 4 MB page: 0xF0000000 -> physical 0

    // XBE header at 0x10000 with a certificate at 0x10200
    unsigned char* xbe = g_ram + 0x3A000;
    memcpy(xbe, "XBEH", 4);
    Put32(xbe + 0x118, 0x00010200);
    Put32(xbe + 0x200 + 8, 0x4D57000E);
    const char* name = "Test Game";
    for (int i = 0; name[i]; i++) xbe[0x200 + 0xC + i * 2] = name[i];

    CHECK(ogx::Attach());
    CHECK(ogx::RamBase() == kFakeRam);
    CHECK(strcmp(ogx::Emulator(), "xefu7") == 0);
    CHECK(ogx::StillRunning());
    CHECK(ogx::TitleId() == 0x4D57000E);
    wchar_t title[41];
    CHECK(ogx::TitleName(title, 41) == 9 && title[0] == 'T' && title[8] == 'e');

    CHECK(ogx::Ptr(0x00010000) == g_ram + 0x3A000);
    CHECK(ogx::Ptr(0x00011004) == g_ram + 0x200004);
    CHECK(ogx::Ptr(0x00012000) == 0);
    CHECK(ogx::Ptr(0x05000000) == 0);
    CHECK(ogx::Ptr(0xF0010002) == g_ram + 0x10002);
    CHECK(ogx::Mapped(0x10FFE, 4) && !ogx::Mapped(0x11FFE, 4));

    // values are stored little endian whatever the machine running this is
    CHECK(ogx::WriteU32(0x00010800, 0x11223344));
    CHECK(xbe[0x800] == 0x44 && xbe[0x803] == 0x11);
    CHECK(ogx::ReadU32(0x00010800) == 0x11223344 && ogx::ReadU16(0x00010800) == 0x3344 && ogx::ReadU8(0x00010803) == 0x11);
    CHECK(ogx::WriteFloat(0x00010810, 500.0f));
    CHECK(xbe[0x810] == 0x00 && xbe[0x812] == 0xFA && xbe[0x813] == 0x43);
    CHECK(ogx::ReadFloat(0x00010810) == 500.0f);

    // a value that straddles two pages which are not neighbours in physical memory
    CHECK(ogx::WriteU32(0x00010FFE, 0xAABBCCDD));
    CHECK(g_ram[0x3AFFE] == 0xDD && g_ram[0x3AFFF] == 0xCC && g_ram[0x200000] == 0xBB && g_ram[0x200001] == 0xAA);
    CHECK(ogx::ReadU32(0x00010FFE) == 0xAABBCCDD);

    // nothing is written when part of the range is unmapped
    CHECK(!ogx::WriteU32(0x00011FFE, 0x12345678) && g_ram[0x200FFE] == 0);
    CHECK(ogx::ReadU32(0x05000000) == 0);

    CHECK(ogx::WriteString(0x00010900, "DMON"));
    char text[16];
    CHECK(ogx::ReadString(0x00010900, text, sizeof(text)) == 4 && strcmp(text, "DMON") == 0);

    ogx::WriteU32(0x00010A00, 0x00010B00);
    ogx::WriteU32(0x00010B10, 0x00010C00);
    ogx::u32 offsets[2] = { 0x10, 0x4 };
    CHECK(ogx::Follow(0x00010A00, offsets, 2) == 0x00010C04);

    g_ram[0x10000] = 0;         // the game went away
    CHECK(!ogx::StillRunning());

    printf(failures ? "%d check(s) failed\n" : "all checks passed\n", failures);
    return failures ? 1 : 0;
}
